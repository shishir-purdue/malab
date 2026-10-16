'use strict';
const $=id=>document.getElementById(id), colors=['#087c82','#7963aa','#b08339','#477eaa'];
let state=null, received=0, pendingRequest=null, lastEvents='', posting=false;
const volts=v=>v==null?'—':(v>=0?'+':'')+v.toFixed(5);
const age=(at,now)=>at==null?Infinity:Math.max(0,now-at);
const ago=seconds=>!Number.isFinite(seconds)?'not yet':seconds<1?'just now':seconds.toFixed(1)+' s ago';
for(let ch=1;ch<=4;ch++){
 const card=document.createElement('article');card.className='card';card.setAttribute('aria-label',`DAC ${ch}`);
 card.innerHTML=`<div class="card-head"><div class="channel-name"><span class="channel-color"></span>DAC ${ch}</div><span class="tag" id="cal-${ch}">Calibration unknown</span></div><div class="voltage" id="voltage-${ch}">— <small>V</small></div><div class="source" id="source-${ch}">Awaiting readback</div><form class="channel-controls" id="form-${ch}"><div class="input-row"><label>Target · V<input id="target-${ch}" aria-label="DAC ${ch} target voltage" type="number" step="any" min="-10" max="10" value="0" required></label><label>Ramp · V/s<input id="speed-${ch}" aria-label="DAC ${ch} ramp speed" type="number" step="any" min="0.000001" value="0.1" required></label></div><div class="card-buttons"><button type="button" id="set-${ch}" aria-label="Set DAC ${ch}">Set voltage</button><button type="submit" id="ramp-${ch}" class="primary" aria-label="Ramp DAC ${ch}">Ramp</button></div><div class="limits" id="limits-${ch}">Waiting for channel limits</div></form>`;
 $('channels').append(card);card.classList.add('channel-'+ch);
 $(`set-${ch}`).onclick=()=>channelAction(ch,'set');
 $(`form-${ch}`).onsubmit=e=>{e.preventDefault();channelAction(ch,'ramp');};
}
function message(text,error=false){$('action-message').textContent=text;$('action-message').className=error?'error':'';}
function channelAction(ch,action){
 const target=$(`target-${ch}`), speed=$(`speed-${ch}`);
 if(!target.reportValidity()||(action==='ramp'&&!speed.reportValidity()))return;
 send({action,channel:ch,voltage:Number(target.value),speed:Number(speed.value),step_size:10});
}
for(const b of document.querySelectorAll('[data-action]'))b.onclick=()=>send({action:b.dataset.action});
async function send(data){
 if(posting)return;
 const request_id=crypto.randomUUID();posting=true;pendingRequest=request_id;
 message('Sending '+data.action.replaceAll('_',' ')+'…');render();
 try{
  const response=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json','X-DAC-Token':document.querySelector('meta[name="dac-token"]').content},body:JSON.stringify({...data,request_id}),signal:AbortSignal.timeout(6000)});
  const result=await response.json();if(!response.ok)throw new Error(result.error||'Command rejected');
 }catch(error){message(error.name==='TimeoutError'?'Action response timed out. Outcome unknown; check outputs before retrying.':error.message,true);pendingRequest=null;}
 finally{posting=false;render();}
}
async function poll(){
 try{
  const response=await fetch('/api/state',{signal:AbortSignal.timeout(2000)});
  if(!response.ok)throw new Error('Local server did not respond');
  state=await response.json();received=performance.now();
  if(pendingRequest){const job=state.jobs[pendingRequest];if(job&&job.state!=='pending'){
   message(job.state==='failed'?job.error:job.action==='ramp'?'Ramp started. Watch the device values and meter below.':job.action==='safe_zero'?'SAFE ZERO started on all four channels at ≤0.01 V/s.':job.action==='connect'?'Connection requested; waiting for a successful device response.':job.action==='network'?'Network reset requested; outputs held while reconnecting.':job.action.toUpperCase()+' complete.',job.state==='failed');pendingRequest=null;
  }}
  render();drawTrace();
 }catch(error){render();}
 setTimeout(poll,250);
}
function render(){
 const serverFresh=state&&performance.now()-received<2500;
 $('server-alert').hidden=!!serverFresh&&!state.device_error;
 $('server-alert').textContent=serverFresh&&state.device_error?state.device_error:state?'Local dashboard connection lost. Values below are stale; no commands have been replayed.':'Connecting to the local dashboard…';
 if(!state)return;
 const now=state.now+(performance.now()-received)/1000,n=state.network,r=state.recovery;
 const networkFresh=serverFresh&&n.state==='good'&&age(n.last_ok,now)<2.5;
 const labels={good:'Network good',connecting:'Connecting',failed:'Network unavailable',disconnected:'Disconnected',suspended:'Network paused · safe zero'};
 $('network-label').textContent=!serverFresh?'Dashboard offline':n.state==='good'&&!networkFresh?'Response overdue':labels[n.state]||n.state;
 $('network').className='signal '+(networkFresh?'good':['connecting','suspended','disconnected'].includes(n.state)&&serverFresh?'amber':'bad');
 $('network-detail').textContent=`Last DAC response ${ago(age(n.last_ok,now))}`+(networkFresh?` · ${n.latency_ms} ms`:n.error?' · '+n.error:'');
 const busy=state.ramp.state==='RUNNING',safe=r.state==='ACTIVE',latched=['LATCHED','FAILED'].includes(r.state);
 $('operation').textContent=safe?'Safe zero running':r.state==='FAILED'?'Safe zero failed':latched?'At zero · latched':busy?`Ramping DAC ${state.ramp.channel}`:state.ramp.state==='ABORTED'?'Ramp stopped':networkFresh?'Ready':'Waiting for connection';
 $('operation').className='operation '+(safe||busy?'busy':'');
 const pending=posting||!!state.pending||!!pendingRequest;
 for(const c of state.channels){
  const ch=c.channel,fresh=serverFresh&&age(c.at,now)<2.5&&(networkFresh||safe||latched);
  $(`voltage-${ch}`).innerHTML=`${volts(c.voltage)} <small>V</small>`;$(`voltage-${ch}`).className='voltage'+(!fresh?' stale':'');
  $(`source-${ch}`).textContent=c.voltage==null?'Unknown · no valid device value':(!fresh?'Stale · last value ':c.source==='write'?'Device value · last write · ':'Readback · ')+ago(age(c.at,now));
  $(`source-${ch}`).className='source'+(!fresh?' stale':'');
  $(`cal-${ch}`).textContent=c.limits?(c.calibrated?'Calibrated':'Nominal'):'Unknown';$(`cal-${ch}`).className='tag'+(c.calibrated?' measured':'');
  $(`limits-${ch}`).textContent=c.limits?`${c.limits[0].toFixed(5)} to +${c.limits[1].toFixed(5)} V`:'Waiting for channel limits';
  if(c.limits){$(`target-${ch}`).min=c.limits[0];$(`target-${ch}`).max=c.limits[1];}
  for(const action of ['set','ramp'])$(`${action}-${ch}`).disabled=pending||!networkFresh||busy||safe||latched;
 }
 $('connect').disabled=pending||networkFresh||safe||latched;
 $('disconnect').disabled=pending||!networkFresh;
 $('initialize').disabled=pending||!networkFresh||busy||safe||latched;
 $('abort').disabled=pending||!busy||!serverFresh;
 $('network-reset').disabled=pending||safe||!serverFresh||r.state==='unavailable';
 $('safe-zero').disabled=pending||safe||!serverFresh||r.state==='unavailable';
 const m=state.meter,mFresh=serverFresh&&m.state==='good'&&age(m.at,now)<2.5,c=state.channels[0];
 $('meter-voltage').innerHTML=`${m.voltage==null?'—':(m.voltage>=0?'+':'')+m.voltage.toFixed(6)} <small>V</small>`;
 $('meter-voltage').className='meter-value'+(mFresh?'':' stale');
 $('meter-status').textContent=mFresh?'Live':m.voltage==null?'Unavailable':'Stale';
 $('meter-age').textContent=`192.168.1.71 · ${ago(age(m.at,now))}`+(m.error?' · '+m.error:'');
 const paired=mFresh&&networkFresh&&age(c.at,now)<2.5&&c.voltage!=null&&!busy&&!safe;
 const difference=paired?(m.voltage-c.voltage)*1000:null;
 $('meter-difference').textContent=difference==null?'—':(difference>=0?'+':'')+difference.toFixed(3)+' mV';
 $('accuracy').textContent=paired?(Math.abs(difference)<=.5?'Within ±0.5 mV':'Outside ±0.5 mV'):busy||safe?'Tracking ramp · samples are not simultaneous':'Waiting for fresh paired readings';
 $('accuracy').className='accuracy '+(paired?(Math.abs(difference)<=.5?'pass':'fail'):'');
 $('usb-state').textContent='USB recovery · '+r.state.toLowerCase();$('usb-dot').className='dot '+(r.state==='unavailable'||r.state==='FAILED'?'bad':'good');
 const events=JSON.stringify(state.events);if(events!==lastEvents){lastEvents=events;$('events').replaceChildren();for(const e of state.events){const li=document.createElement('li');li.className=e.level;const t=document.createElement('time');t.textContent=new Date(e.at*1000).toLocaleTimeString();li.append(t,document.createTextNode(e.message));$('events').append(li);}}
 $('updated').textContent=serverFresh?'Live · '+new Date(state.now*1000).toLocaleTimeString():'Updates stopped';
}
function drawTrace(){
 if(!state)return;const now=state.now,h=state.history.filter(p=>p.at>=now-60);if(!h.length)return;
 const values=h.flatMap(p=>[...p.channels,p.meter]).filter(v=>v!=null);let min=Math.min(0,...values),max=Math.max(0,...values);const pad=Math.max(.005,(max-min)*.12);min-=pad;max+=pad;
 const x=t=>55+(t-(now-60))/60*770,y=v=>190-(v-min)/(max-min)*170;
 let svg='';for(let i=0;i<5;i++){const v=min+(max-min)*i/4,yy=y(v);svg+=`<line x1="55" x2="825" y1="${yy}" y2="${yy}" stroke="#e9eeee"/><text x="43" y="${yy+4}" text-anchor="end" fill="#829398" font-size="10">${v.toFixed(3)}</text>`;}
 for(let i=0;i<5;i++){
  let path='',open=false;for(const p of h){const v=i<4?p.channels[i]:p.meter;if(v==null){open=false;continue;}path+=(open?'L':'M')+x(p.at).toFixed(1)+','+y(v).toFixed(1)+' ';open=true;}
  svg+=`<path d="${path}" fill="none" stroke="${i<4?colors[i]:'#263b42'}" stroke-width="${i<4?1.6:1.2}" ${i===4?'stroke-dasharray="4 3"':''}/>`;
 }
 svg+='<text x="55" y="215" fill="#829398" font-size="10">−60 s</text><text x="825" y="215" text-anchor="end" fill="#829398" font-size="10">Now</text>';
 $('trace').innerHTML=svg;
}
setInterval(render,250);poll();
