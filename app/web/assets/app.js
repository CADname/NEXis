(()=>{
'use strict';
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const FAULT_LABELS={normal:'Normal',unbalance:'Unbalance',misalignment:'Misalignment',looseness:'Fastener Looseness'};
const SCENARIO={
  normal:{title:'Normal Operation',desc:'Replay one randomly selected recorded CSV from the normal condition.'},
  unbalance:{title:'Unbalance',desc:'Replay one randomly selected recorded CSV from the unbalance condition.'},
  misalignment:{title:'Misalignment',desc:'Replay one randomly selected recorded CSV from the misalignment condition.'},
  looseness:{title:'Fastener Looseness',desc:'Replay one randomly selected recorded CSV from the looseness condition.'}
};
const PAGE_META={
  physical:['Live Inspection','Monitor the physical ESP32 station, sensors, motor, and AI diagnosis in one view.'],
  demo:['Recorded Demo','Replay recorded CSV scenarios in real time with AI diagnosis and the digital twin.'],
  ai:['AI Diagnosis','Review the current workspace diagnosis and recent AI history.'],
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
  if(r.status===401){showLogin();throw new Error('Authentication required.');}
  if(!r.ok){let t='';try{t=(await r.json()).detail}catch{}throw new Error(t||`HTTP ${r.status}`)}
  const ct=r.headers.get('content-type')||'';return ct.includes('json')?r.json():r;
}
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=(v,d=2)=>{const n=Number(v);return Number.isFinite(n)?n.toFixed(d):'—'};
function setText(id,v){const e=$('#'+id);if(e)e.textContent=v}
function setTone(id,tone){const e=$('#'+id);if(!e)return;e.classList.remove('tone-ok','tone-warn','tone-danger','tone-info');if(tone)e.classList.add('tone-'+tone)}
function setTagTone(id,tone){const e=$('#'+id);if(!e)return;e.classList.remove('ok','warning','danger','neutral');e.classList.add(tone||'neutral')}
function showLogin(){workspace=null;document.body.classList.remove('workspace-physical','workspace-demo');$('#login').classList.remove('hidden');$('#app').classList.add('hidden')}
function applyWorkspace(kind){workspace=kind==='demo'?'demo':'physical';document.body.classList.toggle('workspace-physical',workspace==='physical');document.body.classList.toggle('workspace-demo',workspace==='demo');$$('[data-workspace-only]').forEach(el=>el.classList.toggle('workspace-hidden',el.dataset.workspaceOnly!==workspace));const src=$('#recordSource');if(src)src.value=workspace;setText('recordSourceBadge',workspace==='physical'?'PHYSICAL STATION':'RECORDED DEMO');setText('captureSourceLabel',workspace==='physical'?'Physical LIVE':'LIVE Demo');setText('sourceChip',workspace==='physical'?'PHYSICAL DEVICE LIVE':'RECORDED LIVE DEMO');const first=workspace==='physical'?'physical':'demo';setPage(first);}
function addLog(type,msg){logs.unshift({t:new Date(),type,msg});if(logs.length>200)logs.length=200;renderLogs()}
function renderLogs(){const el=$('#logList');if(!el)return;el.innerHTML=logs.length?logs.map(x=>`<div class="log-row"><time>${x.t.toLocaleTimeString()}</time><b>${esc(x.type)}</b><span>${esc(x.msg)}</span></div>`).join(''):'<div class="log-row"><time>—</time><b>SYSTEM</b><span>No events to display.</span></div>'}

function ensureTwins(){
  if(workspace==='physical'&&!twins.physical.length){['#physicalTwin','#physicalMainTwin'].forEach(sel=>{const t=window.createNEXisTwin(sel);if(t)twins.physical.push(t)})}
  if(workspace==='demo'&&!twins.demo.length){['#demoTwin','#demoMainTwin'].forEach(sel=>{const t=window.createNEXisTwin(sel);if(t)twins.demo.push(t)})}
}
function twinEach(kind,fn){for(const t of twins[kind])try{fn(t)}catch{}}
function showApp(user){
  currentUser=user;applyWorkspace(user.workspace);$('#login').classList.add('hidden');$('#app').classList.remove('hidden');setText('accountName',user.username);setText('accountRole',`${user.role.toUpperCase()} · ${workspace==='physical'?'PHYSICAL':'DEMO'}`);setText('avatar',user.role==='guest'?'G':'A');
  ensureTwins();connectWS();renderAllProbabilities();if(workspace==='physical'){setPhysicalMonitoring(false);loadControlStatus()}else{setDemoUI(null,false);loadCatalog()}loadRecordings();loadRecordingStatus();loadHistory();renderCaptureTable();addLog('SYSTEM',`${user.role==='guest'?'Guest':'Administrator'} · ${workspace==='physical'?'PHYSICAL STATION':'RECORDED DEMO'} connected`);
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
  };
}

function setPage(name){
  if((name==='physical'&&workspace!=='physical')||(name==='demo'&&workspace!=='demo'))return;
  $$('.nav-item').forEach(b=>b.classList.toggle('active',b.dataset.page===name));$$('.page').forEach(p=>p.classList.toggle('active',p.id===name));
  const meta=PAGE_META[name]||[name,''];setText('pageTitle',meta[0]);setText('pageSubtitle',meta[1]);
  if(name==='ai')loadHistory();if(name==='recordings'){loadRecordings();loadRecordingStatus();renderCaptureTable()}
  if(name==='twin')setTimeout(()=>twinEach(workspace,t=>t.resize?.()),80);
}
$$('.nav-item').forEach(b=>b.addEventListener('click',()=>setPage(b.dataset.page)));$$('[data-page-jump]').forEach(b=>b.addEventListener('click',()=>setPage(b.dataset.pageJump)));

$('#physicalLoginForm').addEventListener('submit',async e=>{e.preventDefault();try{const u=await api('/api/login',{method:'POST',body:JSON.stringify({username:$('#physicalUsername').value,password:$('#physicalPassword').value,workspace:'physical'})});setText('physicalLoginError','');showApp(u)}catch(err){setText('physicalLoginError',err.message)}});
$('#demoLoginForm').addEventListener('submit',async e=>{e.preventDefault();try{const u=await api('/api/login',{method:'POST',body:JSON.stringify({username:$('#demoUsername').value,password:$('#demoPassword').value,workspace:'demo'})});setText('demoLoginError','');showApp(u)}catch(err){setText('demoLoginError',err.message)}});
$('#guestDemoBtn').addEventListener('click',async()=>{try{const u=await api('/api/guest',{method:'POST'});setText('demoLoginError','');showApp(u)}catch(err){setText('demoLoginError',err.message)}});
$('#logoutBtn').addEventListener('click',async()=>{try{await api('/api/logout',{method:'POST'})}catch{}if(ws)ws.close();if(heartbeat)clearInterval(heartbeat);currentUser=null;showLogin()});

function clearStream(kind){
  const s=streams[kind];s.buffer=blankBuffer();s.fft={freq:[],amp:[],dominant:0};s.sampleCounter=0;s.lastTelemetryAt=null;s.lastPred=null;s.recentRows.length=0;
  if(kind==='physical'){renderProb('pProbabilities',null);setText('pDiagnosis','Waiting for operating conditions');setText('pDiagnosisText','Sensors remain live at 0 RPM; only AI inference is paused.');}
  else{renderProb('dProbabilities',null);setText('dDiagnosis','Waiting for analysis');setText('dDiagnosisText','Diagnosis starts after 256 samples are collected.');}
  scheduleCharts(kind,true);renderCaptureTable();
}
function setPhysicalMonitoring(active){
  const s=streams.physical;s.monitoring=!!active;setText('pMonitorState',active?'RUNNING':'STOPPED');setTone('pMonitorState',active?'ok':'warn');setText('ovPhysicalMonitoring',active?'Monitoring':'Stopped');
  $('#physicalMonitorStart').disabled=active;$('#physicalMonitorStop').disabled=!active;
  if(active){clearStream('physical');addLog('PHYSICAL','Physical monitoring started · sensor telemetry remains visible from 0 RPM')}else addLog('PHYSICAL','Physical screen monitoring stopped · MQTT reception and motor control remain active');
}
$('#physicalMonitorStart').addEventListener('click',()=>setPhysicalMonitoring(true));$('#physicalMonitorStop').addEventListener('click',()=>setPhysicalMonitoring(false));

async function startDemo(state){
  try{clearStream('demo');streams.demo.monitoring=true;const r=await api('/api/replay/start',{method:'POST',body:JSON.stringify({state,speed:1,loop:false})});setDemoUI(state,true);addLog('DEMO',`${FAULT_LABELS[state]} started · ${r.selected_from} recorded CSV files available; one selected at random`)}
  catch(e){streams.demo.monitoring=false;setDemoUI(state,false);addLog('ERROR',e.message);alert(e.message)}
}
async function stopDemo(){try{await api('/api/replay/stop',{method:'POST'})}catch{}setDemoUI(streams.demo.scenario,false);addLog('DEMO','Recorded demo stopped')}
$$('[data-demo-scenario]').forEach(b=>b.addEventListener('click',()=>startDemo(b.dataset.demoScenario)));$('#demoStop').addEventListener('click',stopDemo);
function setDemoUI(state,active,complete=false){
  const s=streams.demo;if(state)s.scenario=state;s.active=!!active;s.monitoring=!!active;
  const info=SCENARIO[s.scenario]||{title:'Waiting for scenario',desc:'Select a condition.'};setText('demoScenarioTitle',active?`${info.title} · replaying`:(complete?`${info.title} · complete`:'Waiting for scenario'));setText('demoScenarioDesc',active?info.desc:'Select a condition and the server will randomly choose one recorded CSV from that class.');setText('dMonitorState',active?'RUNNING':(complete?'COMPLETE':'READY'));setTone('dMonitorState',active?'ok':(complete?'info':'warn'));setText('dScenario',s.scenario?FAULT_LABELS[s.scenario]:'—');setText('ovDemoScenario',active?FAULT_LABELS[s.scenario]:(complete?'COMPLETE':'READY'));setText('dMetricScenario',s.scenario?FAULT_LABELS[s.scenario]:'—');
  setText('dTwinState',active?`${FAULT_LABELS[s.scenario]} · · replaying`:(complete?`${FAULT_LABELS[s.scenario]} · · complete`:'Waiting for scenario'));setText('ovDemoTwinState',active?`${FAULT_LABELS[s.scenario]} · · replaying`:'Waiting for scenario');setText('twinDemoState',active?`${FAULT_LABELS[s.scenario]} · · replaying`:'Waiting for scenario');
  $('#demoStop').disabled=!active;$$('[data-demo-scenario]').forEach(b=>b.classList.toggle('running',active&&b.dataset.demoScenario===s.scenario));
  twinEach('demo',t=>t.setScenario(s.scenario||'normal',active));
  const chip=$('#ovDemoChip');if(chip){chip.textContent=active?'DEMO RUNNING':(complete?'DEMO COMPLETE':'DEMO READY');chip.classList.toggle('online',active);chip.classList.toggle('offline',!active)}
  const tchip=$('#twinDemoChip');if(tchip){tchip.textContent=active?'RUNNING':'READY';tchip.classList.toggle('online',active);tchip.classList.toggle('offline',!active)}
}

function push(s,name,v,max=256){s.buffer[name].push(Number(v)||0);if(s.buffer[name].length>max)s.buffer[name].shift()}
function stats(a){if(!a.length)return{rms:0,ptp:0};const mn=Math.min(...a),mx=Math.max(...a);return{rms:Math.sqrt(a.reduce((z,v)=>z+v*v,0)/a.length),ptp:mx-mn}}
function computeFFT(a,fs=100){const n=Math.min(256,a.length);if(n<32)return{freq:[],amp:[],dominant:0};const x=a.slice(-n),mean=x.reduce((z,v)=>z+v,0)/n,freq=[],amp=[];let best=0,bestF=0;for(let k=1;k<=Math.floor(n/2);k++){let re=0,im=0;for(let j=0;j<n;j++){const w=.5-.5*Math.cos(2*Math.PI*j/(n-1)),v=(x[j]-mean)*w,ang=2*Math.PI*k*j/n;re+=v*Math.cos(ang);im-=v*Math.sin(ang)}const mag=Math.hypot(re,im)/n*2,f=k*fs/n;freq.push(f);amp.push(mag);if(mag>best){best=mag;bestF=f}}return{freq,amp,dominant:bestF}}
function routeTelemetry(m){const kind=m.stream||(m.row?.source==='esp32'?'physical':'demo');if(!streams[kind]||kind!==workspace)return;renderTelemetry(kind,m)}
function renderTelemetry(kind,m){
  const s=streams[kind],r=m.row||{};s.lastRow=r;s.lastTelemetryAt=new Date();
  if(kind==='physical'){
    twinEach('physical',t=>t.setTelemetry(r));setText('ovPhysicalRpm',`${num(r.rpm,0)} rpm`);setText('ovPhysicalCurrent',`${num(r.current_a,3)} A`);setText('ovPhysicalPwm',num(r.pwm_eq,2));setText('ovPhysicalUpdate',`Last telemetry ${s.lastTelemetryAt.toLocaleTimeString()}`);setText('pTwinState',Number(r.rpm)>5?`Physical ${num(r.rpm,0)} RPM`:'Physical Station Stopped');setText('ovPhysicalTwinState',Number(r.rpm)>5?`${num(r.rpm,0)} RPM synchronized`:'Physical Station Stopped');setText('twinPhysicalState',Number(r.rpm)>5?`Live ${num(r.rpm,0)} RPM`:'Physical Station Stopped');
  }else{
    twinEach('demo',t=>t.setTelemetry(r));setText('ovDemoRpm',`${num(r.rpm,0)} rpm`);setText('ovDemoCurrent',`${num(r.current_a,3)} A`);setText('ovDemoUpdate',`Last demo sample ${s.lastTelemetryAt.toLocaleTimeString()}`);setText('dTwinState',`${FAULT_LABELS[s.scenario]||'Demo'} · ${num(r.rpm,0)} RPM`);setText('ovDemoTwinState',`${FAULT_LABELS[s.scenario]||'Demo'} · ${num(r.rpm,0)} RPM`);setText('twinDemoState',`${FAULT_LABELS[s.scenario]||'Demo'} · ${num(r.rpm,0)} RPM`);
  }
  // AI/Twin state is always current. Recent raw rows are kept for source-filtered recording preview.
  handlePrediction(kind,m);
  s.recentRows.unshift(r);if(s.recentRows.length>14)s.recentRows.length=14;
  if($('.page.active')?.id==='recordings')renderCaptureTable();
  // Physical chart/sample counting starts only when the operator presses 'Start Physical Monitoring'.
  if(!s.monitoring && kind==='physical')return;
  s.sampleCounter++;push(s,'x',r.ax_g);push(s,'y',r.ay_g);push(s,'z',r.az_g);push(s,'total',r.total_g);push(s,'current',r.current_a);push(s,'rpm',r.rpm);if(s.sampleCounter%16===0)s.fft=computeFFT(s.buffer.total,100);
  renderMetrics(kind,r);scheduleCharts(kind);
}
function renderMetrics(kind,r){
  const s=streams[kind],st=stats(s.buffer.total),time=s.lastTelemetryAt?s.lastTelemetryAt.toLocaleTimeString():'—';
  if(kind==='physical'){
    setText('pSamples',String(s.sampleCounter));setText('ovPhysicalSamples',String(s.sampleCounter));setText('pLastUpdate',time);setText('pTotal',`${num(r.total_g,4)} g`);setText('pRms',st.rms.toFixed(4));setText('pPtp',`${st.ptp.toFixed(4)} g`);setText('pCurrent',num(r.current_a,3));setText('pRpm',num(r.rpm,0));setText('pTargetRpm',`${num(r.target_rpm,0)} rpm`);setText('pRpmError',`${num(r.rpm_error,1)} rpm`);setText('pPwm',num(r.pwm_eq,2));setText('pDuty',`${num(r.duty_10bit,0)} / 1023`);setText('pAcs',`${num(r.acs_v,3)} V`);setText('pMode',r.control_mode||'—');setText('pDominantFreq',`${s.fft.dominant.toFixed(2)} Hz`);
  }else{
    setText('dSamples',String(s.sampleCounter));setText('ovDemoSamples',String(s.sampleCounter));setText('dLastUpdate',time);setText('dTotal',`${num(r.total_g,4)} g`);setText('dRms',st.rms.toFixed(4));setText('ovDemoRms',`${st.rms.toFixed(4)} g`);setText('dPtp',`${st.ptp.toFixed(4)} g`);setText('dCurrent',num(r.current_a,3));setText('dRpm',num(r.rpm,0));setText('dDominantFreq',`${s.fft.dominant.toFixed(2)} Hz`);
  }
}
function handlePrediction(kind,m){
  const s=streams[kind];
  if(m.prediction&&!m.prediction.error){s.lastPred=m.prediction;const label=m.prediction.pred_label_name,conf=Number(m.prediction.top_prob||0);twinEach(kind,t=>t.setDiagnosis(label));
    if(kind==='physical'){renderProb('pProbabilities',m.prediction.probabilities);setText('pDiagnosis',FAULT_LABELS[label]||label);setTone('pDiagnosis',label==='normal'?'ok':'danger');setText('pDiagnosisText',`Confidence ${(conf*100).toFixed(1)}%`);setText('pAiState','ACTIVE');setTagTone('pAiState',label==='normal'?'ok':'danger');setText('pAiGate','ACTIVE');setTone('pAiGate','ok');setText('ovPhysicalAi',FAULT_LABELS[label]||label);setText('aiPhysicalDiagnosis',FAULT_LABELS[label]||label);setText('aiPhysicalConfidence',`${(conf*100).toFixed(1)}%`);setText('aiPhysicalText','Diagnosis from the live physical sensor window');}
    else{renderProb('dProbabilities',m.prediction.probabilities);setText('dDiagnosis',FAULT_LABELS[label]||label);setTone('dDiagnosis',label==='normal'?'ok':'danger');setText('dDiagnosisText',`Confidence ${(conf*100).toFixed(1)}%`);setText('dAiState','ACTIVE');setTagTone('dAiState',label==='normal'?'ok':'danger');setText('ovDemoAi',FAULT_LABELS[label]||label);setText('aiDemoDiagnosis',FAULT_LABELS[label]||label);setText('aiDemoConfidence',`${(conf*100).toFixed(1)}%`);setText('aiDemoText',`${FAULT_LABELS[streams.demo.scenario]||'Demo'} replay window-based diagnosis`);}
    const now=Date.now();if(now-historyTimer>2500){historyTimer=now;loadHistory()}
  }else if(kind==='physical'&&m.ai_eligible===false){s.lastPred=null;renderProb('pProbabilities',null);setText('pDiagnosis','Waiting for operating conditions');setTone('pDiagnosis','warn');setText('pDiagnosisText',`Sensors are live. AI starts above 70% of target RPM (minimum ${num(m.ai_min_rpm,0)} RPM).`);setText('pAiState','WAIT');setTagTone('pAiState','warning');setText('pAiGate','WAIT');setTone('pAiGate','warn');setText('ovPhysicalAi','Waiting for operating conditions');setText('aiPhysicalDiagnosis','Waiting for operating conditions');setText('aiPhysicalConfidence','—');setText('aiPhysicalText','Stopped and low-speed data are excluded from the Physical AI window');}
}
function renderProb(id,probs){const el=$('#'+id);if(!el)return;const p=probs||{normal:0,unbalance:0,misalignment:0,looseness:0};el.innerHTML=['normal','unbalance','misalignment','looseness'].map(k=>{const v=Math.max(0,Math.min(1,Number(p[k])||0));return `<div class="prob-row"><span>${FAULT_LABELS[k]}</span><div class="prob-bar"><i style="width:${(v*100).toFixed(1)}%"></i></div><b>${(v*100).toFixed(1)}%</b></div>`}).join('')}
function renderAllProbabilities(){renderProb('pProbabilities',null);renderProb('dProbabilities',null)}

function scheduleCharts(kind,force=false){const s=streams[kind];if(s.chartPending&&!force)return;s.chartPending=true;requestAnimationFrame(()=>{s.chartPending=false;const pre=kind==='physical'?'p':'d';drawWave($('#'+pre+'WaveChart'),[s.buffer.x,s.buffer.y,s.buffer.z],kind==='physical'?'Start physical monitoring to display the signal.':'Start the recorded demo to display the signal.');drawFFT($('#'+pre+'FftChart'),s.fft)})}
function canvasPrep(c){const d=Math.min(devicePixelRatio||1,2),w=Math.max(1,c.clientWidth),h=Math.max(1,c.clientHeight);if(c.width!==Math.floor(w*d)||c.height!==Math.floor(h*d)){c.width=Math.floor(w*d);c.height=Math.floor(h*d)}const x=c.getContext('2d');x.setTransform(d,0,0,d,0,0);return{x,w,h}}
function drawGrid(x,w,h){x.strokeStyle='rgba(100,145,180,.14)';x.lineWidth=1;for(let i=1;i<5;i++){x.beginPath();x.moveTo(0,h*i/5);x.lineTo(w,h*i/5);x.stroke()}for(let i=1;i<8;i++){x.beginPath();x.moveTo(w*i/8,0);x.lineTo(w*i/8,h);x.stroke()}}
function drawWave(c,sets,emptyText){if(!c)return;const {x,w,h}=canvasPrep(c);x.clearRect(0,0,w,h);drawGrid(x,w,h);const all=sets.flat();if(!all.length){x.fillStyle='#66829a';x.font='11px sans-serif';x.fillText(emptyText,14,24);return}let mn=Math.min(...all),mx=Math.max(...all);if(mx-mn<.001){mx+=.5;mn-=.5}const pad=(mx-mn)*.12;mn-=pad;mx+=pad;const colors=['#4a96ff','#21d69a','#ff9b52'];sets.forEach((a,j)=>{if(a.length<2)return;x.strokeStyle=colors[j];x.lineWidth=1.3;x.beginPath();a.forEach((v,i)=>{const px=i/Math.max(1,a.length-1)*w,py=h-(v-mn)/(mx-mn)*h;i?x.lineTo(px,py):x.moveTo(px,py)});x.stroke()})}
function drawFFT(c,data){if(!c)return;const {x,w,h}=canvasPrep(c);x.clearRect(0,0,w,h);drawGrid(x,w,h);if(!data.amp.length){x.fillStyle='#66829a';x.font='11px sans-serif';x.fillText('Waiting for FFT data',14,24);return}const max=Math.max(...data.amp,1e-6);x.strokeStyle='#37c9ff';x.fillStyle='rgba(55,201,255,.18)';x.lineWidth=1.5;x.beginPath();data.amp.forEach((v,i)=>{const px=i/Math.max(1,data.amp.length-1)*w,py=h-v/max*(h-16);i?x.lineTo(px,py):x.moveTo(px,py)});x.stroke();x.lineTo(w,h);x.lineTo(0,h);x.closePath();x.fill()}

function renderControlStatus(c){
  if(workspace!=='physical')return;const dev=c.device||{},online=!!c.edge_online,local=dev.remote_enabled===true,row=streams.physical.lastRow||{};
  setText('ctrlEdge',online?'ONLINE':'OFFLINE');setText('pLinkState',online?'ONLINE':'OFFLINE');setTone('pLinkState',online?'ok':'danger');setText('ctrlMode',dev.control_mode||row.control_mode||'IDLE');setText('ctrlActual',`${num(dev.rpm??row.rpm,0)} RPM`);setText('ctrlTarget',`${num(dev.target_rpm??row.target_rpm,0)} RPM`);setText('ctrlRpmError',`Error ${num(row.rpm_error,1)} RPM`);setText('ctrlPwm',num(row.pwm_eq,2));setText('ctrlDuty',`Duty ${num(row.duty_10bit,0)} / 1023`);setText('ctrlCurrent',`${num(row.current_a,3)} A`);setText('ctrlAcs',`ACS ${num(row.acs_v,3)} V`);setText('ctrlLastSeen',online?'Heartbeat healthy':'Waiting for heartbeat');
  const chip=$('#ctrlEdgeChip');if(chip){chip.textContent=online?'ESP32 ONLINE':'ESP32 OFFLINE';chip.classList.toggle('online',online);chip.classList.toggle('offline',!online)}
  const admin=currentUser?.role==='admin';$('#ctrlStartBtn').disabled=!admin||!online||!local;$('#ctrlStopBtn').disabled=!admin;
  if(!admin)setText('ctrlMessage','Only administrators can control the physical station.');else if(!online)setText('ctrlMessage','Start/stop becomes available when the ESP32 connects to AWS.');else if(!local)setText('ctrlMessage','Check ESP32 remote command reception.');else setText('ctrlMessage','Enter a target RPM and press Start Motor. Stop can be sent at any time.');
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

$('#resetPhysicalTwin').addEventListener('click',()=>twinEach('physical',t=>t.reset()));$('#resetDemoTwin').addEventListener('click',()=>twinEach('demo',t=>t.reset()));$('#showReference').addEventListener('click',()=>$('#referenceModal').classList.remove('hidden'));$$('[data-close-modal]').forEach(x=>x.addEventListener('click',()=>$('#referenceModal').classList.add('hidden')));$('#clearLogs').addEventListener('click',()=>{logs.length=0;renderLogs()});
function tickClock(){setText('clock',new Date().toLocaleString('en-US',{month:'2-digit',day:'2-digit',weekday:'short',hour:'2-digit',minute:'2-digit',second:'2-digit'}))}
setInterval(tickClock,1000);setInterval(updateRecordingClock,100);controlTimer=setInterval(()=>{if(currentUser){if(workspace==='physical')loadControlStatus();loadRecordingStatus();if($('.page.active')?.id==='recordings')loadRecordings()}},1500);tickClock();renderLogs();renderAllProbabilities();api('/api/me').then(showApp).catch(showLogin);
})();
