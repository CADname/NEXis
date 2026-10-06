(()=>{
'use strict';
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const FAULT_LABELS={normal:'Normal',unbalance:'Unbalance',misalignment:'Misalignment',looseness:'Fastener Looseness'};
const SCENARIO={
  normal:{title:'Normal Operation',desc:'Continuously replay randomly selected recorded CSV files from the normal condition until Stop is pressed.'},
  unbalance:{title:'Unbalance',desc:'Continuously replay randomly selected recorded CSV files from the unbalance condition until Stop is pressed.'},
  misalignment:{title:'Misalignment',desc:'Continuously replay randomly selected recorded CSV files from the misalignment condition until Stop is pressed.'},
  looseness:{title:'Fastener Looseness',desc:'Continuously replay randomly selected recorded CSV files from the looseness condition until Stop is pressed.'}
};
const PAGE_META={
  physical:['Live Inspection','Monitor the physical ESP32 station, sensors, motor, and AI diagnosis in one view.'],
  demo:['Recorded Demo','Replay recorded CSV scenarios in real time with AI diagnosis and the digital twin.'],
  ai:['AI Diagnosis','Review the current workspace diagnosis and recent AI history.'],
  vision:['Vision Safety','Physical Station uses a live camera; Recorded Demo uses a fixed digital twin to configure hazard zones and sensor positions.'],
  recordings:['Data Recording','Capture raw telemetry from the current workspace to CSV.'],
  twin:['Digital Twin','View the equipment twin synchronized to live or replayed RPM.'],
  logs:['Event Log','Review operational events from the current workspace.']
};
const blankBuffer=()=>({x:[],y:[],z:[],total:[],current:[],rpm:[]});
const blankStream=()=>({monitoring:false,active:false,sampleCounter:0,lastTelemetryAt:null,lastRow:null,lastPred:null,buffer:blankBuffer(),fft:{freq:[],amp:[],dominant:0},recentRows:[],chartPending:false});
const streams={physical:blankStream(),demo:blankStream()};
streams.demo.scenario=null;
let currentUser=null,workspace=null,ws=null,heartbeat=null,controlTimer=null,recActive=false,recStartedAt=null,recElapsedFrozen=0,historyTimer=0;
const logs=[];
const twins={physical:[],demo:[]};

async function api(path,opt={}){
  const r=await fetch(path,{credentials:'same-origin',headers:{'Content-Type':'application/json',...(opt.headers||{})},...opt});
  if(r.status===401){showWorkspaceSelector();throw new Error('Workspace selection required.');}
  if(!r.ok){let t='';try{t=(await r.json()).detail}catch{}throw new Error(t||`HTTP ${r.status}`)}
  const ct=r.headers.get('content-type')||'';return ct.includes('json')?r.json():r;
}
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=(v,d=2)=>{const n=Number(v);return Number.isFinite(n)?n.toFixed(d):'—'};
function setText(id,v){const e=$('#'+id);if(e)e.textContent=v}
function setTone(id,tone){const e=$('#'+id);if(!e)return;e.classList.remove('tone-ok','tone-warn','tone-danger','tone-info');if(tone)e.classList.add('tone-'+tone)}
function setTagTone(id,tone){const e=$('#'+id);if(!e)return;e.classList.remove('ok','warning','danger','neutral');e.classList.add(tone||'neutral')}
function showWorkspaceSelector(){workspace=null;currentUser=null;document.body.classList.remove('workspace-physical','workspace-demo');$('#workspaceSelector').classList.remove('hidden');$('#app').classList.add('hidden')}
function applyWorkspace(kind){workspace=kind==='demo'?'demo':'physical';document.body.classList.toggle('workspace-physical',workspace==='physical');document.body.classList.toggle('workspace-demo',workspace==='demo');$$('[data-workspace-only]').forEach(el=>el.classList.toggle('workspace-hidden',el.dataset.workspaceOnly!==workspace));const src=$('#recordSource');if(src)src.value=workspace;setText('recordSourceBadge',workspace==='physical'?'PHYSICAL STATION':'RECORDED DEMO');setText('captureSourceLabel',workspace==='physical'?'Physical LIVE':'LIVE Demo');setText('sourceChip',workspace==='physical'?'PHYSICAL DEVICE LIVE':'RECORDED LIVE DEMO');const first=workspace==='physical'?'physical':'demo';setPage(first);}
function addLog(type,msg){logs.unshift({t:new Date(),type,msg});if(logs.length>200)logs.length=200;renderLogs()}
function renderLogs(){const el=$('#logList');if(!el)return;el.innerHTML=logs.length?logs.map(x=>`<div class="log-row"><time>${x.t.toLocaleTimeString()}</time><b>${esc(x.type)}</b><span>${esc(x.msg)}</span></div>`).join(''):'<div class="log-row"><time>—</time><b>SYSTEM</b><span>No events to display.</span></div>'}

function ensureTwins(){
  if(workspace==='physical'&&!twins.physical.length){['#physicalTwin','#physicalMainTwin'].forEach(sel=>{const t=window.createNEXisTwin(sel);if(t)twins.physical.push(t)})}
  if(workspace==='demo'&&!twins.demo.length){['#demoTwin','#demoMainTwin'].forEach(sel=>{const t=window.createNEXisTwin(sel);if(t)twins.demo.push(t)});const fixed=window.createNEXisTwin('#demoVisionTwin',{locked:true});if(fixed)twins.demo.push(fixed)}
}
function twinEach(kind,fn){for(const t of twins[kind])try{fn(t)}catch{}}
function showApp(user){
  currentUser=user;applyWorkspace(user.workspace);$('#workspaceSelector').classList.add('hidden');$('#app').classList.remove('hidden');
  setText('accountName',workspace==='physical'?'Physical Station':'Recorded Demo');setText('accountRole','DIRECT ACCESS');setText('avatar',workspace==='physical'?'P':'D');
  const requestedPage=new URLSearchParams(location.search).get('page');
  if(requestedPage&&PAGE_META[requestedPage]&&!(requestedPage==='physical'&&workspace!=='physical')&&!(requestedPage==='demo'&&workspace!=='demo'))setPage(requestedPage);
  if(location.search)history.replaceState({},'',location.pathname);
  ensureTwins();connectWS();renderAllProbabilities();if(workspace==='physical'){setPhysicalMonitoring(false);loadControlStatus();visionLoadAll()}else{setDemoUI(null,false);loadCatalog();demoVisionLoadConfig()}loadRecordings();loadRecordingStatus();loadHistory();renderCaptureTable();addLog('SYSTEM',`Direct access · ${workspace==='physical'?'PHYSICAL STATION':'RECORDED DEMO'} connected`);
}

function connectWS(){
  if(ws)ws.close();if(heartbeat)clearInterval(heartbeat);
  const proto=location.protocol==='https:'?'wss':'ws';ws=new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen=()=>{setText('sideStatus','Cloud connected');addLog('NETWORK','WebSocket connected');heartbeat=setInterval(()=>{if(ws?.readyState===1)ws.send('ping')},20000)};
  ws.onclose=()=>setText('sideStatus','Disconnected');
  ws.onmessage=e=>{let m;try{m=JSON.parse(e.data)}catch{return}
    if(m.event==='telemetry')routeTelemetry(m);
    else if(m.event==='scenario_start')setDemoUI(m.state,true);
    else if(m.event==='replay_stop')setDemoUI(streams.demo.scenario,false);
    else if(m.event==='replay_end'){setDemoUI(m.state||streams.demo.scenario,false,true);addLog('DEMO',`${FAULT_LABELS[m.state]||m.state||'scenario'} replay completed`)}
    else if(m.event==='control_status'||m.event==='control_health'||m.event==='control_command')renderControlStatus(m.control||{});
    else if(m.event==='vision_status'){const vv=m.vision||{};renderVisionStatus(vv);if(vv.camera_ok&&$('.page.active')?.id==='vision')visionRefreshFrame();else if(!vv.camera_ok&&$('.page.active')?.id==='vision')visionHideStaleFrame('Waiting for camera frame.');}
  };
}

function setPage(name){
  if((name==='physical'&&workspace!=='physical')||(name==='demo'&&workspace!=='demo'))return;
  $$('.nav-item').forEach(b=>b.classList.toggle('active',b.dataset.page===name));$$('.page').forEach(p=>p.classList.toggle('active',p.id===name));
  const meta=PAGE_META[name]||[name,''];setText('pageTitle',meta[0]);setText('pageSubtitle',meta[1]);
  if(name==='ai')loadHistory();if(name==='recordings'){loadRecordings();loadRecordingStatus();renderCaptureTable()}
  if(name==='vision'){if(workspace==='physical')visionLoadAll();else{demoVisionLoadConfig();setTimeout(()=>{twinEach('demo',t=>t.resize?.());demoVisionDrawOverlay()},80)}}
  if(name==='twin')setTimeout(()=>twinEach(workspace,t=>t.resize?.()),80);
  if(name==='physical'||name==='demo'){requestAnimationFrame(()=>scheduleCharts(name,true));setTimeout(()=>scheduleCharts(name,true),80)}
}
$$('.nav-item').forEach(b=>b.addEventListener('click',()=>setPage(b.dataset.page)));$$('[data-page-jump]').forEach(b=>b.addEventListener('click',()=>setPage(b.dataset.pageJump)));

async function enterWorkspace(kind){
  if(kind!=='physical'&&kind!=='demo')return;
  const btn=kind==='physical'?$('#physicalEnterBtn'):$('#demoEnterBtn');
  if(btn)btn.disabled=true;
  try{const u=await api('/api/enter',{method:'POST',body:JSON.stringify({workspace:kind})});showApp(u)}
  catch(err){alert(err.message);showWorkspaceSelector()}
  finally{if(btn)btn.disabled=false}
}
$('#physicalEnterBtn')?.addEventListener('click',()=>enterWorkspace('physical'));
$('#demoEnterBtn')?.addEventListener('click',()=>enterWorkspace('demo'));
$('#switchWorkspaceBtn').addEventListener('click',async()=>{try{await api('/api/workspace/leave',{method:'POST'})}catch{}if(ws)ws.close();if(heartbeat)clearInterval(heartbeat);currentUser=null;showWorkspaceSelector()});

function clearStream(kind){
  const s=streams[kind];s.buffer=blankBuffer();s.fft={freq:[],amp:[],dominant:0};s.sampleCounter=0;s.lastTelemetryAt=null;s.lastPred=null;s.recentRows.length=0;
  if(kind==='physical'){renderProb('pProbabilities',null);setText('pDiagnosis','Waiting for operating conditions');setText('pDiagnosisText','Sensors remain live at 0 RPM; only AI inference is paused.');}
  else{renderProb('dProbabilities',null);setText('dDiagnosis','Waiting for analysis');setText('dDiagnosisText','Diagnosis starts after 256 samples are collected.');}
  scheduleCharts(kind,true);renderCaptureTable();
}
function setPhysicalMonitoring(active){
  const s=streams.physical;s.monitoring=!!active;setText('pMonitorState',active?'RUNNING':'STOPPED');setTone('pMonitorState',active?'ok':'warn');
  $('#physicalMonitorStart').disabled=active;$('#physicalMonitorStop').disabled=!active;
  if(active){clearStream('physical');addLog('PHYSICAL','Physical monitoring started · sensor telemetry remains visible from 0 RPM')}else addLog('PHYSICAL','Physical screen monitoring stopped · MQTT reception and motor control remain active');
}
$('#physicalMonitorStart').addEventListener('click',()=>setPhysicalMonitoring(true));$('#physicalMonitorStop').addEventListener('click',()=>setPhysicalMonitoring(false));

async function startDemo(state){
  try{clearStream('demo');streams.demo.monitoring=true;const r=await api('/api/replay/start',{method:'POST',body:JSON.stringify({state,speed:1,continuous:true})});setDemoUI(state,true);addLog('DEMO',`${FAULT_LABELS[state]} started · ${r.selected_from} recorded CSV files · random continuous replay until Stop`)}
  catch(e){streams.demo.monitoring=false;setDemoUI(state,false);addLog('ERROR',e.message);alert(e.message)}
}
async function stopDemo(){try{await api('/api/replay/stop',{method:'POST'})}catch{}setDemoUI(streams.demo.scenario,false);addLog('DEMO','Recorded demo stopped')}
$$('[data-demo-scenario]').forEach(b=>b.addEventListener('click',()=>startDemo(b.dataset.demoScenario)));$('#demoStop').addEventListener('click',stopDemo);
function setDemoUI(state,active,complete=false){
  const s=streams.demo;if(state)s.scenario=state;s.active=!!active;s.monitoring=!!active;
  const info=SCENARIO[s.scenario]||{title:'Waiting for scenario',desc:'Select a condition.'};setText('demoScenarioTitle',active?`${info.title} · replaying`:(complete?`${info.title} · complete`:'Waiting for scenario'));setText('demoScenarioDesc',active?info.desc:'Select a condition. Recorded CSV files in that class will be chosen randomly and replayed continuously until Stop is pressed.');setText('dMonitorState',active?'RUNNING':(complete?'COMPLETE':'READY'));setTone('dMonitorState',active?'ok':(complete?'info':'warn'));setText('dScenario',s.scenario?FAULT_LABELS[s.scenario]:'—');setText('dMetricScenario',s.scenario?FAULT_LABELS[s.scenario]:'—');
  setText('dTwinState',active?`${FAULT_LABELS[s.scenario]} · Replaying`:(complete?`${FAULT_LABELS[s.scenario]} · Complete`:'Waiting for scenario'));setText('twinDemoState',active?`${FAULT_LABELS[s.scenario]} · Replaying`:'Waiting for scenario');
  $('#demoStop').disabled=!active;$$('[data-demo-scenario]').forEach(b=>b.classList.toggle('running',active&&b.dataset.demoScenario===s.scenario));
  twinEach('demo',t=>t.setScenario(s.scenario||'normal',active));demoVisionRenderRuntime();
  const tchip=$('#twinDemoChip');if(tchip){tchip.textContent=active?'RUNNING':'READY';tchip.classList.toggle('online',active);tchip.classList.toggle('offline',!active)}
}

function push(s,name,v,max=256){s.buffer[name].push(Number(v)||0);if(s.buffer[name].length>max)s.buffer[name].shift()}
function stats(a){if(!a.length)return{rms:0,ptp:0};const mn=Math.min(...a),mx=Math.max(...a);return{rms:Math.sqrt(a.reduce((z,v)=>z+v*v,0)/a.length),ptp:mx-mn}}
function computeFFT(a,fs=100){const n=Math.min(256,a.length);if(n<32)return{freq:[],amp:[],dominant:0};const x=a.slice(-n),mean=x.reduce((z,v)=>z+v,0)/n,freq=[],amp=[];let best=0,bestF=0;for(let k=1;k<=Math.floor(n/2);k++){let re=0,im=0;for(let j=0;j<n;j++){const w=.5-.5*Math.cos(2*Math.PI*j/(n-1)),v=(x[j]-mean)*w,ang=2*Math.PI*k*j/n;re+=v*Math.cos(ang);im-=v*Math.sin(ang)}const mag=Math.hypot(re,im)/n*2,f=k*fs/n;freq.push(f);amp.push(mag);if(mag>best){best=mag;bestF=f}}return{freq,amp,dominant:bestF}}
function routeTelemetry(m){const kind=m.stream||(m.row?.source==='esp32'?'physical':'demo');if(!streams[kind]||kind!==workspace)return;renderTelemetry(kind,m)}
function renderTelemetry(kind,m){
  const s=streams[kind],r=m.row||{};s.lastRow=r;s.lastTelemetryAt=new Date();
  if(kind==='physical'){
    twinEach('physical',t=>t.setTelemetry(r));setText('pTwinState',Number(r.rpm)>5?`Physical ${num(r.rpm,0)} RPM`:'Physical Station Stopped');setText('twinPhysicalState',Number(r.rpm)>5?`Live ${num(r.rpm,0)} RPM`:'Physical Station Stopped');
  }else{
    twinEach('demo',t=>t.setTelemetry(r));demoVisionRenderRuntime();setText('dTwinState',`${FAULT_LABELS[s.scenario]||'Demo'} · ${num(r.rpm,0)} RPM`);setText('twinDemoState',`${FAULT_LABELS[s.scenario]||'Demo'} · ${num(r.rpm,0)} RPM`);
  }
  handlePrediction(kind,m);
  s.recentRows.unshift(r);if(s.recentRows.length>14)s.recentRows.length=14;
  if($('.page.active')?.id==='recordings')renderCaptureTable();
  if(!s.monitoring && kind==='physical')return;
  s.sampleCounter++;push(s,'x',r.ax_g);push(s,'y',r.ay_g);push(s,'z',r.az_g);push(s,'total',r.total_g);push(s,'current',r.current_a);push(s,'rpm',r.rpm);if(s.sampleCounter%16===0)s.fft=computeFFT(s.buffer.total,100);
  renderMetrics(kind,r);scheduleCharts(kind);
}
function renderMetrics(kind,r){
  const s=streams[kind],st=stats(s.buffer.total),time=s.lastTelemetryAt?s.lastTelemetryAt.toLocaleTimeString():'—';
  if(kind==='physical'){
    setText('pSamples',String(s.sampleCounter));setText('pLastUpdate',time);setText('pTotal',`${num(r.total_g,4)} g`);setText('pRms',st.rms.toFixed(4));setText('pPtp',`${st.ptp.toFixed(4)} g`);setText('pCurrent',num(r.current_a,3));setText('pRpm',num(r.rpm,0));setText('pTargetRpm',`${num(r.target_rpm,0)} rpm`);setText('pRpmError',`${num(r.rpm_error,1)} rpm`);setText('pPwm',num(r.pwm_eq,2));setText('pDuty',`${num(r.duty_10bit,0)} / 1023`);setText('pAcs',`${num(r.acs_v,3)} V`);setText('pMode',r.control_mode||'—');setText('pDominantFreq',`${s.fft.dominant.toFixed(2)} Hz`);
  }else{
    setText('dSamples',String(s.sampleCounter));setText('dLastUpdate',time);setText('dTotal',`${num(r.total_g,4)} g`);setText('dRms',st.rms.toFixed(4));setText('dPtp',`${st.ptp.toFixed(4)} g`);setText('dCurrent',num(r.current_a,3));setText('dRpm',num(r.rpm,0));setText('dDominantFreq',`${s.fft.dominant.toFixed(2)} Hz`);
  }
}
function handlePrediction(kind,m){
  const s=streams[kind];
  if(m.prediction&&!m.prediction.error){s.lastPred=m.prediction;const label=m.prediction.pred_label_name,conf=Number(m.prediction.top_prob||0);twinEach(kind,t=>t.setDiagnosis(label));
    if(kind==='physical'){renderProb('pProbabilities',m.prediction.probabilities);setText('pDiagnosis',FAULT_LABELS[label]||label);setTone('pDiagnosis',label==='normal'?'ok':'danger');setText('pDiagnosisText',`Confidence ${(conf*100).toFixed(1)}%`);setText('pAiState','ACTIVE');setTagTone('pAiState',label==='normal'?'ok':'danger');setText('pAiGate','ACTIVE');setTone('pAiGate','ok');setText('aiPhysicalDiagnosis',FAULT_LABELS[label]||label);setText('aiPhysicalConfidence',`${(conf*100).toFixed(1)}%`);setText('aiPhysicalText','Diagnosis from the live physical sensor window');}
    else{renderProb('dProbabilities',m.prediction.probabilities);setText('dDiagnosis',FAULT_LABELS[label]||label);setTone('dDiagnosis',label==='normal'?'ok':'danger');setText('dDiagnosisText',`Confidence ${(conf*100).toFixed(1)}%`);setText('dAiState','ACTIVE');setTagTone('dAiState',label==='normal'?'ok':'danger');setText('aiDemoDiagnosis',FAULT_LABELS[label]||label);setText('aiDemoConfidence',`${(conf*100).toFixed(1)}%`);setText('aiDemoText',`${FAULT_LABELS[streams.demo.scenario]||'Demo'} replay window-based diagnosis`);}
    const now=Date.now();if(now-historyTimer>2500){historyTimer=now;loadHistory()}
  }else if(kind==='physical'&&m.ai_eligible===false){s.lastPred=null;renderProb('pProbabilities',null);setText('pDiagnosis','Waiting for operating conditions');setTone('pDiagnosis','warn');setText('pDiagnosisText',`Sensors are live. AI starts above 70% of target RPM (minimum ${num(m.ai_min_rpm,0)} RPM).`);setText('pAiState','WAIT');setTagTone('pAiState','warning');setText('pAiGate','WAIT');setTone('pAiGate','warn');setText('aiPhysicalDiagnosis','Waiting for operating conditions');setText('aiPhysicalConfidence','—');setText('aiPhysicalText','Stopped and low-speed data are excluded from the Physical AI window');}
}
function renderProb(id,probs){const el=$('#'+id);if(!el)return;const p=probs||{normal:0,unbalance:0,misalignment:0,looseness:0};el.innerHTML=['normal','unbalance','misalignment','looseness'].map(k=>{const v=Math.max(0,Math.min(1,Number(p[k])||0));return `<div class="prob-row"><span>${FAULT_LABELS[k]}</span><div class="prob-bar"><i style="width:${(v*100).toFixed(1)}%"></i></div><b>${(v*100).toFixed(1)}%</b></div>`}).join('')}
function renderAllProbabilities(){renderProb('pProbabilities',null);renderProb('dProbabilities',null)}

function scheduleCharts(kind,force=false){const s=streams[kind];if(s.chartPending&&!force)return;s.chartPending=true;requestAnimationFrame(()=>{s.chartPending=false;const pre=kind==='physical'?'p':'d',wave=$('#'+pre+'WaveChart'),fft=$('#'+pre+'FftChart');if(!wave||!fft||wave.clientWidth<8||wave.clientHeight<8||fft.clientWidth<8||fft.clientHeight<8)return;drawWave(wave,[s.buffer.x,s.buffer.y,s.buffer.z],kind==='physical'?'Start physical monitoring to display the signal.':'Start the recorded demo to display the signal.');drawFFT(fft,s.fft)})}
function canvasPrep(c){if(!c)return null;const w=c.clientWidth,h=c.clientHeight;if(!Number.isFinite(w)||!Number.isFinite(h)||w<8||h<8)return null;const d=Math.min(window.devicePixelRatio||1,2),pw=Math.max(1,Math.floor(w*d)),ph=Math.max(1,Math.floor(h*d));if(c.width!==pw||c.height!==ph){c.width=pw;c.height=ph}const x=c.getContext('2d');if(!x)return null;x.setTransform(d,0,0,d,0,0);return{x,w,h}}
function drawGrid(x,w,h){x.strokeStyle='rgba(100,145,180,.14)';x.lineWidth=1;for(let i=1;i<5;i++){x.beginPath();x.moveTo(0,h*i/5);x.lineTo(w,h*i/5);x.stroke()}for(let i=1;i<8;i++){x.beginPath();x.moveTo(w*i/8,0);x.lineTo(w*i/8,h);x.stroke()}}
function drawWave(c,sets,emptyText){const p=canvasPrep(c);if(!p)return;const {x,w,h}=p;x.clearRect(0,0,w,h);drawGrid(x,w,h);const all=sets.flat();if(!all.length){x.fillStyle='#66829a';x.font='11px sans-serif';x.fillText(emptyText,14,24);return}let mn=Math.min(...all),mx=Math.max(...all);if(mx-mn<.001){mx+=.5;mn-=.5}const pad=(mx-mn)*.12;mn-=pad;mx+=pad;const colors=['#4a96ff','#21d69a','#ff9b52'];sets.forEach((a,j)=>{if(a.length<2)return;x.strokeStyle=colors[j];x.lineWidth=1.3;x.beginPath();a.forEach((v,i)=>{const px=i/Math.max(1,a.length-1)*w,py=h-(v-mn)/(mx-mn)*h;i?x.lineTo(px,py):x.moveTo(px,py)});x.stroke()})}
function drawFFT(c,data){const p=canvasPrep(c);if(!p)return;const {x,w,h}=p;x.clearRect(0,0,w,h);drawGrid(x,w,h);if(!data.amp.length){x.fillStyle='#66829a';x.font='11px sans-serif';x.fillText('Waiting for FFT data',14,24);return}const max=Math.max(...data.amp,1e-6);x.strokeStyle='#37c9ff';x.fillStyle='rgba(55,201,255,.18)';x.lineWidth=1.5;x.beginPath();data.amp.forEach((v,i)=>{const px=i/Math.max(1,data.amp.length-1)*w,py=h-v/max*(h-16);i?x.lineTo(px,py):x.moveTo(px,py)});x.stroke();x.lineTo(w,h);x.lineTo(0,h);x.closePath();x.fill()}

function renderControlStatus(c){
  if(workspace!=='physical')return;const dev=c.device||{},online=!!c.edge_online,local=dev.remote_enabled===true,row=streams.physical.lastRow||{};
  setText('ctrlEdge',online?'ONLINE':'OFFLINE');setText('pLinkState',online?'ONLINE':'OFFLINE');setTone('pLinkState',online?'ok':'danger');setText('ctrlMode',dev.control_mode||row.control_mode||'IDLE');setText('ctrlActual',`${num(dev.rpm??row.rpm,0)} RPM`);setText('ctrlTarget',`${num(dev.target_rpm??row.target_rpm,0)} RPM`);setText('ctrlRpmError',`Error ${num(row.rpm_error,1)} RPM`);setText('ctrlPwm',num(row.pwm_eq,2));setText('ctrlDuty',`Duty ${num(row.duty_10bit,0)} / 1023`);setText('ctrlCurrent',`${num(row.current_a,3)} A`);setText('ctrlAcs',`ACS ${num(row.acs_v,3)} V`);setText('ctrlLastSeen',online?'Heartbeat healthy':'Waiting for heartbeat');
  const chip=$('#ctrlEdgeChip');if(chip){chip.textContent=online?'ESP32 ONLINE':'ESP32 OFFLINE';chip.classList.toggle('online',online);chip.classList.toggle('offline',!online)}
  const operator=currentUser?.role==='operator';$('#ctrlStartBtn').disabled=!operator||!online||!local;$('#ctrlStopBtn').disabled=!operator;
  if(!operator)setText('ctrlMessage','Physical control is available only in the Physical Station workspace.');else if(!online)setText('ctrlMessage','Start/stop becomes available when the ESP32 connects to AWS.');else if(!local)setText('ctrlMessage','Check ESP32 remote command reception.');else setText('ctrlMessage','Enter a target RPM and press Start Motor. Stop can be sent at any time.');
}
async function loadControlStatus(){if(!currentUser||workspace!=='physical')return;try{renderControlStatus(await api('/api/control/status'))}catch(e){setText('ctrlMessage',e.message)}}
$('#ctrlStartBtn').addEventListener('click',async()=>{try{const rpm=Math.round(Number($('#ctrlRpmInput').value));const r=await api('/api/control/start',{method:'POST',body:JSON.stringify({rpm})});renderControlStatus(r);addLog('CONTROL',`Motor start · target ${rpm} RPM`)}catch(e){setText('ctrlMessage',e.message);alert(e.message)}});
$('#ctrlStopBtn').addEventListener('click',async()=>{try{const r=await api('/api/control/stop',{method:'POST',body:'{}'});renderControlStatus(r);addLog('CONTROL','Motor stop')}catch(e){setText('ctrlMessage',e.message);alert(e.message)}});

async function loadCatalog(){try{const c=await api('/api/replay/catalog');const total=Object.values(c.counts).reduce((a,b)=>a+b,0);$('#datasetCounts').innerHTML=`Normal ${c.counts.normal} · Unbalance ${c.counts.unbalance} · Misalignment ${c.counts.misalignment} · Fastener Looseness ${c.counts.looseness}<br>${total} total · replay dataset for the recorded demo`;addLog('DEMO',`Replay dataset verified: ${total} files`)}catch(e){setText('datasetCounts',e.message)}}
async function loadHistory(){try{const rows=await api('/api/history');$('#historyTable').innerHTML=rows.length?rows.map(r=>`<tr><td>${new Date(r.ts).toLocaleString()}</td><td><b>${FAULT_LABELS[r.predicted]||r.predicted}</b></td><td>${(Number(r.confidence)*100).toFixed(1)}%</td><td>${FAULT_LABELS[r.fault_truth]||r.fault_truth||'—'}</td><td>${r.source==='esp32'?'PHYSICAL':(r.source==='replay'?'DEMO':esc(r.source))}</td></tr>`).join(''):'<tr><td colspan="5">No AI diagnosis history.</td></tr>'}catch{}}
$('#refreshHistory').addEventListener('click',loadHistory);

function durationBetween(a,b){if(!a)return'—';const ms=Math.max(0,(b?new Date(b):new Date())-new Date(a));return fmtDuration(ms/1000,false)}
async function loadRecordings(){try{const rows=await api('/api/recordings');$('#recordTable').innerHTML=rows.length?rows.map(r=>`<tr><td>${esc(r.name)}</td><td>${esc(String(r.source||'').toUpperCase())}</td><td>${esc(FAULT_LABELS[r.label]||r.label||'')}</td><td>${esc(r.status)}</td><td>${r.sample_count}</td><td>${durationBetween(r.started_at,r.ended_at)}</td><td>${new Date(r.started_at).toLocaleString()}</td><td><button class="mini-button" onclick="location.href='/api/recordings/${r.id}/download'">Download</button> <button class="mini-button" data-del-rec="${r.id}">Delete</button></td></tr>`).join(''):'<tr><td colspan="8">No recording sessions.</td></tr>';$$('[data-del-rec]').forEach(b=>b.addEventListener('click',()=>delRecording(b.dataset.delRec)))}catch{}}
async function delRecording(id){if(!confirm('Delete this recording CSV?'))return;await api(`/api/recordings/${id}`,{method:'DELETE'});addLog('RECORDING','Recording CSV deleted');loadRecordings()}
function syncRecordingUI(s){recActive=!!s.active;if(recActive){recStartedAt=s.started_at?new Date(s.started_at):new Date();recElapsedFrozen=Number(s.elapsed_s||0);$('#recIndicator').classList.add('active');setText('recStatus','Recording');setText('recFile',s.name||'—');setText('recLabelNow',FAULT_LABELS[s.label]||s.label||'—');setText('recSamples',String(s.sample_count||0));setText('recStarted',recStartedAt.toLocaleString());setText('recSource',String(s.source||'—').toUpperCase());$('#recordStart').disabled=true;$('#recordStop').disabled=false}else{recStartedAt=null;$('#recIndicator').classList.remove('active');setText('recStatus','Idle');$('#recordStart').disabled=false;$('#recordStop').disabled=true}}
async function loadRecordingStatus(){if(!currentUser)return;try{syncRecordingUI(await api('/api/recordings/status'))}catch{}}
$('#recordStart').addEventListener('click',async()=>{try{const payload={label:$('#recordLabel').value,source:workspace};const nm=$('#recordName').value.trim();if(nm)payload.name=nm.endsWith('.csv')?nm:`${nm}.csv`;const r=await api('/api/recordings/start',{method:'POST',body:JSON.stringify(payload)});syncRecordingUI({active:true,...r,elapsed_s:0});addLog('RECORDING',`${String(r.source).toUpperCase()} recording started · ${r.name}`);loadRecordings()}catch(e){alert(e.message)}});
$('#recordStop').addEventListener('click',async()=>{try{const r=await api('/api/recordings/stop',{method:'POST'});recElapsedFrozen=Number(r.duration_s||0);syncRecordingUI({active:false});setText('recElapsed',fmtDuration(recElapsedFrozen,true));setText('recSamples',String(r.sample_count||0));addLog('RECORDING',`Recording stopped · ${r.sample_count} samples`);loadRecordings()}catch(e){alert(e.message)}});
$('#refreshRec').addEventListener('click',()=>{loadRecordings();loadRecordingStatus()});
function fmtDuration(sec,tenths=false){sec=Math.max(0,Number(sec)||0);const h=Math.floor(sec/3600),m=Math.floor(sec%3600/60),s=Math.floor(sec%60),d=Math.floor((sec-Math.floor(sec))*10);return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}${tenths?'.'+d:''}`}
function updateRecordingClock(){let sec=recElapsedFrozen;if(recActive&&recStartedAt)sec=Math.max(0,(Date.now()-recStartedAt.getTime())/1000);setText('recElapsed',fmtDuration(sec,true))}
function renderCaptureTable(){const kind=workspace==='demo'?'demo':'physical',s=streams[kind],rows=s.recentRows,el=$('#captureTable');if(!el)return;setText('captureHint',s.lastTelemetryAt?`Latest ${s.lastTelemetryAt.toLocaleTimeString()}`:'Waiting for data');el.innerHTML=rows.length?rows.map((r,i)=>`<tr><td>${esc(r.sample_index??s.sampleCounter-i)}</td><td>${num(r.elapsed_ms,0)} ms</td><td>${num(r.ax_g,4)}</td><td>${num(r.ay_g,4)}</td><td>${num(r.az_g,4)}</td><td>${num(r.total_g,4)}</td><td>${num(r.rpm,0)}</td><td>${num(r.target_rpm,0)}</td><td>${num(r.pwm_eq,2)}</td><td>${num(r.current_a,3)}</td><td>${esc(r.control_mode||'—')}</td></tr>`).join(''):'<tr><td colspan="11">No telemetry received.</td></tr>'}


const visionState={
  status:{},config:null,savedConfig:null,tool:null,dragStart:null,tempRect:null,
  frameMtime:0,pendingFrameMtime:0,displayedFrameMtime:0,frameNaturalW:1280,frameNaturalH:720,lastFrameRefresh:0,localFrameLoadedAt:0,localFrameSeq:0,edgeInfo:null,serverMeta:{},frameFetchInFlight:false,frameFetchErrors:0,localObjectUrl:null,localHostIndex:0
};
const VISION_ROI_LABELS={hall_led:'Hall Sensor LED',rotor:'Rotor',adxl345:'ADXL345',acs712:'ACS712',hall_sensor:'Hall Sensor'};
const VISION_TOOL_HELP={
  hazard:'Click at least three points around the restricted machine area. Right-click or use Undo Point to remove the last point.',
  hall_led:'Draw a tight rectangle around the Hall sensor LED that actually blinks.',
  rotor:'Draw around the moving rotor, pulley, or disk.',
  adxl345:'Include the ADXL345 and its mounting surface in the ROI.',
  acs712:'If the ACS712 is visible, draw its mounting area.',
  hall_sensor:'If the Hall sensor is visible, draw its mounting area.'
};
function visionDefaultConfig(){return{schema_revision:3,hazard_polygon:[],warning_margin_px:90,rois:{},baseline_revision:0,baseline_required:true,setup_frame_width:0,setup_frame_height:0,setup_camera_index:-1}}
function visionClone(x){return JSON.parse(JSON.stringify(x||visionDefaultConfig()))}
function visionTone(id,tone){const e=$('#'+id);if(!e)return;e.classList.remove('vision-status-ok','vision-status-warn','vision-status-danger');if(tone)e.classList.add('vision-status-'+tone)}
function visionFrameIsLive(){const st=visionState.status||{},meta=visionState.serverMeta||{},required=Number(visionState.edgeInfo?.required_protocol||3),protocolOk=Number(st.vision_protocol||0)>=required,statusAge=Number.isFinite(Number(meta.edge_age_s))?Number(meta.edge_age_s):(st.server_received_ts?Math.max(0,Date.now()/1000-Number(st.server_received_ts)):9999),frameAge=Number.isFinite(Number(meta.frame_age_s))?Number(meta.frame_age_s):(visionState.frameMtime?Math.max(0,Date.now()/1000-Number(visionState.frameMtime)):9999),stage=$('#visionStage'),reportedW=Number(st.frame_width||0),reportedH=Number(st.frame_height||0),dimsMatch=reportedW>0&&reportedH>0&&visionState.frameNaturalW===reportedW&&visionState.frameNaturalH===reportedH;return protocolOk&&st.camera_ok===true&&meta.frame_available===true&&statusAge<5&&frameAge<5&&dimsMatch&&!!stage?.classList.contains('has-frame')}
function visionSetTool(tool){
  if(tool&&!visionFrameIsLive()){alert('Wait until a live camera frame is visible before editing the setup.');return}
  visionState.tool=tool||null;visionState.dragStart=null;visionState.tempRect=null;
  $$('.vision-tool').forEach(b=>b.classList.toggle('active',b.dataset.visionTool===tool));
  setText('visionToolLabel',tool?`Edit · ${tool==='hazard'?'Hazard Zone':VISION_ROI_LABELS[tool]||tool}`:'View');
  setText('visionToolHelp',tool?(VISION_TOOL_HELP[tool]||'Draw the area on the camera frame.'):'Saved settings load automatically. Choose an item below to edit.');
  visionDrawOverlay();
}
function visionNormalizeLoaded(cfg){
  if(!cfg||!cfg.configured)return visionDefaultConfig();
  const m=Number(cfg.warning_margin_px??90),margin=Number.isFinite(m)?Math.max(0,Math.min(500,m)):90;
  return{schema_revision:3,revision:cfg.revision||0,baseline_revision:cfg.baseline_revision||0,baseline_required:cfg.baseline_required!==false,hazard_polygon:Array.isArray(cfg.hazard_polygon)?cfg.hazard_polygon:[],warning_margin_px:margin,rois:cfg.rois&&typeof cfg.rois==='object'?cfg.rois:{},setup_frame_width:Number(cfg.setup_frame_width||0),setup_frame_height:Number(cfg.setup_frame_height||0),setup_camera_index:Number.isFinite(Number(cfg.setup_camera_index))?Number(cfg.setup_camera_index):-1};
}
async function visionLoadConfig(){
  if(workspace!=='physical'||!currentUser)return;
  try{
    const cfg=await api('/api/vision/config');
    visionState.config=visionNormalizeLoaded(cfg);visionState.savedConfig=visionClone(visionState.config);
    visionState.serverMeta={...visionState.serverMeta,configured:!!cfg.configured,config_revision:Number(cfg.revision||0),baseline_revision:Number(cfg.baseline_revision||0),baseline_required:cfg.baseline_required!==false};
    if($('#visionWarningPx'))$('#visionWarningPx').value=visionState.config.warning_margin_px??90;
    const configured=!!cfg.configured,baselineReady=Number(cfg.baseline_revision||0)>0&&!cfg.baseline_required;setText('visionConfigBadge',configured?(baselineReady?'Saved':'Saved · Sensor Baseline Required'):'Not Configured');setTagTone('visionConfigBadge',configured&&baselineReady?'ok':'warning');
    visionDrawOverlay();
  }catch(e){addLog('VISION',`Failed to load setup · ${e.message}`)}
}
async function visionLoadEdgeInfo(){
  if(workspace!=='physical'||!currentUser)return;
  try{const x=await api('/api/vision/edge-info');visionState.edgeInfo={...x,server_url:location.origin};setText('visionEdgeHint',x.ready?'Connection ready · Vision processing runs on this PC and detection results are synchronized with the server.':'Vision Edge is not ready. Verify the server deployment.')}catch(e){setText('visionEdgeHint',e.message)}
}
async function visionRefreshStatus(){
  if(workspace!=='physical'||!currentUser)return;
  try{const x=await api('/api/vision/status');visionState.serverMeta=x;visionState.frameMtime=Number(x.frame_mtime||0);renderVisionStatus(x.status||{},x);const live=Number.isFinite(Number(x.edge_age_s))&&Number(x.edge_age_s)<5&&x.status?.camera_ok===true,frameLive=x.frame_available===true&&Number.isFinite(Number(x.frame_age_s))&&Number(x.frame_age_s)<5,isVision=$('.page.active')?.id==='vision';if(isVision&&live&&frameLive)visionRefreshFrame();else if(isVision)visionHideStaleFrame(!live?'Waiting for camera connection.':'Waiting for a new camera frame.');}
  catch(e){setText('visionEdgeAge',e.message)}
}
function visionRenderCameraChoices(v={},edgeOnline=false){
  const box=$('#visionCameraChoices'),hint=$('#visionCameraChoiceHint');if(!box)return;box.replaceChildren();
  const cams=Array.isArray(v.available_cameras)?v.available_cameras:[],active=Number(v.camera_index);
  if(!cams.length){const e=document.createElement('span');e.className='vision-camera-empty';e.textContent=edgeOnline?'Searching for cameras. Wait a moment or restart the Windows Vision Edge.':'Available cameras appear after the Windows Vision Edge starts.';box.appendChild(e);return}
  for(const item of cams){const idx=Number(typeof item==='object'?item.index:item);if(!Number.isInteger(idx)||idx<0)continue;const label=(typeof item==='object'&&item.label)?String(item.label):`Camera ${idx}`;const b=document.createElement('button');b.type='button';b.className='vision-camera-choice'+(idx===active?' active':'');b.textContent=idx===active?`${label} · Active`:label;b.disabled=!edgeOnline;b.addEventListener('click',()=>visionSelectCamera(idx));box.appendChild(b)}
  const err=String(v.camera_switch_error||'');if(hint&&err)hint.textContent=err;else if(hint)hint.textContent='Choose a camera. After changing cameras, save the hazard zone and sensor baseline again.';
}
async function visionSelectCamera(index){
  const idx=Number(index);if(!Number.isInteger(idx)||idx<0)return;const rawCurrent=visionState.status?.camera_index,current=Number(rawCurrent),cameraActive=visionState.status?.camera_ok===true&&rawCurrent!==null&&rawCurrent!==undefined&&Number.isInteger(current)&&current>=0;if(cameraActive&&current===idx)return;
  if(visionState.serverMeta?.configured&&!confirm(`Camera ${idx}? Changing cameras requires saving the hazard zone/ROIs and sensor baseline again.`))return;
  try{setText('visionCameraChoiceHint',`Camera ${idx} connecting…`);const r=await api('/api/vision/camera/select',{method:'POST',body:JSON.stringify({camera_index:idx})});addLog('VISION',`Camera ${idx} selected`);if(r.unchanged)setText('visionCameraChoiceHint',`Camera ${idx} is already selected.`);setTimeout(()=>visionRefreshStatus(),350)}catch(e){setText('visionCameraChoiceHint',e.message);alert(e.message)}
}
async function visionCameraOff(){
  const online=Number.isFinite(Number(visionState.serverMeta?.edge_age_s))&&Number(visionState.serverMeta.edge_age_s)<5;if(!online){alert('Vision Edge is offline.');return}
  if(!visionState.status?.camera_ok){setText('visionCameraChoiceHint','The camera is already off.');return}
  try{setText('visionCameraChoiceHint','Turning camera off…');await api('/api/vision/camera/off',{method:'POST'});addLog('VISION','Camera turned off from the dashboard');visionHideStaleFrame('Camera is off. Select a camera below.');setTimeout(()=>visionRefreshStatus(),500)}catch(e){setText('visionCameraChoiceHint',e.message);alert(e.message)}
}

function visionZoneLabel(z){return z==='danger'?'Danger':z==='warning'?'Warning':z==='safe'?'Safe':z==='unconfigured'?'Zone Not Configured':'Checking'}
function renderVisionStatus(v={},wrapper=null){
  visionState.status=v||{};const meta=wrapper||visionState.serverMeta||{};if(wrapper)visionState.serverMeta=wrapper;
  const age=wrapper?.edge_age_s??((v.server_received_ts)?Math.max(0,Date.now()/1000-Number(v.server_received_ts)):9999),online=Number.isFinite(Number(age))&&Number(age)<5;
  setText('visionEdgeState',online?'Online':'Offline');visionTone('visionEdgeState',online?'ok':'danger');setText('visionConnectorBadge',online?'Connected':'Offline');setTagTone('visionConnectorBadge',online?'ok':'warning');setText('visionEdgeAge',online?`Updated ${Number(age).toFixed(1)}s ago`:'Waiting for Windows Vision Edge');
  const cam=online&&!!v.camera_ok,cameraUserOff=online&&v.camera_user_off===true;setText('visionCameraState',cam?'Connected':cameraUserOff?'Off':online?'Waiting for Selection':'Offline');visionTone('visionCameraState',cam?'ok':cameraUserOff?'warn':online?'warn':'danger');setText('visionCameraMeta',cam?`Camera ${v.camera_index??'—'} · ${num(v.fps,1)} fps · ${v.frame_width||'—'}×${v.frame_height||'—'}`:cameraUserOff?'Camera was turned off from the dashboard':online?'Select a camera':'No camera status');
  const offBtn=$('#visionCameraOff');if(offBtn){offBtn.disabled=!online||!cam;offBtn.textContent=cam?'Turn Camera Off':'Camera Off'}visionRenderCameraChoices(v,online);
  const requiredProtocol=Number(visionState.edgeInfo?.required_protocol||3),edgeProtocol=Number(v.vision_protocol||0),edgeProtocolOk=edgeProtocol>=requiredProtocol,configured=meta.configured!==undefined?!!meta.configured:(!!v.configured||!!visionState.config?.hazard_polygon?.length),savedRev=Number(meta.config_revision??visionState.config?.revision??0),edgeRev=Number(v.config_revision||0),synced=!configured||(savedRev>0&&edgeRev===savedRev),frameCompatRaw=v.frame_config_compatible,frameCompatible=!configured||(edgeProtocolOk&&frameCompatRaw===true),frameMismatch=configured&&edgeProtocolOk&&frameCompatRaw===false;
  const detectorOk=online&&v.person_detector_ok===true,persons=Number(v.person_count||0),zone=String(v.person_zone||'unknown').toLowerCase();
  if(!online||!cam){setText('visionPersonCount','—');setText('visionPersonZone','Checking');visionTone('visionPersonZone','warn');setText('visionPersonDetail',!online?'Waiting for Vision Edge':'Waiting for camera selection');visionTone('visionPersonDetail','warn')}
  else if(!edgeProtocolOk){setText('visionPersonCount','—');setText('visionPersonZone','Update Required');visionTone('visionPersonZone','warn');setText('visionPersonDetail','Restart the Windows Vision Edge with the current release.');visionTone('visionPersonDetail','warn')}
  else if(configured&&!synced){setText('visionPersonCount','—');setText('visionPersonZone','Syncing Setup');visionTone('visionPersonZone','warn');setText('visionPersonDetail','Synchronizing the saved setup.');visionTone('visionPersonDetail','warn')}
  else if(configured&&!frameCompatible){setText('visionPersonCount','—');setText('visionPersonZone','Reconfiguration Required');visionTone('visionPersonZone','warn');setText('visionPersonDetail',frameMismatch?'The camera or frame geometry changed. Save the setup again.':'Verifying camera setup.');visionTone('visionPersonDetail','warn')}
  else if(!detectorOk){setText('visionPersonCount','—');setText('visionPersonZone','Unavailable');visionTone('visionPersonZone','warn');setText('visionPersonDetail','Person detector is unavailable.');visionTone('visionPersonDetail','warn')}
  else if(!configured||zone==='unconfigured'){setText('visionPersonCount',String(persons));setText('visionPersonZone','Zone Not Configured');visionTone('visionPersonZone','warn');setText('visionPersonDetail',`Person ${persons} detected · save the hazard zone first.`);visionTone('visionPersonDetail','warn')}
  else{setText('visionPersonCount',String(persons));setText('visionPersonZone',visionZoneLabel(zone));visionTone('visionPersonZone',zone==='danger'?'danger':zone==='warning'?'warn':'ok');setText('visionPersonDetail',persons?`Person ${persons} detected · ${visionZoneLabel(zone)}`:'No Person');visionTone('visionPersonDetail',zone==='danger'?'danger':zone==='warning'?'warn':'ok')}
  const hands=Number(v.hand_count||0),handZone=String(v.hand_zone||'unknown').toLowerCase(),handOk=online&&v.hand_detector_ok===true;
  if(!online||!cam){setText('visionHandCount','—');setText('visionHandZone','Checking');visionTone('visionHandZone','warn');setText('visionHandDetail',!online?'Waiting for Vision Edge':'Waiting for camera selection');visionTone('visionHandDetail','warn')}
  else if(!handOk){setText('visionHandCount','—');setText('visionHandZone','Unavailable');visionTone('visionHandZone','warn');setText('visionHandDetail','Hand detector is unavailable.');visionTone('visionHandDetail','warn')}
  else if(!configured||handZone==='unconfigured'){setText('visionHandCount',String(hands));setText('visionHandZone','Zone Not Configured');visionTone('visionHandZone','warn');setText('visionHandDetail',`Hand ${hands} detected · save the hazard zone first.`);visionTone('visionHandDetail','warn')}
  else{setText('visionHandCount',String(hands));setText('visionHandZone',visionZoneLabel(handZone));visionTone('visionHandZone',handZone==='danger'?'danger':handZone==='warning'?'warn':'ok');setText('visionHandDetail',hands?`Hand ${hands} detected · ${visionZoneLabel(handZone)}`:'No Hand');visionTone('visionHandDetail',handZone==='danger'?'danger':handZone==='warning'?'warn':'ok')}
  const led=v.hall_led||{},ledReady=online&&cam&&configured&&synced&&frameCompatible&&led.configured!==false,blink=ledReady&&!!led.blink_detected;setText('visionHallLed',ledReady?(blink?'Blink Detected':'No Blink'):'Waiting');visionTone('visionHallLed',ledReady?(blink?'ok':'warn'):'warn');setText('visionHallLedMeta',ledReady?`${num(led.blink_rate_hz,2)} Hz · blinks ${Number(led.blink_events||0)} · brightness delta ${num(led.brightness_delta,1)}`:!online?'Waiting for Vision Edge':!cam?'Waiting for camera selection':configured&&!synced?'Synchronizing setup':configured&&!frameCompatible?'Camera reconfiguration required':'Configure the Hall sensor LED ROI.');setText('visionLedDetail',ledReady?(blink?`Blink Detected · ${num(led.blink_rate_hz,2)} Hz`:'No repeated brightness transitions'):'Waiting');visionTone('visionLedDetail',blink?'ok':'warn');
  const rotor=v.rotor||{},rotorReady=online&&cam&&configured&&synced&&frameCompatible&&rotor.configured!==false,moving=rotorReady&&!!rotor.motion_detected;setText('visionRotor',rotorReady?(moving?'Motion Detected':'Stopped'):'Waiting');visionTone('visionRotor',rotorReady?(moving?'ok':'warn'):'warn');setText('visionRotorMeta',rotorReady?`Motion score ${num(rotor.motion_score,2)}`:!online?'Waiting for Vision Edge':!cam?'Waiting for camera selection':'Configure the rotor ROI.');setText('visionRotorDetail',rotorReady?(moving?'Rotor motion detected':'No motion'):'Waiting');visionTone('visionRotorDetail',moving?'ok':'warn');
  const requestedBaseline=Number(meta.baseline_revision??visionState.config?.baseline_revision??0),savedBaselineReady=configured&&requestedBaseline>0&&meta.baseline_required===false,baselineReady=online&&cam&&synced&&v.baseline_ready===true&&Number(v.baseline_revision||0)===requestedBaseline,sensors=v.sensors||{},sensorKeys=['adxl345','acs712','hall_sensor'];let good=0,bad=0;
  for(const k of sensorKeys){let st=String(sensors[k]?.status||'not_configured').toLowerCase();if(!online)st='offline';else if(!cam)st='camera_offline';else if(!configured)st='not_configured';else if(!synced)st='syncing';else if(!frameCompatible)st='frame_mismatch';if(st==='ok'&&baselineReady)good++;else if((st==='changed'||st==='missing')&&baselineReady)bad++;const id=k==='adxl345'?'visionAdxlStatus':k==='acs712'?'visionAcsStatus':'visionHallStatus';const txt=st==='ok'&&baselineReady?`OK · diff ${num(sensors[k]?.diff,1)}`:st==='changed'&&baselineReady?`Changed · diff ${num(sensors[k]?.diff,1)}`:st==='checking'&&baselineReady?`Checking · diff ${num(sensors[k]?.diff,1)}`:st==='missing'&&baselineReady?'Sensor Missing':st==='syncing'?'Syncing Setup':st==='frame_mismatch'?'Camera Reconfiguration Required':st==='not_configured'?'Not Configured':st==='offline'?'Vision Edge Offline':st==='camera_offline'?'Camera Off':st==='uncalibrated'||!baselineReady?'Sensor Baseline Required':'Checking';setText(id,txt);visionTone(id,st==='ok'&&baselineReady?'ok':(st==='changed'||st==='missing')&&baselineReady?'danger':'warn')}
  const mountTxt=!online?'Offline':!cam?'Camera Off':!configured?'Not Configured':!synced?'Syncing Setup':!frameCompatible?'Reconfiguration Required':bad?`${bad} changed`:good?`${good} OK`:savedBaselineReady&&!baselineReady?'Baseline Missing':savedBaselineReady?'Checking':'Sensor Baseline Required';setText('visionMountSummary',mountTxt);visionTone('visionMountSummary',bad?'danger':good?'ok':'warn');
  if($('#visionConfigBadge')){if(configured&&online&&cam&&!frameCompatible){setText('visionConfigBadge','Saved · Camera Reconfiguration Required');setTagTone('visionConfigBadge','warning')}else if(configured&&!savedBaselineReady){setText('visionConfigBadge','Saved · Sensor Baseline Required');setTagTone('visionConfigBadge','warning')}else if(configured&&online&&cam&&synced&&frameCompatible&&savedBaselineReady&&!baselineReady){setText('visionConfigBadge','Saved · Recapture Sensor Baseline');setTagTone('visionConfigBadge','warning')}else if(configured){setText('visionConfigBadge','Saved');setTagTone('visionConfigBadge','ok')}else{setText('visionConfigBadge','Not Configured');setTagTone('visionConfigBadge','warning')}}
  visionDrawOverlay();
}
function visionSetNoFrame(message){setText('visionNoFrameText',message)}
function visionHideStaleFrame(message='Waiting for camera frame.'){const stage=$('#visionStage'),img=$('#visionFrameImg');visionState.pendingFrameMtime=0;visionState.displayedFrameMtime=0;if(stage)stage.classList.remove('has-frame');if(img&&img.getAttribute('src'))img.removeAttribute('src');visionSetNoFrame(message)}
function visionRefreshFrame(force=false){
  if(workspace!=='physical'||!currentUser)return;const img=$('#visionFrameImg');if(!img)return;const now=Date.now();if(!force&&now-visionState.lastFrameRefresh<550)return;visionState.lastFrameRefresh=now;visionState.pendingFrameMtime=visionState.frameMtime||0;img.style.visibility='visible';img.src=`/api/vision/frame.jpg?t=${visionState.pendingFrameMtime||now}`;
}
function visionImageLoaded(){
  const img=$('#visionFrameImg'),stage=$('#visionStage'),canvas=$('#visionOverlay');if(!img||!stage||!canvas||!img.naturalWidth)return;
  const meta=visionState.serverMeta||{},age=Number.isFinite(Number(meta.edge_age_s))?Number(meta.edge_age_s):9999,frameAge=Number.isFinite(Number(meta.frame_age_s))?Number(meta.frame_age_s):9999;if(!visionState.status?.camera_ok||meta.frame_available!==true||age>=5||frameAge>=5){visionHideStaleFrame(age>=5||!visionState.status?.camera_ok?'Waiting for camera connection.':'Waiting for a new camera frame.');return}
  const reportedW=Number(visionState.status?.frame_width||0),reportedH=Number(visionState.status?.frame_height||0);if(reportedW>0&&reportedH>0&&(img.naturalWidth!==reportedW||img.naturalHeight!==reportedH)){visionHideStaleFrame('Synchronizing the current camera frame.');return}
  visionState.frameNaturalW=img.naturalWidth;visionState.frameNaturalH=img.naturalHeight;visionState.displayedFrameMtime=visionState.pendingFrameMtime||visionState.frameMtime||0;stage.classList.add('has-frame');visionSetNoFrame('');stage.style.aspectRatio=`${img.naturalWidth}/${img.naturalHeight}`;canvas.width=img.naturalWidth;canvas.height=img.naturalHeight;visionDrawOverlay();
}
function visionImageError(){visionHideStaleFrame('Waiting for a new camera frame.')}
function visionEffectiveMargin(cfg,w,h){const raw=Math.max(0,Math.min(500,Number(cfg?.warning_margin_px??90)||0)),sw=Number(cfg?.setup_frame_width||cfg?.frame_width||0),sh=Number(cfg?.setup_frame_height||cfg?.frame_height||0);if(sw>1&&sh>1){const scale=Math.min(w/sw,h/sh);if(Number.isFinite(scale)&&scale>0)return raw*scale}return raw}
function visionDrawOverlay(){
  const c=$('#visionOverlay');if(!c||!c.width)return;const ctx=c.getContext('2d'),w=c.width,h=c.height;ctx.clearRect(0,0,w,h);const cfg=visionState.config||visionDefaultConfig();
  const poly=cfg.hazard_polygon||[];if(poly.length){ctx.beginPath();poly.forEach((p,i)=>{const x=p[0]*w,y=p[1]*h;i?ctx.lineTo(x,y):ctx.moveTo(x,y)});if(poly.length>=3)ctx.closePath();const effectiveMargin=visionEffectiveMargin(cfg,w,h);if(poly.length>=3&&effectiveMargin>0){ctx.save();ctx.strokeStyle='rgba(242,185,75,.22)';ctx.lineJoin='round';ctx.lineCap='round';ctx.lineWidth=Math.max(2,effectiveMargin*2);ctx.stroke();ctx.restore()}ctx.fillStyle='rgba(255,80,80,.17)';if(poly.length>=3)ctx.fill();ctx.strokeStyle='#ff6464';ctx.lineWidth=Math.max(2,w/600);ctx.stroke();poly.forEach((p,i)=>{ctx.beginPath();ctx.arc(p[0]*w,p[1]*h,Math.max(4,w/250),0,Math.PI*2);ctx.fillStyle='#ff8b8b';ctx.fill();ctx.fillStyle='#fff';ctx.font=`${Math.max(12,w/90)}px sans-serif`;ctx.fillText(String(i+1),p[0]*w+7,p[1]*h-7)})}
  const colors={hall_led:'#37d39a',rotor:'#4aa3ff',adxl345:'#f2b94b',acs712:'#45c7e8',hall_sensor:'#b78cff'};for(const [k,r] of Object.entries(cfg.rois||{})){if(!r)continue;const x=r.x*w,y=r.y*h,rw=r.w*w,rh=r.h*h;ctx.strokeStyle=colors[k]||'#fff';ctx.lineWidth=Math.max(2,w/700);ctx.strokeRect(x,y,rw,rh);ctx.fillStyle='rgba(7,12,17,.72)';ctx.fillRect(x,Math.max(0,y-24),Math.min(rw,160),22);ctx.fillStyle=colors[k]||'#fff';ctx.font=`bold ${Math.max(11,w/110)}px sans-serif`;ctx.fillText(VISION_ROI_LABELS[k]||k,x+5,Math.max(14,y-7))}
  const st=visionState.status||{},meta=visionState.serverMeta||{},fw=Number(st.frame_width||w),fh=Number(st.frame_height||h),peopleSynced=!!meta.configured&&st.frame_config_compatible===true&&Number(st.config_revision||0)===Number(meta.config_revision||0)&&!visionState.tool;if(peopleSynced)for(const person of (Array.isArray(st.people)?st.people:[])){const b=person.xyxy;if(!Array.isArray(b)||b.length!==4||!fw||!fh)continue;const x1=b[0]/fw*w,y1=b[1]/fh*h,x2=b[2]/fw*w,y2=b[3]/fh*h,z=String(person.zone||'safe').toLowerCase();ctx.strokeStyle=z==='danger'?'#ff6464':z==='warning'?'#f2b94b':z==='unconfigured'?'#a0aab3':'#37d39a';ctx.lineWidth=Math.max(2,w/500);ctx.strokeRect(x1,y1,x2-x1,y2-y1);ctx.fillStyle='rgba(7,12,17,.78)';ctx.fillRect(x1,Math.max(0,y1-24),Math.min(170,x2-x1),22);ctx.fillStyle=ctx.strokeStyle;ctx.font=`bold ${Math.max(11,w/110)}px sans-serif`;ctx.fillText(`Person ${visionZoneLabel(z)} ${num(person.confidence,2)}`,x1+5,Math.max(14,y1-7))}
  if(peopleSynced)for(const hand of (Array.isArray(st.hands)?st.hands:[])){const b=hand.xyxy;if(!Array.isArray(b)||b.length!==4||!fw||!fh)continue;const x1=b[0]/fw*w,y1=b[1]/fh*h,x2=b[2]/fw*w,y2=b[3]/fh*h,z=String(hand.zone||'safe').toLowerCase();ctx.strokeStyle=z==='danger'?'#ff6464':z==='warning'?'#f2b94b':'#45c7e8';ctx.lineWidth=Math.max(2,w/550);ctx.strokeRect(x1,y1,x2-x1,y2-y1);ctx.fillStyle='rgba(7,12,17,.78)';ctx.fillRect(x1,Math.max(0,y1-22),Math.min(150,x2-x1),20);ctx.fillStyle=ctx.strokeStyle;ctx.font=`bold ${Math.max(10,w/120)}px sans-serif`;ctx.fillText(`Hand ${visionZoneLabel(z)}`,x1+5,Math.max(13,y1-6))}
  if(visionState.tempRect){const r=visionState.tempRect;ctx.setLineDash([8,5]);ctx.strokeStyle='#fff';ctx.lineWidth=Math.max(2,w/700);ctx.strokeRect(r.x*w,r.y*h,r.w*w,r.h*h);ctx.setLineDash([])}
}
function visionPointerNorm(ev){const c=$('#visionOverlay'),r=c.getBoundingClientRect();return{x:Math.max(0,Math.min(1,(ev.clientX-r.left)/r.width)),y:Math.max(0,Math.min(1,(ev.clientY-r.top)/r.height))}}
function visionPointerDown(ev){
  if(!visionState.tool||!visionState.config||!visionFrameIsLive())return;ev.preventDefault();const p=visionPointerNorm(ev);
  if(visionState.tool==='hazard'){visionState.config.hazard_polygon.push([p.x,p.y]);visionDrawOverlay();return}
  try{ev.currentTarget?.setPointerCapture?.(ev.pointerId)}catch(_){}visionState.dragStart=p;visionState.tempRect={x:p.x,y:p.y,w:0,h:0};visionDrawOverlay();
}
function visionPointerMove(ev){if(!visionState.dragStart||!visionState.tool||visionState.tool==='hazard')return;const p=visionPointerNorm(ev),a=visionState.dragStart;visionState.tempRect={x:Math.min(a.x,p.x),y:Math.min(a.y,p.y),w:Math.abs(p.x-a.x),h:Math.abs(p.y-a.y)};visionDrawOverlay()}
function visionPointerUp(ev){if(!visionState.dragStart||!visionState.tool||visionState.tool==='hazard')return;visionPointerMove(ev);const r=visionState.tempRect;if(r&&r.w>.005&&r.h>.005)visionState.config.rois[visionState.tool]=r;visionState.dragStart=null;visionState.tempRect=null;visionDrawOverlay()}
function visionUndo(){if(!visionState.config)return;if(visionState.tool==='hazard'&&visionState.config.hazard_polygon.length)visionState.config.hazard_polygon.pop();else if(visionState.tool&&visionState.tool!=='hazard')delete visionState.config.rois[visionState.tool];visionDrawOverlay()}
async function visionSave(){
  if(!visionState.config)return;if(!visionFrameIsLive()){alert('Wait until a live camera frame is visible before saving the setup.');return}const cameraIndex=Number(visionState.status?.camera_index);if(!Number.isInteger(cameraIndex)||cameraIndex<0){alert('Active camera information is not available yet. Try again shortly.');return}const rawMargin=Number($('#visionWarningPx')?.value??90);visionState.config.warning_margin_px=Number.isFinite(rawMargin)?Math.max(0,Math.min(500,rawMargin)):90;visionState.config.frame_width=visionState.frameNaturalW||0;visionState.config.frame_height=visionState.frameNaturalH||0;visionState.config.camera_index=cameraIndex;const missing=[];if((visionState.config.hazard_polygon||[]).length<3)missing.push('Hazard Zone');for(const k of ['hall_led','rotor','adxl345'])if(!visionState.config.rois?.[k])missing.push(VISION_ROI_LABELS[k]);if(missing.length){alert(`Configure first: ${missing.join(', ')}`);return}
  try{const r=await api('/api/vision/config',{method:'POST',body:JSON.stringify(visionState.config)});visionState.config=visionNormalizeLoaded({configured:true,...r});visionState.savedConfig=visionClone(visionState.config);visionState.serverMeta={...visionState.serverMeta,configured:true,config_revision:Number(r.revision||0),baseline_revision:Number(r.baseline_revision||0),baseline_required:r.baseline_required!==false};visionSetTool(null);const baselineReady=Number(r.baseline_revision||0)>0&&!r.baseline_required;setText('visionConfigBadge',baselineReady?'Saved':'Saved · Sensor Baseline Required');setTagTone('visionConfigBadge',baselineReady?'ok':'warning');if(r.unchanged){addLog('VISION','Setup unchanged · existing sensor baseline retained');alert(baselineReady?'The setup is unchanged, so the existing sensor baseline was retained.':'The setup is unchanged. Place the sensors correctly, then capture the sensor baseline.')}else{addLog('VISION','Setup changed · previous sensor baseline invalidated');alert('Setup saved. Because the hazard zone or ROIs changed, the previous sensor baseline was invalidated. Place the sensors correctly, then capture a new baseline.')}}
  catch(e){alert(e.message)}
}
async function visionBaseline(){try{const r=await api('/api/vision/baseline',{method:'POST'});visionState.serverMeta={...visionState.serverMeta,baseline_revision:Number(r.baseline_revision||0),baseline_required:true};if(visionState.config){visionState.config.baseline_revision=Number(r.baseline_revision||0);visionState.config.baseline_required=true}setText('visionConfigBadge','Saved · Sensor Baseline Required');setTagTone('visionConfigBadge','warning');addLog('VISION',`Sensor baseline capture requested · ${r.baseline_revision}`);alert('Sensor baseline capture requested. Keep the camera and sensors still for a moment.')}catch(e){alert(e.message)}}
async function visionReset(){if(!confirm('Reset the saved hazard zone, sensor ROIs, and sensor baseline?'))return;try{await api('/api/vision/config',{method:'DELETE'});visionState.config=visionDefaultConfig();visionState.savedConfig=visionClone(visionState.config);visionState.status={};visionState.frameMtime=0;visionState.pendingFrameMtime=0;visionState.displayedFrameMtime=0;visionState.localFrameLoadedAt=0;visionState.serverMeta={...visionState.serverMeta,configured:false,config_revision:0,baseline_revision:0,baseline_required:true,frame_available:false,frame_mtime:0,frame_age_s:null};visionHideStaleFrame('Setup reset. Waiting for camera frame.');if($('#visionWarningPx'))$('#visionWarningPx').value=90;setText('visionConfigBadge','Not Configured');setTagTone('visionConfigBadge','warning');visionSetTool(null);visionDrawOverlay();addLog('VISION','Vision setup reset')}catch(e){alert(e.message)}}
function visionCancelEdit(){visionState.config=visionClone(visionState.savedConfig||visionDefaultConfig());if($('#visionWarningPx'))$('#visionWarningPx').value=visionState.config.warning_margin_px??90;visionSetTool(null);visionDrawOverlay()}
async function visionLoadAll(){if(workspace!=='physical'||!currentUser)return;await Promise.allSettled([visionLoadConfig(),visionLoadEdgeInfo(),visionRefreshStatus()])}
$$('.vision-tool').forEach(b=>b.addEventListener('click',()=>visionSetTool(b.dataset.visionTool)));$('#visionUndoPoint')?.addEventListener('click',visionUndo);$('#visionCancelEdit')?.addEventListener('click',visionCancelEdit);$('#visionSaveConfig')?.addEventListener('click',visionSave);$('#visionCaptureBaseline')?.addEventListener('click',visionBaseline);$('#visionResetConfig')?.addEventListener('click',visionReset);$('#visionRefresh')?.addEventListener('click',()=>visionRefreshStatus());$('#visionReloadConfig')?.addEventListener('click',visionLoadConfig);$('#visionCameraOff')?.addEventListener('click',visionCameraOff);
$('#visionFrameImg')?.addEventListener('load',visionImageLoaded);$('#visionFrameImg')?.addEventListener('error',visionImageError);$('#visionOverlay')?.addEventListener('pointerdown',visionPointerDown);$('#visionOverlay')?.addEventListener('pointermove',visionPointerMove);$('#visionOverlay')?.addEventListener('pointerup',visionPointerUp);$('#visionOverlay')?.addEventListener('pointercancel',()=>{visionState.dragStart=null;visionState.tempRect=null;visionDrawOverlay()});$('#visionOverlay')?.addEventListener('contextmenu',e=>{e.preventDefault();visionUndo()});


const demoVisionState={config:null,savedConfig:null,tool:null,dragStart:null,tempRect:null};
function demoVisionDefaultConfig(){return{schema_revision:1,hazard_polygon:[],warning_margin_px:90,rois:{},baseline_revision:0,baseline_required:true}}
function demoVisionClone(x){return JSON.parse(JSON.stringify(x||demoVisionDefaultConfig()))}
function demoVisionNormalize(cfg){if(!cfg||!cfg.configured)return demoVisionDefaultConfig();const m=Number(cfg.warning_margin_px??90);return{schema_revision:1,revision:Number(cfg.revision||0),hazard_polygon:Array.isArray(cfg.hazard_polygon)?cfg.hazard_polygon:[],warning_margin_px:Number.isFinite(m)?Math.max(0,Math.min(500,m)):90,rois:cfg.rois&&typeof cfg.rois==='object'?cfg.rois:{},baseline_revision:Number(cfg.baseline_revision||0),baseline_required:cfg.baseline_required!==false}}
function demoVisionBaselineReady(){const c=demoVisionState.config;return !!c&&Number(c.baseline_revision||0)>0&&c.baseline_required===false}
function demoVisionSetTool(tool){demoVisionState.tool=tool||null;demoVisionState.dragStart=null;demoVisionState.tempRect=null;$$('.demo-vision-tool').forEach(b=>b.classList.toggle('active',b.dataset.demoVisionTool===tool));setText('demoVisionToolLabel',tool?`Edit · ${tool==='hazard'?'Hazard Zone':VISION_ROI_LABELS[tool]||tool}`:'View');setText('demoVisionToolHelp',tool?(VISION_TOOL_HELP[tool]||'Draw the area on the fixed digital twin.'):'Use the fixed digital twin as the inspection view. Choose an item below to edit.');demoVisionDrawOverlay()}
function demoVisionCanvasPrep(){const c=$('#demoVisionOverlay');if(!c)return null;const d=Math.min(devicePixelRatio||1,2),w=Math.max(1,c.clientWidth),h=Math.max(1,c.clientHeight);if(c.width!==Math.floor(w*d)||c.height!==Math.floor(h*d)){c.width=Math.floor(w*d);c.height=Math.floor(h*d)}const ctx=c.getContext('2d');ctx.setTransform(d,0,0,d,0,0);ctx.clearRect(0,0,w,h);return{c,ctx,w,h}}
function demoVisionDrawOverlay(){const q=demoVisionCanvasPrep();if(!q)return;const {ctx,w,h}=q,cfg=demoVisionState.config||demoVisionDefaultConfig();const poly=Array.isArray(cfg.hazard_polygon)?cfg.hazard_polygon:[];if(poly.length){ctx.beginPath();poly.forEach((p,i)=>{const x=p[0]*w,y=p[1]*h;i?ctx.lineTo(x,y):ctx.moveTo(x,y)});if(poly.length>=3)ctx.closePath();ctx.fillStyle='rgba(255,76,76,.13)';ctx.fill();ctx.strokeStyle='#ff6464';ctx.lineWidth=Math.max(2,w/650);ctx.stroke();for(const p of poly){ctx.beginPath();ctx.arc(p[0]*w,p[1]*h,Math.max(4,w/230),0,Math.PI*2);ctx.fillStyle='#ff6464';ctx.fill()}ctx.fillStyle='#ff8585';ctx.font=`bold ${Math.max(11,w/100)}px sans-serif`;ctx.fillText('Hazard Zone',poly[0][0]*w+8,Math.max(16,poly[0][1]*h-8))}const colors={hall_led:'#e5d74f',rotor:'#54b8ff',adxl345:'#50df9f',acs712:'#e89a54',hall_sensor:'#bb8cff'};for(const [k,r] of Object.entries(cfg.rois||{})){if(!r)continue;const x=r.x*w,y=r.y*h,rw=r.w*w,rh=r.h*h;ctx.strokeStyle=colors[k]||'#fff';ctx.lineWidth=Math.max(2,w/650);ctx.strokeRect(x,y,rw,rh);ctx.fillStyle='rgba(7,12,17,.72)';ctx.fillRect(x,Math.max(0,y-22),Math.min(160,rw),20);ctx.fillStyle=colors[k]||'#fff';ctx.font=`bold ${Math.max(10,w/115)}px sans-serif`;ctx.fillText(VISION_ROI_LABELS[k]||k,x+5,Math.max(13,y-6))}if(demoVisionState.tempRect){const r=demoVisionState.tempRect;ctx.setLineDash([8,5]);ctx.strokeStyle='#fff';ctx.lineWidth=2;ctx.strokeRect(r.x*w,r.y*h,r.w*w,r.h*h);ctx.setLineDash([])}}
function demoVisionPointerNorm(ev){const c=$('#demoVisionOverlay'),r=c.getBoundingClientRect();return{x:Math.max(0,Math.min(1,(ev.clientX-r.left)/r.width)),y:Math.max(0,Math.min(1,(ev.clientY-r.top)/r.height))}}
function demoVisionPointerDown(ev){if(!demoVisionState.tool||!demoVisionState.config)return;ev.preventDefault();const p=demoVisionPointerNorm(ev);if(demoVisionState.tool==='hazard'){demoVisionState.config.hazard_polygon.push([p.x,p.y]);demoVisionDrawOverlay();return}try{ev.currentTarget?.setPointerCapture?.(ev.pointerId)}catch(_){}demoVisionState.dragStart=p;demoVisionState.tempRect={x:p.x,y:p.y,w:0,h:0};demoVisionDrawOverlay()}
function demoVisionPointerMove(ev){if(!demoVisionState.dragStart||!demoVisionState.tool||demoVisionState.tool==='hazard')return;const p=demoVisionPointerNorm(ev),a=demoVisionState.dragStart;demoVisionState.tempRect={x:Math.min(a.x,p.x),y:Math.min(a.y,p.y),w:Math.abs(p.x-a.x),h:Math.abs(p.y-a.y)};demoVisionDrawOverlay()}
function demoVisionPointerUp(ev){if(!demoVisionState.dragStart||!demoVisionState.tool||demoVisionState.tool==='hazard')return;demoVisionPointerMove(ev);const r=demoVisionState.tempRect;if(r&&r.w>.005&&r.h>.005)demoVisionState.config.rois[demoVisionState.tool]=r;demoVisionState.dragStart=null;demoVisionState.tempRect=null;demoVisionDrawOverlay()}
function demoVisionUndo(){if(!demoVisionState.config)return;if(demoVisionState.tool==='hazard'&&demoVisionState.config.hazard_polygon.length)demoVisionState.config.hazard_polygon.pop();else if(demoVisionState.tool&&demoVisionState.tool!=='hazard')delete demoVisionState.config.rois[demoVisionState.tool];demoVisionDrawOverlay();demoVisionRenderRuntime()}
function demoVisionCancel(){demoVisionState.config=demoVisionClone(demoVisionState.savedConfig||demoVisionDefaultConfig());if($('#demoVisionWarningPx'))$('#demoVisionWarningPx').value=demoVisionState.config.warning_margin_px??90;demoVisionSetTool(null);demoVisionRenderRuntime()}
async function demoVisionLoadConfig(){if(workspace!=='demo'||!currentUser)return;try{const cfg=await api('/api/demo/vision/config');demoVisionState.config=demoVisionNormalize(cfg);demoVisionState.savedConfig=demoVisionClone(demoVisionState.config);if($('#demoVisionWarningPx'))$('#demoVisionWarningPx').value=demoVisionState.config.warning_margin_px??90;const ready=demoVisionBaselineReady(),configured=!!cfg.configured;setText('demoVisionConfigBadge',configured?(ready?'Saved':'Saved · Sensor Baseline Required'):'Not Configured');setTagTone('demoVisionConfigBadge',configured&&ready?'ok':'warning');demoVisionDrawOverlay();demoVisionRenderRuntime()}catch(e){addLog('DEMO VISION',`Failed to load setup · ${e.message}`)}}
async function demoVisionSave(){if(!demoVisionState.config)return;const raw=Number($('#demoVisionWarningPx')?.value??90);demoVisionState.config.warning_margin_px=Number.isFinite(raw)?Math.max(0,Math.min(500,raw)):90;const missing=[];if((demoVisionState.config.hazard_polygon||[]).length<3)missing.push('Hazard Zone');for(const k of ['hall_led','rotor','adxl345'])if(!demoVisionState.config.rois?.[k])missing.push(VISION_ROI_LABELS[k]);if(missing.length){alert(`Configure first: ${missing.join(', ')}`);return}try{const r=await api('/api/demo/vision/config',{method:'POST',body:JSON.stringify(demoVisionState.config)});demoVisionState.config=demoVisionNormalize({configured:true,...r});demoVisionState.savedConfig=demoVisionClone(demoVisionState.config);demoVisionSetTool(null);const ready=demoVisionBaselineReady();setText('demoVisionConfigBadge',ready?'Saved':'Saved · Sensor Baseline Required');setTagTone('demoVisionConfigBadge',ready?'ok':'warning');demoVisionRenderRuntime();addLog('DEMO VISION',r.unchanged?'Setup Changed None':'Fixed-twin Vision setup saved');if(!ready)alert('Setup saved. Verify sensor positions, then capture the sensor baseline.')}catch(e){alert(e.message)}}
async function demoVisionBaseline(){try{const r=await api('/api/demo/vision/baseline',{method:'POST'});if(demoVisionState.config){demoVisionState.config.baseline_revision=Number(r.baseline_revision||0);demoVisionState.config.baseline_required=false;demoVisionState.savedConfig=demoVisionClone(demoVisionState.config)}setText('demoVisionConfigBadge','Saved');setTagTone('demoVisionConfigBadge','ok');demoVisionRenderRuntime();addLog('DEMO VISION','Sensor baseline captured')}catch(e){alert(e.message)}}
async function demoVisionReset(){if(!confirm('Reset the Recorded Demo hazard zone, sensor positions, and sensor baseline?'))return;try{await api('/api/demo/vision/config',{method:'DELETE'});demoVisionState.config=demoVisionDefaultConfig();demoVisionState.savedConfig=demoVisionClone(demoVisionState.config);if($('#demoVisionWarningPx'))$('#demoVisionWarningPx').value=90;setText('demoVisionConfigBadge','Not Configured');setTagTone('demoVisionConfigBadge','warning');demoVisionSetTool(null);demoVisionRenderRuntime();addLog('DEMO VISION','Fixed-twin Vision setup reset')}catch(e){alert(e.message)}}
function demoVisionRenderRuntime(){if(workspace!=='demo')return;const c=demoVisionState.config||demoVisionDefaultConfig(),configured=(c.hazard_polygon||[]).length>=3,ready=demoVisionBaselineReady(),rpm=Number(streams.demo.lastRow?.rpm||0),running=streams.demo.active&&rpm>5,scenario=streams.demo.scenario||'normal',faultLabel={normal:'Normal',unbalance:'Unbalance',misalignment:'Misalignment',looseness:'Fastener Looseness'}[scenario]||'Waiting';setText('demoVisionViewState',running?faultLabel:'Stopped');setTone('demoVisionViewState',!running?'warn':(scenario==='normal'?'ok':'danger'));setText('demoVisionHazardState',configured?'Configured':'Not Configured');setTone('demoVisionHazardState',configured?'ok':'warn');setText('demoVisionHazardDetail',configured?'Configured':'Not Configured');setText('demoVisionHallLed',running?'Blinking':'Stopped');setTone('demoVisionHallLed',running?'ok':'warn');setText('demoVisionLedDetail',running?`blinks · RPM synchronized · ${num(rpm,0)} RPM`:'Stopped');setText('demoVisionRotor',running?'Rotating':'Stopped');setTone('demoVisionRotor',running?(scenario==='normal'?'ok':'danger'):'warn');setText('demoVisionRotorDetail',running?`${faultLabel} · ${num(rpm,0)} RPM`:'Stopped');const mountText=ready?'Normal':(configured?'Baseline Required':'Not Configured');setText('demoVisionMountSummary',mountText);setTone('demoVisionMountSummary',ready?'ok':'warn');for(const [k,id] of [['adxl345','demoVisionAdxlStatus'],['acs712','demoVisionAcsStatus'],['hall_sensor','demoVisionHallStatus']])setText(id,c.rois?.[k]?(ready?'Normal':'Baseline Required'):(k==='adxl345'?'Not Configured':'Optional'));demoVisionDrawOverlay()}
$$('.demo-vision-tool').forEach(b=>b.addEventListener('click',()=>demoVisionSetTool(b.dataset.demoVisionTool)));$('#demoVisionUndoPoint')?.addEventListener('click',demoVisionUndo);$('#demoVisionCancelEdit')?.addEventListener('click',demoVisionCancel);$('#demoVisionSaveConfig')?.addEventListener('click',demoVisionSave);$('#demoVisionCaptureBaseline')?.addEventListener('click',demoVisionBaseline);$('#demoVisionResetConfig')?.addEventListener('click',demoVisionReset);$('#demoVisionReloadConfig')?.addEventListener('click',demoVisionLoadConfig);$('#demoVisionOverlay')?.addEventListener('pointerdown',demoVisionPointerDown);$('#demoVisionOverlay')?.addEventListener('pointermove',demoVisionPointerMove);$('#demoVisionOverlay')?.addEventListener('pointerup',demoVisionPointerUp);$('#demoVisionOverlay')?.addEventListener('pointercancel',()=>{demoVisionState.dragStart=null;demoVisionState.tempRect=null;demoVisionDrawOverlay()});$('#demoVisionOverlay')?.addEventListener('contextmenu',e=>{e.preventDefault();demoVisionUndo()});window.addEventListener('resize',()=>{const active=$('.page.active')?.id;if(workspace==='demo'&&active==='vision')demoVisionDrawOverlay();if((workspace==='physical'&&active==='physical')||(workspace==='demo'&&active==='demo'))scheduleCharts(workspace,true)});

$('#resetPhysicalTwin').addEventListener('click',()=>twinEach('physical',t=>t.reset()));$('#resetDemoTwin').addEventListener('click',()=>twinEach('demo',t=>t.reset()));$('#showReference').addEventListener('click',()=>$('#referenceModal').classList.remove('hidden'));$$('[data-close-modal]').forEach(x=>x.addEventListener('click',()=>$('#referenceModal').classList.add('hidden')));$('#clearLogs').addEventListener('click',()=>{logs.length=0;renderLogs()});
function tickClock(){setText('clock',new Date().toLocaleString('en-US',{month:'2-digit',day:'2-digit',weekday:'short',hour:'2-digit',minute:'2-digit',second:'2-digit'}))}
setInterval(tickClock,1000);setInterval(updateRecordingClock,100);setInterval(()=>{if(currentUser&&workspace==='physical'&&$('.page.active')?.id==='vision'&&visionState.status?.camera_ok===true&&visionState.status?.local_preview_ready===true)visionRefreshFrame()},80);controlTimer=setInterval(()=>{if(currentUser){if(workspace==='physical'){loadControlStatus();visionRefreshStatus();}loadRecordingStatus();if($('.page.active')?.id==='recordings')loadRecordings()}},1500);tickClock();renderLogs();renderAllProbabilities();
(async()=>{
  const q=new URLSearchParams(location.search),auto=q.get('auto')==='1',requested=q.get('workspace');
  if(auto&&(requested==='physical'||requested==='demo')){await enterWorkspace(requested);return}
  try{showApp(await api('/api/me'))}catch{showWorkspaceSelector()}
})();
})();
