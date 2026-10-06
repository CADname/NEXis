from __future__ import annotations
import asyncio, csv, hashlib, hmac, json, math, os, secrets, threading, time, uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
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

VISION_ROOT=Path(os.getenv('VISION_ROOT','/runtime/vision'))
VISION_ROOT.mkdir(parents=True, exist_ok=True)
VISION_CONFIG_PATH=VISION_ROOT/'config.json'
VISION_STATUS_PATH=VISION_ROOT/'status.json'
VISION_FRAME_PATH=VISION_ROOT/'latest.jpg'
VISION_TOKEN_PATH=VISION_ROOT/'edge_token.txt'
VISION_RESET_PATH=VISION_ROOT/'reset.json'
VISION_CAMERA_PATH=VISION_ROOT/'camera_selection.json'
DEMO_VISION_CONFIG_PATH=VISION_ROOT/'demo_config.json'
VISION_MAX_FRAME_BYTES=int(os.getenv('VISION_MAX_FRAME_BYTES','3500000'))
VISION_FRAME_MAX_AGE_SECONDS=float(os.getenv('VISION_FRAME_MAX_AGE_SECONDS','10'))
VISION_CONFIG_LOCK=threading.RLock()
VISION_EDGE_PROTOCOL=3

engine=create_engine(DB_DSN, pool_pre_ping=True)
model=FaultModel(MODEL_PATH)
app=FastAPI(title='NEXis Machine Inspection Platform')
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
VISION_ROI_KEYS=('hall_led','rotor','adxl345','acs712','hall_sensor')


def utcnow(): return datetime.now(timezone.utc)

def atomic_json_write(path:Path, payload:dict[str,Any]):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(f'.{path.name}.{os.getpid()}.{threading.get_ident()}.{secrets.token_hex(4)}.tmp')
    try:
        tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(tmp,path)
    finally:
        try: tmp.unlink(missing_ok=True)
        except Exception: pass

def atomic_bytes_write(path:Path, payload:bytes):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(f'.{path.name}.{os.getpid()}.{threading.get_ident()}.{secrets.token_hex(4)}.tmp')
    try:
        tmp.write_bytes(payload)
        os.replace(tmp,path)
    finally:
        try: tmp.unlink(missing_ok=True)
        except Exception: pass

def unlink_if_exists(path:Path):
    try: path.unlink()
    except FileNotFoundError: pass

def read_json_file(path:Path, default:dict[str,Any]|None=None)->dict[str,Any]:
    try:
        if path.exists():
            data=json.loads(path.read_text(encoding='utf-8'))
            return data if isinstance(data,dict) else (default or {})
    except Exception as e:
        print(f'[VISION] read error {path}: {e}')
    return dict(default or {})

def vision_edge_token()->str:
    env=os.getenv('VISION_EDGE_TOKEN','').strip()
    if env: return env
    try:
        return VISION_TOKEN_PATH.read_text(encoding='utf-8').strip()
    except Exception:
        return ''

def require_vision_edge(req:Request):
    expected=vision_edge_token()
    supplied=req.headers.get('x-vision-token','').strip()
    if not expected or not supplied or not hmac.compare_digest(expected,supplied):
        raise HTTPException(401,'Invalid vision edge token.')

def norm_point(value:Any)->list[float]:
    if not isinstance(value,(list,tuple)) or len(value)!=2: raise HTTPException(400,'Invalid polygon point.')
    try:
        x=float(value[0]); y=float(value[1])
    except Exception:
        raise HTTPException(400,'Invalid polygon point.')
    if not (math.isfinite(x) and math.isfinite(y) and 0.0<=x<=1.0 and 0.0<=y<=1.0):
        raise HTTPException(400,'Vision coordinates must be finite and normalized to 0..1.')
    return [x,y]

def polygon_area(points:list[list[float]])->float:
    if len(points)<3: return 0.0
    return abs(sum(points[i][0]*points[(i+1)%len(points)][1]-points[(i+1)%len(points)][0]*points[i][1] for i in range(len(points))))*0.5

def _segments_intersect(a:list[float],b:list[float],c:list[float],d:list[float])->bool:
    eps=1e-10
    def orient(p,q,r): return (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    def on_segment(p,q,r):
        return min(p[0],r[0])-eps<=q[0]<=max(p[0],r[0])+eps and min(p[1],r[1])-eps<=q[1]<=max(p[1],r[1])+eps
    o1,o2,o3,o4=orient(a,b,c),orient(a,b,d),orient(c,d,a),orient(c,d,b)
    if ((o1>eps and o2<-eps) or (o1<-eps and o2>eps)) and ((o3>eps and o4<-eps) or (o3<-eps and o4>eps)):
        return True
    if abs(o1)<=eps and on_segment(a,c,b): return True
    if abs(o2)<=eps and on_segment(a,d,b): return True
    if abs(o3)<=eps and on_segment(c,a,d): return True
    if abs(o4)<=eps and on_segment(c,b,d): return True
    return False

def polygon_self_intersects(points:list[list[float]])->bool:
    n=len(points)
    if n<4: return False
    for i in range(n):
        a,b=points[i],points[(i+1)%n]
        for j in range(i+1,n):
            if i==j or (i+1)%n==j or (j+1)%n==i:
                continue
            c,d=points[j],points[(j+1)%n]
            if _segments_intersect(a,b,c,d):
                return True
    return False

def safe_int(value:Any, default:int, lo:int, hi:int)->int:
    try: n=int(value)
    except Exception: n=default
    return max(lo,min(hi,n))

def norm_roi(value:Any)->dict[str,float]:
    if not isinstance(value,dict): raise HTTPException(400,'Invalid ROI.')
    try:
        out={k:float(value.get(k,0.0)) for k in ('x','y','w','h')}
    except Exception:
        raise HTTPException(400,'Invalid ROI.')
    if not all(math.isfinite(v) for v in out.values()): raise HTTPException(400,'ROI coordinates must be finite.')
    if out['w']<=0.002 or out['h']<=0.002: raise HTTPException(400,'ROI width/height is too small.')
    if out['x']<0 or out['y']<0 or out['x']+out['w']>1.0001 or out['y']+out['h']>1.0001:
        raise HTTPException(400,'ROI must fit inside the camera frame.')
    return out


def vision_camera_snapshot()->dict[str,Any]:
    data=read_json_file(VISION_CAMERA_PATH,{'revision':0,'requested_index':None})
    idx=data.get('requested_index',None)
    try:
        idx=None if idx is None else int(idx)
    except Exception:
        idx=None
    if idx is not None and not (0<=idx<=15): idx=None
    return {
      'revision':safe_int(data.get('revision',0) or 0,0,0,10**18),
      'requested_index':idx,
      'updated_at':str(data.get('updated_at','') or '')
    }

def vision_config_snapshot()->dict[str,Any]:
    cfg=read_json_file(VISION_CONFIG_PATH)
    reset=read_json_file(VISION_RESET_PATH,{'reset_revision':0})
    if not cfg:
        return {'configured':False,'reset_revision':safe_int(reset.get('reset_revision',0),0,0,10**18)}
    return {**cfg,'configured':True,'reset_revision':safe_int(reset.get('reset_revision',0),0,0,10**18)}

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
    owner_id='physical-station' if workspace=='physical' else f'demo-{uuid.uuid4().hex}'
    data={'role':role,'username':username,'owner_id':owner_id,'workspace':workspace,'created':time.time()}
    sessions[token]=data
    return token,data

def session_from_request(request:Request)->dict[str,Any]:
    token=request.cookies.get('nexis_session','')
    data=sessions.get(token)
    if not data: raise HTTPException(401,'Workspace session required.')
    return data

def session_from_ws(ws:WebSocket)->dict[str,Any]|None:
    return sessions.get(ws.cookies.get('nexis_session',''))

def require_workspace(req:Request, workspace:str)->dict[str,Any]:
    s=session_from_request(req)
    if s.get('workspace') != workspace:
        raise HTTPException(403,'This feature is not available in the current workspace.')
    return s

def require_physical_operator(req:Request)->dict[str,Any]:
    s=require_workspace(req,'physical')
    if s.get('role')!='operator':
        raise HTTPException(403,'Physical control is available only in the Physical Station workspace.')
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
        if source=='esp32' and windows[key]:
            windows[key].clear()

    await broadcast(owner_id,{
        'event':'telemetry','stream':stream,'row':row,'prediction':pred,'truth':truth,
        'ai_eligible':ai_eligible,'ai_status':ai_status,'ai_min_rpm':ai_threshold
    },stream)


async def ingest_physical_batch(samples:list[dict[str,Any]]):
    for sample in samples:
        if not isinstance(sample,dict):
            continue
        row=normalize_row(sample,'esp32',sensor_id=str(sample.get('sensor_id','ESP32-AWS-DIRECT')))
        await ingest('physical-station',row,None)

async def replay_worker(owner_id:str,state:str,speed:float,continuous:bool=True):
    last_filename=replay_last_file.get(owner_id)
    try:
        while True:
            files=catalog().get(state,[])
            if not files:
                await broadcast(owner_id,{'event':'replay_end','state':state,'reason':'no_files'},'demo')
                return
            choices=[f for f in files if f != last_filename] or files
            filename=secrets.choice(choices)
            last_filename=filename
            replay_last_file[owner_id]=filename
            path=REPLAY_DIR/filename
            df=pd.read_csv(path)
            rows=df.to_dict('records')
            dt=max(0.001,0.01/max(speed,0.05))
            await broadcast(owner_id,{'event':'replay_file','state':state,'file':filename,'selected_from':len(files)},'demo')
            for i,r in enumerate(rows):
                r['sample_index']=i
                row=normalize_row(r,'replay')
                await ingest(owner_id,row,state)
                await asyncio.sleep(dt)
            if not continuous:
                await broadcast(owner_id,{'event':'replay_end','state':state,'file':filename},'demo')
                return
    except asyncio.CancelledError:
        await broadcast(owner_id,{'event':'replay_stop'},'demo')
        raise
    finally:
        replay_tasks.pop(owner_id,None)



def now_ms()->int:
    return int(time.time()*1000)


def edge_online()->bool:
    last_seen=int(control_state.get('device_last_seen_ms') or 0)
    return last_seen>0 and (now_ms()-last_seen)<=EDGE_ONLINE_TIMEOUT_MS


def server_armed()->bool:
    return now_ms()<int(control_state.get('server_arm_until_ms') or 0)


def require_operator(req:Request)->dict[str,Any]:
    s=session_from_request(req)
    if s.get('role')!='operator':
        raise HTTPException(403,'Physical control is available only in the Physical Station workspace.')
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
    return


@app.on_event('startup')
async def startup():
    global loop
    validate_runtime_config()
    loop=asyncio.get_running_loop(); init_db(); start_mqtt()

@app.get('/',response_class=HTMLResponse)
def root(): return (WEB_DIR/'index.html').read_text(encoding='utf-8')

@app.get('/api/health')
def health(): return {'ok':True,'model':model.info(),'dataset_counts':{k:len(v) for k,v in catalog().items()}}

@app.get('/api/vision/status')
def vision_status(req:Request):
    require_workspace(req,'physical')
    status=read_json_file(VISION_STATUS_PATH)
    cfg=read_json_file(VISION_CONFIG_PATH)
    now=time.time()
    try:
        ts=float(status.get('server_received_ts',0.0)) if status else 0.0
        age=max(0.0,now-ts) if status and math.isfinite(ts) else None
    except Exception:
        age=None
    try:
        frame_mtime=VISION_FRAME_PATH.stat().st_mtime
    except FileNotFoundError:
        frame_mtime=0.0
    except OSError as e:
        print(f'[VISION] frame stat error: {e}')
        frame_mtime=0.0
    frame_age=max(0.0,now-frame_mtime) if frame_mtime>0 and math.isfinite(frame_mtime) else None
    return {
      'configured':bool(cfg),
      'config_revision':safe_int(cfg.get('revision',0) or 0,0,0,10**18) if cfg else 0,
      'baseline_revision':safe_int(cfg.get('baseline_revision',0) or 0,0,0,10**18) if cfg else 0,
      'baseline_required':bool(cfg.get('baseline_required',True)) if cfg else True,
      'camera_selection':vision_camera_snapshot(),
      'status':status,'frame_available':frame_mtime>0.0,'frame_mtime':frame_mtime,'frame_age_s':frame_age,'edge_age_s':age,
      'preview_mode':'cloud-jpeg'
    }

@app.get('/api/vision/config')
def vision_get_config(req:Request):
    require_physical_operator(req)
    return vision_config_snapshot()

@app.get('/api/vision/camera')
def vision_camera_get(req:Request):
    require_physical_operator(req)
    return {'ok':True,**vision_camera_snapshot()}

@app.post('/api/vision/camera/select')
async def vision_camera_select(req:Request):
    require_physical_operator(req)
    try:
        body=await req.json()
    except Exception:
        raise HTTPException(400,'Camera selection must be valid JSON.')
    if not isinstance(body,dict): raise HTTPException(400,'Camera selection must be a JSON object.')
    try:
        requested=int(body.get('camera_index'))
    except Exception:
        raise HTTPException(400,'camera_index must be an integer.')
    if requested<0 or requested>15: raise HTTPException(400,'camera_index must be between 0 and 15.')
    status=read_json_file(VISION_STATUS_PATH)
    try:
        age=max(0.0,time.time()-float(status.get('server_received_ts',0.0))) if status else 9999.0
    except Exception:
        age=9999.0
    if age>5.0: raise HTTPException(409,'Start the Windows Vision Camera Connector first.')
    available=[]
    for item in status.get('available_cameras',[]) if isinstance(status.get('available_cameras'),list) else []:
        try: available.append(int(item.get('index') if isinstance(item,dict) else item))
        except Exception: pass
    if requested not in available:
        raise HTTPException(409,'That camera is not currently available. Restart the Camera Connector if a webcam was just plugged in.')
    previous=vision_camera_snapshot()
    if previous.get('requested_index')==requested:
        return {'ok':True,'unchanged':True,**previous}
    payload={'revision':max(now_ms(),safe_int(previous.get('revision',0),0,0,10**18)+1),'requested_index':requested,'updated_at':utcnow().isoformat()}
    atomic_json_write(VISION_CAMERA_PATH,payload)
    return {'ok':True,'unchanged':False,**payload}

@app.post('/api/vision/camera/off')
def vision_camera_off(req:Request):
    require_physical_operator(req)
    previous=vision_camera_snapshot()
    payload={'revision':max(now_ms(),safe_int(previous.get('revision',0),0,0,10**18)+1),'requested_index':None,'updated_at':utcnow().isoformat()}
    atomic_json_write(VISION_CAMERA_PATH,payload)
    return {'ok':True,**payload}

@app.post('/api/vision/config')
async def vision_save_config(req:Request):
    require_physical_operator(req)
    try:
        body=await req.json()
    except Exception:
        raise HTTPException(400,'Vision setup must be valid JSON.')
    if not isinstance(body,dict): raise HTTPException(400,'Vision setup must be a JSON object.')
    raw_polygon=body.get('hazard_polygon',[])
    if not isinstance(raw_polygon,list): raise HTTPException(400,'Invalid hazard zone polygon.')
    polygon=[norm_point(p) for p in raw_polygon]
    if len(polygon)<3: raise HTTPException(400,'Select at least 3 points for the hazard zone.')
    if len(polygon)>32: raise HTTPException(400,'Hazard zone is too complex; use 32 points or fewer.')
    if polygon_self_intersects(polygon):
        raise HTTPException(400,'Hazard zone edges cross each other. Redraw the polygon in perimeter order.')
    if len({(round(p[0],6),round(p[1],6)) for p in polygon})<3 or polygon_area(polygon)<1e-6:
        raise HTTPException(400,'Hazard zone polygon has no usable area.')
    rois_in=body.get('rois',{}) if isinstance(body.get('rois',{}),dict) else {}
    rois:dict[str,dict[str,float]]={}
    for key in VISION_ROI_KEYS:
        value=rois_in.get(key)
        if value:
            rois[key]=norm_roi(value)
    if 'hall_led' not in rois: raise HTTPException(400,'Select the Hall LED ROI.')
    if 'rotor' not in rois: raise HTTPException(400,'Select the rotor ROI.')
    if 'adxl345' not in rois: raise HTTPException(400,'Select the ADXL345 mount ROI.')
    warning_margin=safe_int(body.get('warning_margin_px',90),90,0,500)
    setup_w=safe_int(body.get('frame_width',0) or 0,0,0,10000)
    setup_h=safe_int(body.get('frame_height',0) or 0,0,0,10000)
    setup_camera=safe_int(body.get('camera_index',-1),-1,-1,64)
    if setup_w<16 or setup_h<16:
        raise HTTPException(409,'A fresh webcam frame is required before saving the Vision setup.')
    if setup_camera<0:
        raise HTTPException(409,'The active webcam index is not available yet. Wait for the Edge Agent camera status and try again.')
    edge_status=read_json_file(VISION_STATUS_PATH)
    try:
        edge_age=max(0.0,time.time()-float(edge_status.get('server_received_ts',0.0))) if edge_status else 9999.0
    except Exception:
        edge_age=9999.0
    if edge_age>5.0 or edge_status.get('camera_ok') is not True:
        raise HTTPException(409,'A live webcam edge agent is required before saving the Vision setup.')
    if safe_int(edge_status.get('vision_protocol',0),0,0,1000)<VISION_EDGE_PROTOCOL:
        raise HTTPException(409,'Restart the Windows Vision Edge before saving this setup.')
    edge_camera=safe_int(edge_status.get('camera_index',-1),-1,-1,64)
    edge_w=safe_int(edge_status.get('frame_width',0),0,0,10000)
    edge_h=safe_int(edge_status.get('frame_height',0),0,0,10000)
    if edge_camera!=setup_camera or edge_w!=setup_w or edge_h!=setup_h:
        raise HTTPException(409,'The webcam changed while this setup was being edited. Refresh the live frame and save again.')
    with VISION_CONFIG_LOCK:
        previous=read_json_file(VISION_CONFIG_PATH)
        prev_w=safe_int(previous.get('setup_frame_width',0) or 0,0,0,10000) if previous else 0
        prev_h=safe_int(previous.get('setup_frame_height',0) or 0,0,0,10000) if previous else 0
        prev_camera=safe_int(previous.get('setup_camera_index',-1),-1,-1,64) if previous else -1
        schema_ok=bool(previous) and safe_int(previous.get('schema_revision',0),0,0,100)>=3
        geometry_same=schema_ok and previous.get('hazard_polygon')==polygon and previous.get('rois')==rois and safe_int(previous.get('warning_margin_px',90),90,0,500)==warning_margin
        frame_ok=prev_w==setup_w and prev_h==setup_h and prev_w>=16 and prev_h>=16
        camera_ok=prev_camera>=0 and prev_camera==setup_camera
        same_setup=geometry_same and frame_ok and camera_ok
        if same_setup:
            return {'ok':True,'unchanged':True,**previous}
        rev=max(now_ms(),safe_int(previous.get('revision',0),0,0,10**18)+1)
        payload={
          'schema_revision':3,'revision':rev,'baseline_revision':0,
          'hazard_polygon':polygon,'warning_margin_px':warning_margin,
          'rois':rois,
          'setup_frame_width':setup_w,
          'setup_frame_height':setup_h,
          'setup_camera_index':setup_camera,
          'baseline_required':True,'updated_at':utcnow().isoformat()
        }
        atomic_json_write(VISION_CONFIG_PATH,payload)
    return {'ok':True,'unchanged':False,**payload}

@app.post('/api/vision/baseline')
def vision_capture_baseline(req:Request):
    require_physical_operator(req)
    status=read_json_file(VISION_STATUS_PATH)
    try: age=max(0.0,time.time()-float(status.get('server_received_ts',0.0))) if status else 9999.0
    except Exception: age=9999.0
    if age>5.0 or not bool(status.get('camera_ok')):
        raise HTTPException(409,'The webcam edge agent must be online before capturing a sensor baseline.')
    if safe_int(status.get('vision_protocol',0),0,0,1000)<VISION_EDGE_PROTOCOL:
        raise HTTPException(409,'Restart the Windows Vision Edge before capturing a sensor baseline.')
    if status.get('frame_config_compatible') is not True:
        raise HTTPException(409,'The Vision Edge has not confirmed that the active camera and frame geometry match the saved setup. Save the setup again on the active camera or restart the Vision Edge.')
    with VISION_CONFIG_LOCK:
        cfg=read_json_file(VISION_CONFIG_PATH)
        if not cfg: raise HTTPException(409,'Save the vision setup first.')
        try: edge_cfg_rev=int(status.get('config_revision',0) or 0)
        except Exception: edge_cfg_rev=0
        if edge_cfg_rev != safe_int(cfg.get('revision',0) or 0,0,0,10**18):
            raise HTTPException(409,'The webcam edge agent is still syncing the saved setup. Wait a moment and try again.')
        cfg['baseline_revision']=max(now_ms(),safe_int(cfg.get('baseline_revision',0),0,0,10**18)+1)
        cfg['baseline_required']=True
        cfg['updated_at']=utcnow().isoformat()
        atomic_json_write(VISION_CONFIG_PATH,cfg)
    return {'ok':True,'baseline_revision':cfg['baseline_revision'],'baseline_required':True}

@app.delete('/api/vision/config')
def vision_reset_config(req:Request):
    require_physical_operator(req)
    with VISION_CONFIG_LOCK:
        unlink_if_exists(VISION_CONFIG_PATH)
        previous_reset=read_json_file(VISION_RESET_PATH,{'reset_revision':0})
        reset_rev=max(now_ms(),safe_int(previous_reset.get('reset_revision',0) or 0,0,0,10**18)+1)
        reset={'reset_revision':reset_rev,'updated_at':utcnow().isoformat()}
        atomic_json_write(VISION_RESET_PATH,reset)
    unlink_if_exists(VISION_STATUS_PATH)
    unlink_if_exists(VISION_FRAME_PATH)
    return {'ok':True,**reset}

@app.get('/api/vision/frame.jpg')
def vision_frame(req:Request):
    require_workspace(req,'physical')
    try:
        st=VISION_FRAME_PATH.stat()
        age=max(0.0,time.time()-st.st_mtime)
        if age>VISION_FRAME_MAX_AGE_SECONDS:
            raise HTTPException(404,'Latest camera frame is stale.')
        raw=VISION_FRAME_PATH.read_bytes()
    except FileNotFoundError:
        raise HTTPException(404,'No camera frame has been received yet.')
    except HTTPException:
        raise
    except OSError as e:
        print(f'[VISION] frame read error: {e}')
        raise HTTPException(503,'Latest camera frame is temporarily unavailable.')
    if len(raw)<100 or not raw.startswith(b'\xff\xd8') or not raw.rstrip().endswith(b'\xff\xd9'):
        raise HTTPException(503,'Latest camera frame is invalid.')
    return Response(content=raw,media_type='image/jpeg',headers={'Cache-Control':'no-store, max-age=0'})

@app.get('/api/vision/edge-info')
def vision_edge_info(req:Request):
    require_physical_operator(req)
    token=vision_edge_token()
    return {'server_url':str(req.base_url).rstrip('/'),'token':token,'ready':bool(token),'required_protocol':VISION_EDGE_PROTOCOL,'preview_mode':'cloud-jpeg'}

@app.get('/api/vision/edge/config')
def vision_edge_config(req:Request):
    require_vision_edge(req)
    return {**vision_config_snapshot(),'camera_selection':vision_camera_snapshot(),'required_protocol':VISION_EDGE_PROTOCOL}

@app.post('/api/vision/edge/status')
async def vision_edge_status(req:Request):
    require_vision_edge(req)
    try:
        body=await req.json()
    except Exception:
        raise HTTPException(400,'Invalid vision status JSON.')
    if not isinstance(body,dict): raise HTTPException(400,'Invalid vision status payload.')
    body=dict(body)
    body['server_received_at']=utcnow().isoformat()
    body['server_received_ts']=time.time()
    atomic_json_write(VISION_STATUS_PATH,body)
    with VISION_CONFIG_LOCK:
        cfg=read_json_file(VISION_CONFIG_PATH)
        requested=safe_int(cfg.get('baseline_revision',0) or 0,0,0,10**18) if cfg else 0
        try: confirmed=int(body.get('baseline_revision',0) or 0)
        except Exception: confirmed=0
        try: confirmed_cfg=int(body.get('config_revision',0) or 0)
        except Exception: confirmed_cfg=0
        protocol_ok=safe_int(body.get('vision_protocol',0),0,0,1000)>=VISION_EDGE_PROTOCOL
        if cfg and protocol_ok and requested>0 and confirmed_cfg==safe_int(cfg.get('revision',0) or 0,0,0,10**18) and body.get('frame_config_compatible') is True and bool(body.get('baseline_ready')) and confirmed==requested and bool(cfg.get('baseline_required',True)):
            cfg['baseline_required']=False
            cfg['baseline_confirmed_at']=utcnow().isoformat()
            atomic_json_write(VISION_CONFIG_PATH,cfg)
    await broadcast('physical-station',{'event':'vision_status','vision':body},'physical')
    return {'ok':True}

@app.post('/api/vision/edge/frame')
async def vision_edge_frame(req:Request, frame:UploadFile=File(...)):
    require_vision_edge(req)
    raw=await frame.read(VISION_MAX_FRAME_BYTES+1)
    if len(raw)>VISION_MAX_FRAME_BYTES: raise HTTPException(413,'Vision frame is too large.')
    if len(raw)<100 or not raw.startswith(b'\xff\xd8') or not raw.rstrip().endswith(b'\xff\xd9'):
        raise HTTPException(400,'Vision frame must be a JPEG image.')
    atomic_bytes_write(VISION_FRAME_PATH,raw)
    return {'ok':True,'bytes':len(raw)}


def demo_vision_config_snapshot()->dict[str,Any]:
    cfg=read_json_file(DEMO_VISION_CONFIG_PATH)
    if not cfg:
        return {'configured':False,'baseline_revision':0,'baseline_required':True}
    return {**cfg,'configured':True}

@app.get('/api/demo/vision/config')
def demo_vision_get_config(req:Request):
    require_workspace(req,'demo')
    return demo_vision_config_snapshot()

@app.post('/api/demo/vision/config')
async def demo_vision_save_config(req:Request):
    require_workspace(req,'demo')
    try:
        body=await req.json()
    except Exception:
        raise HTTPException(400,'Demo Vision setup must be valid JSON.')
    if not isinstance(body,dict):
        raise HTTPException(400,'Demo Vision setup must be a JSON object.')
    raw_polygon=body.get('hazard_polygon',[])
    if not isinstance(raw_polygon,list): raise HTTPException(400,'Invalid hazard zone polygon.')
    polygon=[norm_point(p) for p in raw_polygon]
    if len(polygon)<3: raise HTTPException(400,'Select at least 3 points for the hazard zone.')
    if len(polygon)>32: raise HTTPException(400,'Hazard zone is too complex; use 32 points or fewer.')
    if polygon_self_intersects(polygon): raise HTTPException(400,'Hazard zone edges cross each other. Redraw the polygon in perimeter order.')
    if len({(round(p[0],6),round(p[1],6)) for p in polygon})<3 or polygon_area(polygon)<1e-6:
        raise HTTPException(400,'Hazard zone polygon has no usable area.')
    rois_in=body.get('rois',{}) if isinstance(body.get('rois',{}),dict) else {}
    rois:dict[str,dict[str,float]]={}
    for key in VISION_ROI_KEYS:
        value=rois_in.get(key)
        if value: rois[key]=norm_roi(value)
    if 'hall_led' not in rois: raise HTTPException(400,'Select the Hall LED ROI.')
    if 'rotor' not in rois: raise HTTPException(400,'Select the rotor ROI.')
    if 'adxl345' not in rois: raise HTTPException(400,'Select the ADXL345 mount ROI.')
    warning_margin=safe_int(body.get('warning_margin_px',90),90,0,500)
    with VISION_CONFIG_LOCK:
        previous=read_json_file(DEMO_VISION_CONFIG_PATH)
        geometry_same=bool(previous) and previous.get('hazard_polygon')==polygon and previous.get('rois')==rois and safe_int(previous.get('warning_margin_px',90),90,0,500)==warning_margin
        if geometry_same:
            revision=safe_int(previous.get('revision',0),0,0,10**18) or now_ms()
            baseline_revision=safe_int(previous.get('baseline_revision',0),0,0,10**18)
            baseline_required=bool(previous.get('baseline_required',True))
        else:
            revision=max(now_ms(),safe_int(previous.get('revision',0),0,0,10**18)+1 if previous else now_ms())
            baseline_revision=0
            baseline_required=True
        payload={'schema_revision':1,'revision':revision,'hazard_polygon':polygon,'warning_margin_px':warning_margin,'rois':rois,'baseline_revision':baseline_revision,'baseline_required':baseline_required,'updated_at':utcnow().isoformat()}
        atomic_json_write(DEMO_VISION_CONFIG_PATH,payload)
    return {'ok':True,'unchanged':geometry_same,**payload}

@app.post('/api/demo/vision/baseline')
def demo_vision_capture_baseline(req:Request):
    require_workspace(req,'demo')
    with VISION_CONFIG_LOCK:
        cfg=read_json_file(DEMO_VISION_CONFIG_PATH)
        if not cfg: raise HTTPException(409,'Save the demo Vision setup first.')
        baseline=max(now_ms(),safe_int(cfg.get('baseline_revision',0),0,0,10**18)+1)
        cfg={**cfg,'baseline_revision':baseline,'baseline_required':False,'baseline_updated_at':utcnow().isoformat()}
        atomic_json_write(DEMO_VISION_CONFIG_PATH,cfg)
    return {'ok':True,'baseline_revision':baseline,'baseline_required':False}

@app.delete('/api/demo/vision/config')
def demo_vision_reset_config(req:Request):
    require_workspace(req,'demo')
    with VISION_CONFIG_LOCK:
        try: DEMO_VISION_CONFIG_PATH.unlink()
        except FileNotFoundError: pass
    return {'ok':True,'configured':False}

def direct_workspace_response(req:Request, workspace:str)->JSONResponse:
    workspace=str(workspace or '').strip().lower()
    if workspace not in ('physical','demo'):
        raise HTTPException(400,'workspace must be either physical or demo.')
    old=req.cookies.get('nexis_session','')
    if old:
        sessions.pop(old,None)
    role='operator' if workspace=='physical' else 'demo'
    token,data=new_session(role,'Physical Station' if workspace=='physical' else 'Recorded Demo',workspace)
    r=JSONResponse({'ok':True,**data,'direct_access':True})
    set_cookie(r,token)
    return r

@app.post('/api/enter')
async def enter_workspace(req:Request):
    """Direct workspace selector used by the kiosk UI (no username/password form)."""
    try:
        body=await req.json()
    except Exception:
        raise HTTPException(400,'Workspace selection must be valid JSON.')
    if not isinstance(body,dict):
        raise HTTPException(400,'Workspace selection must be a JSON object.')
    return direct_workspace_response(req,body.get('workspace',''))

@app.post('/api/enter/{workspace}')
def enter_workspace_path(workspace:str, req:Request):
    """Convenience endpoint used by the one-click Windows camera connector."""
    return direct_workspace_response(req,workspace)



@app.get('/api/me')
def me(req:Request): return session_from_request(req)

@app.post('/api/workspace/leave')
def leave_workspace(req:Request):
    token=req.cookies.get('nexis_session','')
    sessions.pop(token,None)
    r=JSONResponse({'ok':True})
    r.delete_cookie('nexis_session',path='/')
    return r

@app.get('/api/replay/catalog')
def replay_catalog(req:Request):
    require_workspace(req,'demo'); c=catalog(); return {'counts':{k:len(v) for k,v in c.items()},'files':c}

@app.post('/api/replay/start')
async def replay_start(req:Request):
    s=require_workspace(req,'demo'); b=await req.json(); state=str(b.get('state','normal'))
    if state not in FAULTS: raise HTTPException(400,'Unsupported condition.')
    files=catalog()[state]
    if not files: raise HTTPException(404,'No replay CSV data is available for this condition.')
    old=replay_tasks.get(s['owner_id'])
    if old:
        old.cancel()
        try: await old
        except asyncio.CancelledError: pass
    windows[(s['owner_id'],'demo')].clear()
    speed=max(0.1,min(float(b.get('speed',1.0)),5.0))
    continuous=bool(b.get('continuous',True))
    task=asyncio.create_task(replay_worker(s['owner_id'],state,speed,continuous))
    replay_tasks[s['owner_id']]=task
    await broadcast(s['owner_id'],{'event':'scenario_start','state':state,'mode':'Recorded sensor scenario','continuous':continuous},'demo')
    return {'ok':True,'state':state,'selected_from':len(files),'continuous':continuous,'mode':'Recorded sensor scenario'}

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
    require_physical_operator(req)
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
    require_physical_operator(req)
    body=await req.json()
    if not edge_online(): raise HTTPException(409,'Physical ESP32 station is offline')
    dev=control_state.get('device') or {}
    if dev.get('remote_enabled') is not True: raise HTTPException(409,'ESP32 remote command reception is disabled.')
    try: rpm=int(float(body.get('rpm')))
    except Exception: raise HTTPException(400,'rpm is required')
    if rpm<REMOTE_RPM_MIN or rpm>REMOTE_RPM_MAX:
        raise HTTPException(400,f'RPM must be between {REMOTE_RPM_MIN} and {REMOTE_RPM_MAX}.')
    control_state['server_arm_until_ms']=now_ms()+REMOTE_ARM_SECONDS*1000
    cmd=publish_control('SET_RPM',rpm)
    await broadcast('physical-station',{'event':'control_command','control':control_snapshot()},'physical')
    return {'ok':True,'command':cmd,**control_snapshot()}


@app.post('/api/control/target')
async def control_target(req:Request):
    require_physical_operator(req)
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
    await broadcast('physical-station',{'event':'control_command','control':control_snapshot()},'physical')
    return {'ok':True,'command':cmd,**control_snapshot()}


@app.post('/api/control/stop')
async def control_stop(req:Request):
    require_physical_operator(req)
    control_state['server_arm_until_ms']=0
    cmd=publish_control('STOP',0)
    await broadcast('physical-station',{'event':'control_command','control':control_snapshot()},'physical')
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
                    submit(broadcast('physical-station',{'event':'control_status','control':control_snapshot()},'physical'))
                return
            if topic.endswith('/health'):
                if isinstance(payload,dict):
                    control_state['health']=payload
                    control_state['device_last_seen_ms']=now
                    submit(broadcast('physical-station',{'event':'control_health','control':control_snapshot()},'physical'))
                return
            if isinstance(payload,dict):
                owner=str(payload.pop('owner_id','physical-station'))
                if owner=='physical-station':
                    submit(ingest_physical_batch([payload]))
                else:
                    row=normalize_row(payload,'esp32',sensor_id=str(payload.get('sensor_id','ESP32-ADXL345')))
                    submit(ingest(owner,row,None))
        except Exception as e:
            print('[MQTT] message error:',e)

    c=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id=f'nexis-cloud-{uuid.uuid4().hex[:8]}')
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
