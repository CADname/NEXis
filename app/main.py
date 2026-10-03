from __future__ import annotations
import asyncio, csv, hashlib, hmac, json, math, os, secrets, shutil, time, uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from paho.mqtt import client as mqtt
from sqlalchemy import create_engine, text

from ai_model import FaultModel

APP_DIR=Path(__file__).resolve().parent
WEB_DIR=APP_DIR/'web'
REPLAY_DIR=APP_DIR/'replay_data'
MODEL_PATH=APP_DIR/'model'/'multi_fault_current_csv_model.joblib'
RECORDING_ROOT=Path(os.getenv('RECORDING_ROOT','/runtime/recordings'))
RECORDING_ROOT.mkdir(parents=True, exist_ok=True)
DB_DSN=os.getenv('DATABASE_DSN','postgresql://nexis:change-me@db:5432/nexis')
ADMIN_USER=os.getenv('ADMIN_USER','admin')
ADMIN_PASSWORD=os.getenv('ADMIN_PASSWORD','')
COOKIE_SECURE=os.getenv('COOKIE_SECURE','false').strip().lower() in {'1','true','yes','on'}
MQTT_HOST=os.getenv('MQTT_HOST','mqtt')
MQTT_PORT=int(os.getenv('MQTT_PORT','1883'))
MQTT_TOPIC=os.getenv('MQTT_TOPIC','nexis/esp32/#')
MQTT_DEVICE_ID=os.getenv('MQTT_DEVICE_ID','rotor_rig_01').strip() or 'rotor_rig_01'
MQTT_DIRECT_PREFIX=f'nexis/esp32/{MQTT_DEVICE_ID}'
COMMAND_TOPIC=f'{MQTT_DIRECT_PREFIX}/control/command'
REMOTE_RPM_MIN=int(os.getenv('REMOTE_RPM_MIN','100'))
REMOTE_RPM_MAX=int(os.getenv('REMOTE_RPM_MAX','1500'))
REMOTE_ARM_SECONDS=int(os.getenv('REMOTE_ARM_SECONDS','60'))
CONTROL_COMMAND_TTL_MS=int(os.getenv('CONTROL_COMMAND_TTL_MS','5000'))
EDGE_ONLINE_TIMEOUT_MS=int(os.getenv('EDGE_ONLINE_TIMEOUT_MS','8000'))
PHYSICAL_AI_MIN_RPM_RATIO=float(os.getenv('PHYSICAL_AI_MIN_RPM_RATIO','0.70'))

engine=create_engine(DB_DSN, pool_pre_ping=True)
model=FaultModel(MODEL_PATH)
app=FastAPI(title='NEXis AI End-of-Line Spin Inspection')
app.mount('/assets', StaticFiles(directory=str(WEB_DIR/'assets')), name='assets')

sessions:dict[str,dict[str,Any]]={}
owner_ws:dict[tuple[str,str],set[WebSocket]]=defaultdict(set)
replay_tasks:dict[str,asyncio.Task]={}
replay_last_file:dict[str,str]={}
latest:dict[str,dict[str,dict[str,Any]]]=defaultdict(dict)
windows:dict[tuple[str,str],deque]=defaultdict(lambda: deque(maxlen=model.window_size))
stream_counters:dict[tuple[str,str],int]=defaultdict(int)
recording_handles:dict[tuple[str,str],dict[str,Any]]={}
loop:asyncio.AbstractEventLoop|None=None
mqtt_client:mqtt.Client|None=None
control_state:dict[str,Any]={
    'server_arm_until_ms':0,
    'device':{},
    'device_last_seen_ms':0,
    'health':{},
    'last_command':{},
    'rpm_min':REMOTE_RPM_MIN,
    'rpm_max':REMOTE_RPM_MAX,
}

FAULTS=('normal','unbalance','misalignment','looseness')


def utcnow(): return datetime.now(timezone.utc)

def init_db():
    ddl='''
    CREATE TABLE IF NOT EXISTS telemetry(
      id BIGSERIAL PRIMARY KEY, owner_id TEXT NOT NULL, source TEXT NOT NULL, sensor_id TEXT,
      ts TIMESTAMPTZ NOT NULL DEFAULT now(), ax_g DOUBLE PRECISION, ay_g DOUBLE PRECISION,
      az_g DOUBLE PRECISION, total_g DOUBLE PRECISION, rpm DOUBLE PRECISION,
      current_a DOUBLE PRECISION, fault_truth TEXT
    );
    CREATE INDEX IF NOT EXISTS telemetry_owner_ts ON telemetry(owner_id,ts DESC);
    CREATE TABLE IF NOT EXISTS predictions(
      id BIGSERIAL PRIMARY KEY, owner_id TEXT NOT NULL, ts TIMESTAMPTZ NOT NULL DEFAULT now(),
      predicted TEXT NOT NULL, confidence DOUBLE PRECISION NOT NULL, probabilities JSONB NOT NULL,
      source TEXT NOT NULL, fault_truth TEXT
    );
    CREATE INDEX IF NOT EXISTS predictions_owner_ts ON predictions(owner_id,ts DESC);
    CREATE TABLE IF NOT EXISTS recordings(
      id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, name TEXT NOT NULL, label TEXT,
      source TEXT NOT NULL, path TEXT NOT NULL, status TEXT NOT NULL,
      sample_count BIGINT NOT NULL DEFAULT 0, started_at TIMESTAMPTZ NOT NULL DEFAULT now(), ended_at TIMESTAMPTZ
    );
    CREATE INDEX IF NOT EXISTS recordings_owner_started ON recordings(owner_id,started_at DESC);
    '''
    with engine.begin() as c:
        for stmt in [x.strip() for x in ddl.split(';') if x.strip()]: c.execute(text(stmt))


def new_session(role:str, username:str, workspace:str)->tuple[str,dict[str,Any]]:
    workspace='demo' if workspace=='demo' else 'physical'
    token=secrets.token_urlsafe(32)
    owner_id='admin' if role=='admin' else f'guest-{uuid.uuid4().hex}'
    data={'role':role,'username':username,'owner_id':owner_id,'workspace':workspace,'created':time.time()}
    sessions[token]=data
    return token,data

def session_from_request(request:Request)->dict[str,Any]:
    token=request.cookies.get('nexis_session','')
    data=sessions.get(token)
    if not data: raise HTTPException(401,'Authentication required.')
    return data

def session_from_ws(ws:WebSocket)->dict[str,Any]|None:
    return sessions.get(ws.cookies.get('nexis_session',''))

def require_workspace(req:Request, workspace:str)->dict[str,Any]:
    s=session_from_request(req)
    if s.get('workspace') != workspace:
        raise HTTPException(403,'This feature is not available in the current workspace.')
    return s

def require_physical_admin(req:Request)->dict[str,Any]:
    s=require_workspace(req,'physical')
    if s.get('role')!='admin':
        raise HTTPException(403,'Only administrators can remotely control the physical station.')
    return s

def set_cookie(resp:Response, token:str):
    resp.set_cookie('nexis_session',token,httponly=True,samesite='lax',secure=COOKIE_SECURE,max_age=12*3600,path='/')

def catalog():
    out={k:[] for k in FAULTS}
    for p in sorted(REPLAY_DIR.glob('*.csv')):
        for f in FAULTS:
            if p.name.startswith(f+'_'):
                out[f].append(p.name); break
    return out

async def broadcast(owner_id:str,payload:dict[str,Any],workspace:str):
    key=(owner_id,workspace)
    dead=[]
    for ws in list(owner_ws.get(key,set())):
        try: await ws.send_json(payload)
        except Exception: dead.append(ws)
    for ws in dead: owner_ws[key].discard(ws)


def clean_num(v:Any,default=0.0)->float:
    try:
        x=float(v)
        return x if math.isfinite(x) else default
    except Exception: return default


def normalize_row(row:dict[str,Any],source:str,sensor_id='ESP32-ADXL345')->dict[str,Any]:
    ax,ay,az=(clean_num(row.get('ax_g')),clean_num(row.get('ay_g')),clean_num(row.get('az_g')))
    total=clean_num(row.get('total_g'), math.sqrt(ax*ax+ay*ay+az*az))
    return {
      'sample_index':int(clean_num(row.get('sample_index'),-1)),'elapsed_ms':clean_num(row.get('elapsed_ms',row.get('time_ms',0)),0),
      'ax_g':ax,'ay_g':ay,'az_g':az,'total_g':total,
      'rpm':clean_num(row.get('rpm'),0),'target_rpm':clean_num(row.get('target_rpm'),0),
      'rpm_error':clean_num(row.get('rpm_error'),0),'pwm_eq':clean_num(row.get('pwm_eq'),0),
      'duty_10bit':clean_num(row.get('duty_10bit'),0),'acs_v':clean_num(row.get('acs_v'),0),
      'current_a':clean_num(row.get('current_a'),0),'control_mode':str(row.get('control_mode','')),
      'state':str(row.get('state','')),'fault_type':str(row.get('fault_type','')),
      'source':source,'sensor_id':sensor_id,'ts':utcnow().isoformat()
    }


def stream_name(source:str)->str:
    return 'physical' if source=='esp32' else ('demo' if source=='replay' else source)

def stream_key(owner_id:str,source:str)->tuple[str,str]:
    return (owner_id,stream_name(source))

def write_recording(owner_id:str,row:dict[str,Any]):
    rec=recording_handles.get((owner_id,stream_name(str(row.get('source') or ''))))
    if not rec: return
    source_filter=str(rec.get('source_filter') or 'all')
    if source_filter!='all' and str(row.get('source') or '')!=source_filter:
        return
    rec['writer'].writerow({k:row.get(k,'') for k in rec['fields']})
    rec['file'].flush(); rec['count']+=1
    if rec['count']%25==0:
        with engine.begin() as c: c.execute(text('UPDATE recordings SET sample_count=:n WHERE id=:id'),{'n':rec['count'],'id':rec['id']})

def physical_ai_eligibility(row:dict[str,Any])->tuple[bool,str,float]:
    """Keep physical telemetry visible/recordable at RPM=0, but only feed valid rotating data to the fault model."""
    if str(row.get('source') or '') != 'esp32':
        return True,'replay',0.0
    rpm=max(0.0,clean_num(row.get('rpm'),0.0))
    target=max(0.0,clean_num(row.get('target_rpm'),0.0))
    mode=str(row.get('control_mode') or '').upper()
    if target <= 0:
        return False,'target_rpm_not_set',float(REMOTE_RPM_MIN)
    threshold=max(float(REMOTE_RPM_MIN), target*PHYSICAL_AI_MIN_RPM_RATIO)
    if rpm < threshold:
        return False,'waiting_for_valid_rpm',threshold
    if mode in ('IDLE',''):
        return False,'control_not_running',threshold
    return True,'eligible',threshold

async def ingest(owner_id:str,row:dict[str,Any],truth:str|None=None):
    source=str(row.get('source') or 'unknown')
    stream=stream_name(source)
    key=stream_key(owner_id,source)

    idx=int(row.get('sample_index',-1))
    if idx < 0:
        idx=stream_counters[key]
        stream_counters[key]+=1
        row['sample_index']=idx
    else:
        stream_counters[key]=max(stream_counters[key],idx+1)

    latest[owner_id][stream]=row
    write_recording(owner_id,row)
    if idx%10==0:
        with engine.begin() as c:
            c.execute(text('''INSERT INTO telemetry(owner_id,source,sensor_id,ax_g,ay_g,az_g,total_g,rpm,current_a,fault_truth)
              VALUES(:o,:s,:sid,:ax,:ay,:az,:tg,:rpm,:cur,:truth)'''),
              {'o':owner_id,'s':row['source'],'sid':row['sensor_id'],'ax':row['ax_g'],'ay':row['ay_g'],'az':row['az_g'],'tg':row['total_g'],'rpm':row['rpm'],'cur':row['current_a'],'truth':truth})

    ai_eligible,ai_status,ai_threshold=physical_ai_eligibility(row)
    pred=None
    if ai_eligible:
        windows[key].append(row)
        if len(windows[key])==model.window_size and idx%model.step_size==0:
            try:
                pred=model.predict(list(windows[key]))
                with engine.begin() as c:
                    c.execute(text('''INSERT INTO predictions(owner_id,predicted,confidence,probabilities,source,fault_truth)
                      VALUES(:o,:p,:c,CAST(:pr AS JSONB),:s,:t)'''),
                      {'o':owner_id,'p':pred['pred_label_name'],'c':pred['top_prob'],'pr':json.dumps(pred['probabilities']),'s':row['source'],'t':truth})
            except Exception as e:
                pred={'error':str(e)}
    else:
        # Never let stopped/ramp-up physical samples contaminate the next valid 256-sample AI window.
        if source=='esp32' and windows[key]:
            windows[key].clear()

    await broadcast(owner_id,{
        'event':'telemetry','stream':stream,'row':row,'prediction':pred,'truth':truth,
        'ai_eligible':ai_eligible,'ai_status':ai_status,'ai_min_rpm':ai_threshold
    },stream)


async def ingest_physical_batch(samples:list[dict[str,Any]]):
    # Physical telemetry is always ingested, even while a recorded demo is running.
    # Physical and demo AI windows are separated by stream key, so samples can never mix.
    for sample in samples:
        if not isinstance(sample,dict):
            continue
        row=normalize_row(sample,'esp32',sensor_id=str(sample.get('sensor_id','ESP32-AWS-DIRECT')))
        await ingest('admin',row,None)

async def replay_worker(owner_id:str,state:str,filename:str,speed:float,looping:bool):
    path=REPLAY_DIR/filename
    try:
        while True:
            df=pd.read_csv(path)
            rows=df.to_dict('records')
            dt=max(0.001,0.01/max(speed,0.05))
            for i,r in enumerate(rows):
                r['sample_index']=i
                row=normalize_row(r,'replay')
                await ingest(owner_id,row,state)
                await asyncio.sleep(dt)
            if not looping: break
        await broadcast(owner_id,{'event':'replay_end','state':state,'file':filename},'demo')
    except asyncio.CancelledError:
        await broadcast(owner_id,{'event':'replay_stop'},'demo')
        raise
    finally:
        replay_tasks.pop(owner_id,None)


def cleanup_guest(owner_id:str):
    task=replay_tasks.pop(owner_id,None)
    if task: task.cancel()
    rec=recording_handles.pop((owner_id,'demo'),None)
    if rec:
        try: rec['file'].close()
        except Exception: pass
    with engine.begin() as c:
        c.execute(text('DELETE FROM predictions WHERE owner_id=:o'),{'o':owner_id})
        c.execute(text('DELETE FROM telemetry WHERE owner_id=:o'),{'o':owner_id})
        c.execute(text('DELETE FROM recordings WHERE owner_id=:o'),{'o':owner_id})
    shutil.rmtree(RECORDING_ROOT/owner_id,ignore_errors=True)
    latest.pop(owner_id,None); replay_last_file.pop(owner_id,None)
    for key in [k for k in list(windows) if k[0]==owner_id]: windows.pop(key,None)
    for key in [k for k in list(stream_counters) if k[0]==owner_id]: stream_counters.pop(key,None)

def now_ms()->int:
    return int(time.time()*1000)


def edge_online()->bool:
    last_seen=int(control_state.get('device_last_seen_ms') or 0)
    return last_seen>0 and (now_ms()-last_seen)<=EDGE_ONLINE_TIMEOUT_MS


def server_armed()->bool:
    return now_ms()<int(control_state.get('server_arm_until_ms') or 0)


def require_admin(req:Request)->dict[str,Any]:
    s=session_from_request(req)
    if s.get('role')!='admin':
        raise HTTPException(403,'Only administrators can remotely control the physical station.')
    return s


def control_snapshot()->dict[str,Any]:
    out=dict(control_state)
    out['device']=dict(control_state.get('device') or {})
    out['health']=dict(control_state.get('health') or {})
    out['last_command']=dict(control_state.get('last_command') or {})
    out['edge_online']=edge_online()
    out['server_armed']=server_armed()
    out['arm_remaining_ms']=max(0,int(control_state.get('server_arm_until_ms') or 0)-now_ms())
    out['command_topic']=COMMAND_TOPIC
    out['device_id']=MQTT_DEVICE_ID
    out['mqtt_topic']=MQTT_TOPIC
    return out


def publish_control(action:str,target_rpm:int=0)->dict[str,Any]:
    if mqtt_client is None or not mqtt_client.is_connected():
        raise HTTPException(503,'The MQTT broker connection is not ready.')
    command_id=uuid.uuid4().hex[:16]
    payload=f'{action.upper()}|{int(target_rpm)}|{command_id}|{now_ms()}|{CONTROL_COMMAND_TTL_MS}'
    info=mqtt_client.publish(COMMAND_TOPIC,payload,qos=1,retain=False)
    cmd={'command_id':command_id,'action':action.lower(),'target_rpm':int(target_rpm),'issued_ms':now_ms(),'mqtt_rc':int(info.rc)}
    control_state['last_command']=cmd
    return cmd


def validate_runtime_config():
    if not ADMIN_PASSWORD.strip() or ADMIN_PASSWORD.startswith('CHANGE_ME'):
        raise RuntimeError('ADMIN_PASSWORD must be configured with a non-placeholder value')


@app.on_event('startup')
async def startup():
    global loop
    validate_runtime_config()
    loop=asyncio.get_running_loop(); init_db(); start_mqtt()

@app.get('/',response_class=HTMLResponse)
def root(): return (WEB_DIR/'index.html').read_text(encoding='utf-8')

@app.get('/api/health')
def health(): return {'ok':True,'model':model.info(),'dataset_counts':{k:len(v) for k,v in catalog().items()}}

@app.post('/api/login')
async def login(req:Request):
    body=await req.json(); u=str(body.get('username','')); p=str(body.get('password','')); workspace=str(body.get('workspace','')).lower()
    if workspace not in ('physical','demo'):
        raise HTTPException(400,'workspace must be either physical or demo.')
    if not (hmac.compare_digest(u,ADMIN_USER) and hmac.compare_digest(p,ADMIN_PASSWORD)):
        raise HTTPException(401,'Invalid username or password.')
    token,data=new_session('admin',u,workspace); r=JSONResponse({'ok':True,**data}); set_cookie(r,token); return r

@app.post('/api/guest')
def guest():
    token,data=new_session('guest','Guest','demo'); r=JSONResponse({'ok':True,**data}); set_cookie(r,token); return r

@app.get('/api/me')
def me(req:Request): return session_from_request(req)

@app.post('/api/logout')
def logout(req:Request):
    token=req.cookies.get('nexis_session',''); data=sessions.pop(token,None)
    if data and data['role']=='guest': cleanup_guest(data['owner_id'])
    r=JSONResponse({'ok':True,'guest_data_deleted':bool(data and data['role']=='guest')}); r.delete_cookie('nexis_session',path='/'); return r

@app.get('/api/replay/catalog')
def replay_catalog(req:Request):
    require_workspace(req,'demo'); c=catalog(); return {'counts':{k:len(v) for k,v in c.items()},'files':c}

@app.post('/api/replay/start')
async def replay_start(req:Request):
    s=require_workspace(req,'demo'); b=await req.json(); state=str(b.get('state','normal'))
    if state not in FAULTS: raise HTTPException(400,'Unsupported condition.')
    files=catalog()[state]
    if not files: raise HTTPException(404,'No replay CSV data is available for this condition.')
    # The operator selects only the operating condition. The server chooses one
    # real recorded CSV from that condition, choosing a different recording when possible.
    last_file=replay_last_file.get(s['owner_id'])
    choices=[f for f in files if f != last_file] or files
    filename=secrets.choice(choices)
    replay_last_file[s['owner_id']]=filename
    active_task=replay_tasks.get(s['owner_id'])
    if active_task:
        active_task.cancel()
        try: await active_task
        except asyncio.CancelledError: pass
    windows[(s['owner_id'],'demo')].clear()
    speed=max(0.1,min(float(b.get('speed',1.0)),5.0))
    looping=bool(b.get('loop',False))
    task=asyncio.create_task(replay_worker(s['owner_id'],state,filename,speed,looping))
    replay_tasks[s['owner_id']]=task
    await broadcast(s['owner_id'],{'event':'scenario_start','state':state,'mode':'Recorded sensor scenario'},'demo')
    return {'ok':True,'state':state,'selected_from':len(files),'mode':'Recorded sensor scenario'}

@app.post('/api/replay/stop')
async def replay_stop(req:Request):
    s=require_workspace(req,'demo'); owner=s['owner_id']; t=replay_tasks.get(owner)
    stopped=bool(t)
    if t:
        t.cancel()
        try: await t
        except asyncio.CancelledError: pass
    replay_tasks.pop(owner,None)
    return {'ok':True,'stopped':stopped}

@app.get('/api/model')
def model_info(req:Request): session_from_request(req); return model.info()

@app.get('/api/latest')
def latest_api(req:Request):
    s=session_from_request(req); return latest.get(s['owner_id'],{}).get(s.get('workspace'),{})

@app.post('/api/recordings/start')
async def recording_start(req:Request):
    s=session_from_request(req); owner=s['owner_id']; workspace=s['workspace']; rec_key=(owner,workspace)
    if rec_key in recording_handles: raise HTTPException(409,'A recording session is already active.')
    b=await req.json(); label=str(b.get('label','unspecified'))[:64]
    source_label=workspace
    source_filter='esp32' if workspace=='physical' else 'replay'
    name=str(b.get('name') or f'NEXis_{source_label}_{label}_{utcnow().strftime("%Y%m%d_%H%M%S")}.csv')
    rid=uuid.uuid4().hex; folder=RECORDING_ROOT/owner; folder.mkdir(parents=True,exist_ok=True); path=folder/f'{rid}_{Path(name).name}'
    fields=['sample_index','elapsed_ms','ax_g','ay_g','az_g','total_g','rpm','target_rpm','rpm_error','pwm_eq','duty_10bit','acs_v','current_a','control_mode','state','fault_type','source','sensor_id','ts']
    fh=path.open('w',newline='',encoding='utf-8'); wr=csv.DictWriter(fh,fieldnames=fields); wr.writeheader()
    recording_handles[rec_key]={'id':rid,'file':fh,'writer':wr,'fields':fields,'count':0,'path':path,'name':name,'label':label,'source':source_label,'source_filter':source_filter,'started_at':utcnow(),'started_monotonic':time.monotonic()}
    with engine.begin() as c: c.execute(text("INSERT INTO recordings(id,owner_id,name,label,source,path,status) VALUES(:id,:o,:n,:l,:s,:p,'recording')"),{'id':rid,'o':owner,'n':name,'l':label,'s':source_label,'p':str(path)})
    return {'ok':True,'id':rid,'name':name,'label':label,'source':source_label,'started_at':recording_handles[rec_key]['started_at'].isoformat(),'sample_count':0}


@app.post('/api/recordings/stop')
def recording_stop(req:Request):
    s=session_from_request(req); owner=s['owner_id']; rec=recording_handles.pop((owner,s['workspace']),None)
    if not rec: raise HTTPException(404,'No recording session is currently active.')
    rec['file'].close()
    with engine.begin() as c: c.execute(text("UPDATE recordings SET status='completed',sample_count=:n,ended_at=now() WHERE id=:id"),{'n':rec['count'],'id':rec['id']})
    return {'ok':True,'id':rec['id'],'sample_count':rec['count'],'duration_s':max(0.0,time.monotonic()-rec.get('started_monotonic',time.monotonic()))}

@app.get('/api/recordings/status')
def recording_status(req:Request):
    s=session_from_request(req); owner=s['owner_id']; rec=recording_handles.get((owner,s['workspace']))
    if not rec:
        return {'active':False,'sample_count':0}
    return {
      'active':True,'id':rec['id'],'name':rec.get('name',''),'label':rec.get('label',''),
      'source':rec.get('source','replay_or_esp32'),'sample_count':rec.get('count',0),
      'started_at':rec.get('started_at',utcnow()).isoformat(),
      'elapsed_s':max(0.0,time.monotonic()-rec.get('started_monotonic',time.monotonic()))
    }

@app.get('/api/recordings')
def recordings(req:Request):
    s=session_from_request(req)
    with engine.begin() as c: rows=c.execute(text('SELECT id,name,label,source,status,sample_count,started_at,ended_at FROM recordings WHERE owner_id=:o AND source=:src ORDER BY started_at DESC'),{'o':s['owner_id'],'src':s['workspace']}).mappings().all()
    return [dict(r) for r in rows]

@app.get('/api/recordings/{rid}/download')
def recording_download(rid:str,req:Request):
    s=session_from_request(req)
    with engine.begin() as c: r=c.execute(text('SELECT name,path FROM recordings WHERE id=:id AND owner_id=:o AND source=:src'),{'id':rid,'o':s['owner_id'],'src':s['workspace']}).mappings().first()
    if not r or not Path(r['path']).exists(): raise HTTPException(404,'File not found.')
    return FileResponse(r['path'],filename=r['name'],media_type='text/csv')

@app.delete('/api/recordings/{rid}')
def recording_delete(rid:str,req:Request):
    s=session_from_request(req)
    with engine.begin() as c:
        r=c.execute(text('SELECT path FROM recordings WHERE id=:id AND owner_id=:o AND source=:src'),{'id':rid,'o':s['owner_id'],'src':s['workspace']}).mappings().first()
        if not r: raise HTTPException(404,'Recording not found.')
        c.execute(text('DELETE FROM recordings WHERE id=:id AND owner_id=:o AND source=:src'),{'id':rid,'o':s['owner_id'],'src':s['workspace']})
    Path(r['path']).unlink(missing_ok=True); return {'ok':True}

@app.get('/api/history')
def history(req:Request):
    s=session_from_request(req)
    with engine.begin() as c:
        source='esp32' if s['workspace']=='physical' else 'replay'
        p=c.execute(text('SELECT predicted,confidence,probabilities,source,fault_truth,ts FROM predictions WHERE owner_id=:o AND source=:src ORDER BY ts DESC LIMIT 30'),{'o':s['owner_id'],'src':source}).mappings().all()
    return [dict(x) for x in p]

@app.get('/api/control/status')
def control_status(req:Request):
    require_workspace(req,'physical')
    return control_snapshot()


@app.post('/api/control/arm')
async def control_arm(req:Request):
    require_physical_admin(req)
    body=await req.json()
    arm=bool(body.get('arm',True))
    if not arm:
        control_state['server_arm_until_ms']=0
        return {'ok':True,**control_snapshot()}
    if not edge_online():
        raise HTTPException(409,'Physical ESP32 station is offline')
    dev=control_state.get('device') or {}
    if dev.get('remote_enabled') is not True:
        raise HTTPException(409,'ESP32 remote command reception is disabled. Check the device status.')
    duration=max(10,min(int(body.get('duration_s',REMOTE_ARM_SECONDS)),300))
    control_state['server_arm_until_ms']=now_ms()+duration*1000
    return {'ok':True,**control_snapshot()}


@app.post('/api/control/start')
async def control_start(req:Request):
    require_physical_admin(req)
    body=await req.json()
    if not edge_online(): raise HTTPException(409,'Physical ESP32 station is offline')
    dev=control_state.get('device') or {}
    if dev.get('remote_enabled') is not True: raise HTTPException(409,'ESP32 remote command reception is disabled.')
    try: rpm=int(float(body.get('rpm')))
    except Exception: raise HTTPException(400,'rpm is required')
    if rpm<REMOTE_RPM_MIN or rpm>REMOTE_RPM_MAX:
        raise HTTPException(400,f'RPM must be between {REMOTE_RPM_MIN} and {REMOTE_RPM_MAX}.')
    # Keep the server-side safety gate active without exposing an extra operator step.
    control_state['server_arm_until_ms']=now_ms()+REMOTE_ARM_SECONDS*1000
    cmd=publish_control('SET_RPM',rpm)
    await broadcast('admin',{'event':'control_command','control':control_snapshot()},'physical')
    return {'ok':True,'command':cmd,**control_snapshot()}


@app.post('/api/control/target')
async def control_target(req:Request):
    require_physical_admin(req)
    body=await req.json()
    if not edge_online(): raise HTTPException(409,'Physical ESP32 station is offline')
    if not server_armed(): raise HTTPException(409,'Remote control must be armed from the dashboard.')
    dev=control_state.get('device') or {}
    if dev.get('remote_enabled') is not True: raise HTTPException(409,'ESP32 local REMOTE ARM is OFF')
    try: rpm=int(float(body.get('rpm')))
    except Exception: raise HTTPException(400,'rpm is required')
    if rpm<REMOTE_RPM_MIN or rpm>REMOTE_RPM_MAX:
        raise HTTPException(400,f'RPM must be between {REMOTE_RPM_MIN} and {REMOTE_RPM_MAX}.')
    cmd=publish_control('SET_RPM',rpm)
    await broadcast('admin',{'event':'control_command','control':control_snapshot()},'physical')
    return {'ok':True,'command':cmd,**control_snapshot()}


@app.post('/api/control/stop')
async def control_stop(req:Request):
    require_physical_admin(req)
    control_state['server_arm_until_ms']=0
    cmd=publish_control('STOP',0)
    await broadcast('admin',{'event':'control_command','control':control_snapshot()},'physical')
    return {'ok':True,'command':cmd,**control_snapshot()}


@app.websocket('/ws')
async def ws_endpoint(ws:WebSocket):
    s=session_from_ws(ws)
    if not s: await ws.close(code=4401); return
    await ws.accept(); owner=s['owner_id']; workspace=s['workspace']; key=(owner,workspace); owner_ws[key].add(ws)
    try:
        await ws.send_json({'event':'hello','owner_id':owner,'role':s['role'],'workspace':workspace,'model':model.info()})
        while True: await ws.receive_text()
    except WebSocketDisconnect: pass
    finally: owner_ws[key].discard(ws)


def start_mqtt():
    global mqtt_client
    def submit(coro):
        if loop:
            asyncio.run_coroutine_threadsafe(coro,loop)

    def on_connect(client,userdata,flags,reason_code,properties=None):
        try: rc=int(reason_code)
        except Exception: rc=0 if str(reason_code).lower() in ('success','0') else -1
        if rc==0:
            client.subscribe(MQTT_TOPIC,qos=0)
            print(f'[MQTT] subscribed={MQTT_TOPIC} command={COMMAND_TOPIC}')

    def on_message(client,userdata,msg):
        try:
            topic=str(msg.topic)
            if topic == COMMAND_TOPIC:
                return
            payload=json.loads(msg.payload.decode('utf-8'))
            now=now_ms()
            if topic.endswith('/telemetry/batch'):
                samples=payload.get('samples') if isinstance(payload,dict) else []
                if isinstance(samples,list):
                    control_state['device_last_seen_ms']=now
                    submit(ingest_physical_batch(samples))
                return
            if topic.endswith('/telemetry/raw'):
                if isinstance(payload,dict):
                    control_state['device_last_seen_ms']=now
                    submit(ingest_physical_batch([payload]))
                return
            if topic.endswith('/control/status'):
                if isinstance(payload,dict):
                    control_state['device']=payload
                    control_state['device_last_seen_ms']=now
                    submit(broadcast('admin',{'event':'control_status','control':control_snapshot()},'physical'))
                return
            if topic.endswith('/health'):
                if isinstance(payload,dict):
                    control_state['health']=payload
                    control_state['device_last_seen_ms']=now
                    submit(broadcast('admin',{'event':'control_health','control':control_snapshot()},'physical'))
                return
            # Physical ESP32 telemetry topic supported by the device integration.
            if isinstance(payload,dict):
                owner=str(payload.pop('owner_id','admin'))
                if owner=='admin':
                    submit(ingest_physical_batch([payload]))
                else:
                    row=normalize_row(payload,'esp32',sensor_id=str(payload.get('sensor_id','ESP32-ADXL345')))
                    submit(ingest(owner,row,None))
        except Exception as e:
            print('[MQTT] message error:',e)

    c=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id=f'nexis-v43-{uuid.uuid4().hex[:8]}')
    c.on_connect=on_connect
    c.on_message=on_message
    c.reconnect_delay_set(min_delay=1,max_delay=10)
    mqtt_client=c
    try:
        c.connect_async(MQTT_HOST,MQTT_PORT,60)
        c.loop_start()
    except Exception as e:
        print('[MQTT] connect error:',e)


if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='0.0.0.0',port=8000)
