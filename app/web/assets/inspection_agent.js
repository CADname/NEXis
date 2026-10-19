/* NEXis AI Agent v4: main-login session; server-side API credentials only. */
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  if (!$('nexisAgentPanel')) return;
  const state = { configured:false, access:false, busy:false, lastRefresh:0, workspace:null };
  const faultNames = {normal:'Normal',unbalance:'Unbalance',misalignment:'Misalignment',looseness:'Fastener Looseness'};
  async function request(path, options={}) {
    const response = await fetch(path, {credentials:'same-origin',headers:{'Content-Type':'application/json'},...options});
    let data={};try{data=await response.json();}catch(_){}
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    return data;
  }
  function setStatus(label,ready) {
    const el=$('inspectionAgentStatus');el.textContent=label;el.classList.toggle('ready',!!ready);
  }
  function syncControls() {
    const enabled=state.configured && state.access && !state.busy;
    $('inspectionAgentSend').disabled=!enabled;
    $('inspectionAgentQuestion').disabled=!enabled;
    $('inspectionAgentSend').textContent=state.busy?'Analyzing…':'Send ↗';
    if(!state.access){ $('inspectionAgentQuestion').placeholder=state.configured?'Sign in to NEXis first':'AI agent is not configured on the server'; }
    else {$('inspectionAgentQuestion').placeholder='Ask a question about the current inspection…';}
  }
  async function refreshStatus() {
    try {
      const s=await request('/api/agent/status');
      state.configured=!!s.configured;state.access=!!s.access;state.workspace=s.workspace;
      setStatus(!s.configured?'Not configured':!s.access?'Sign-in required':s.auto_enabled?'Auto analysis enabled':'Ready for investigation',s.configured&&s.access);
    } catch (_) {state.configured=false;state.access=false;setStatus('Session unavailable',false);}
    syncControls();
  }
  // Safe Markdown subset: headings, tables, lists, paragraphs and inline emphasis.
  // Model output is never interpreted as HTML.
  function renderMarkdown(source) {
    const root=document.createElement('div');root.className='agent-md';
    const lines=String(source||'').replace(/\r\n?/g,'\n').split('\n');
    const isBlank=s=>!String(s).trim();
    const splitCells=s=>String(s).trim().replace(/^\|/,'').replace(/\|$/,'').split(/(?<!\\)\|/).map(v=>v.trim().replace(/\\\|/g,'|'));
    const divider=s=>{const c=splitCells(s);return c.length>1&&c.every(v=>/^:?-{3,}:?$/.test(v));};
    const inline=(parent,text)=>{
      const re=/(\*\*[^*\n]+\*\*|`[^`\n]+`|\*[^*\n]+\*)/g;
      let from=0,m;
      while((m=re.exec(text))){
        if(m.index>from)parent.append(document.createTextNode(text.slice(from,m.index)));
        const value=m[0],strong=value.startsWith('**'),code=value.startsWith('`');
        const el=document.createElement(strong?'strong':code?'code':'em');
        el.textContent=value.slice(strong?2:1,strong?-2:-1);parent.append(el);from=re.lastIndex;
      }
      if(from<text.length)parent.append(document.createTextNode(text.slice(from)));
    };
    const add=(tag,text,parent=root)=>{const el=document.createElement(tag);inline(el,text);parent.append(el);return el;};
    for(let i=0;i<lines.length;){
      const line=lines[i];
      if(isBlank(line)){i++;continue;}
      if(/^```/.test(line.trim())){
        const code=document.createElement('pre');const inner=document.createElement('code');const b=[];i++;
        while(i<lines.length&&!/^```/.test(lines[i].trim()))b.push(lines[i++]);
        if(i<lines.length)i++;inner.textContent=b.join('\n');code.append(inner);root.append(code);continue;
      }
      const heading=line.match(/^\s{0,3}(#{1,4})\s+(.+)$/);
      if(heading){add('h'+Math.min(4,heading[1].length+1),heading[2]);i++;continue;}
      if(i+1<lines.length&&line.includes('|')&&divider(lines[i+1])){
        const heads=splitCells(line);
        const wrap=document.createElement('div');wrap.className='agent-md-table-wrap';
        const table=document.createElement('table');table.className='agent-md-table';
        const thead=document.createElement('thead'),tr=document.createElement('tr');
        heads.forEach(t=>add('th',t,tr));thead.append(tr);table.append(thead);
        const tbody=document.createElement('tbody');i+=2;
        while(i<lines.length&&!isBlank(lines[i])&&lines[i].includes('|')){
          const cells=splitCells(lines[i]);const row=document.createElement('tr');
          heads.forEach((_,col)=>add('td',cells[col]||'',row));tbody.append(row);i++;
        }
        table.append(tbody);wrap.append(table);root.append(wrap);continue;
      }
      if(/^\s*>\s?/.test(line)){
        const quote=document.createElement('blockquote');
        while(i<lines.length&&/^\s*>\s?/.test(lines[i])){
          add('p',lines[i].replace(/^\s*>\s?/,''),quote);i++;
        }
        root.append(quote);continue;
      }
      if(/^\s*(?:[-*+]\s+|\d+[.)]\s+)/.test(line)){
        const numbered=/^\s*\d+[.)]\s+/.test(line),list=document.createElement(numbered?'ol':'ul');
        while(i<lines.length&&new RegExp(numbered?'^\\s*\\d+[.)]\\s+':'^\\s*[-*+]\\s+').test(lines[i])){
          add('li',lines[i].replace(/^\s*(?:[-*+]\s+|\d+[.)]\s+)/,''),list);i++;
        }
        root.append(list);continue;
      }
      const para=[];
      while(i<lines.length&&!isBlank(lines[i])&&!(i+1<lines.length&&lines[i].includes('|')&&divider(lines[i+1]))&&!/^\s*(?:#{1,4}\s+|[-*+]\s+|\d+[.)]\s+|>\s?|```)/.test(lines[i]))para.push(lines[i++]);
      if(para.length)add('p',para.join(' '));else{add('p',lines[i]);i++;}
    }
    return root;
  }
  function addMessage(role,text,tools=[]) {
    const el=$('inspectionAgentMessages');
    if(el.querySelector('.agent-empty'))el.replaceChildren();
    const item=document.createElement('div');item.className=`agent-message agent-${role}`;
    const who=document.createElement('small');who.textContent=role==='user'?'You':role==='error'?'Request failed':'Nemotron Ultra · '+(state.workspace==='demo'?'Recorded Demo':'Physical Station');
    const body=role==='assistant'?renderMarkdown(text):document.createElement('p');
    if(role!=='assistant')body.textContent=String(text||'');
    item.append(who,body);
    if(tools.length){const trace=document.createElement('small');trace.textContent='Evidence tools: '+[...new Set(tools)].join(' · ');item.append(trace);}
    el.append(item);while(el.children.length>30)el.firstElementChild.remove();el.scrollTop=el.scrollHeight;
  }
  function eventCard(e) {
    const card=document.createElement('div');card.className='agent-event';
    const title=document.createElement('b');title.textContent=(faultNames[e.fault]||e.fault||'Unknown')+' · '+(Number(e.confidence||0)*100).toFixed(1)+'%';
    const date=document.createElement('small');
    date.textContent=(e.created_at?new Date(e.created_at).toLocaleString('en-US'):'Unknown time')+' · '+(e.status||'Detected');
    card.append(title,date);
    if(e.summary){const summary=document.createElement('p');summary.textContent=e.summary;card.append(summary);}
    if(state.access&&state.configured){
      const button=document.createElement('button');button.className='agent-reanalyze';button.type='button';button.textContent='Reanalyze event';button.disabled=state.busy;
      button.addEventListener('click',async()=>{
        if(state.busy)return;
        state.busy=true;syncControls();button.disabled=true;
        addMessage('user','Analyze the '+(faultNames[e.fault]||e.fault)+' inspection event.');
        try {const result=await request('/api/agent/events/'+encodeURIComponent(e.id)+'/analyze',{method:'POST',body:'{}'});
          const updated=(result.events||[]).find(x=>x.id===e.id);addMessage('assistant',updated?.summary||'Event analysis completed.');await refreshEvents();
        } catch(err) {addMessage('error',err.message);}finally{state.busy=false;syncControls();}
      });card.append(button);
    }
    return card;
  }
  async function refreshEvents() {
    const el=$('inspectionAgentEvents');
    try {
      const result=await request('/api/agent/events');el.replaceChildren();
      const events=result.events||[];
      if(result.locked){const note=document.createElement('p');note.className='agent-notice';note.textContent='Sign in to NEXis to view physical inspection events.';el.append(note);return;}
      if(!events.length){const note=document.createElement('p');note.className='agent-notice';note.textContent='No physical inspection events yet. Events are created after three consecutive non-normal predictions.';el.append(note);}
      else events.forEach(e=>el.append(eventCard(e)));
    } catch(err){el.textContent='Could not load inspection history: '+err.message;}
  }
  async function submitQuestion(question) {
    if(!state.configured||!state.access||state.busy||!question.trim())return;
    state.busy=true;syncControls();addMessage('user',question);
    try {const result=await request('/api/agent/ask',{method:'POST',body:JSON.stringify({question})});
      addMessage('assistant',result.answer,result.tools_used||[]);
    } catch(err){addMessage('error',err.message);}finally{state.busy=false;syncControls();}
  }
  $('inspectionAgentForm').addEventListener('submit',e=>{e.preventDefault();const input=$('inspectionAgentQuestion');const v=input.value.trim();if(v){input.value='';submitQuestion(v);}});
  $('inspectionAgentQuestion').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();$('inspectionAgentForm').requestSubmit();}});
  document.querySelectorAll('[data-agent-prompt]').forEach(b=>b.addEventListener('click',()=>{
    $('inspectionAgentQuestion').value=b.dataset.agentPrompt;
    if(!state.access)return;
    $('inspectionAgentQuestion').focus();
  }));
  $('inspectionAgentRefresh').addEventListener('click',async()=>{await refreshStatus();await refreshEvents();});
  document.querySelectorAll('[data-page="agent"]').forEach(b=>b.addEventListener('click',()=>{
    $('pageTitle').textContent='AI Agent';$('pageSubtitle').textContent='Investigate trial inspections with NVIDIA Nemotron Ultra.';
    refreshStatus().then(refreshEvents);
  }));
  async function whenVisible(){
    const active=$('agent')?.classList.contains('active')&&!$('app')?.classList.contains('hidden');
    if(!active||Date.now()-state.lastRefresh<15000)return;
    state.lastRefresh=Date.now();await refreshStatus();await refreshEvents();
  }
  setInterval(whenVisible,15000);whenVisible();
})();
