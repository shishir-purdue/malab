'use strict';
const $=id=>document.getElementById(id),colors=['#087c82','#7963aa','#b08339','#477eaa'];
let state=null,received=0,layout='',session=null,lastEvents='',traceKey='',hadResistors=false;
const modes=new Map();
const pending=new Map(),posting=new Set();
const volts=v=>v==null||!Number.isFinite(v)?'—':(v>=0?'+':'')+(v!==0&&(Math.abs(v)<.00001||Math.abs(v)>=1e6)?v.toExponential(4):v.toFixed(5));
const age=(at,now)=>at==null?Infinity:Math.max(0,now-at);
const ago=s=>!Number.isFinite(s)?'not yet':s<1?'just now':s.toFixed(1)+' s ago';
const color=ch=>colors[(ch-1)%4];
const channelName=c=>c?.label?`${c.label} (DAC ${c.channel})`:`DAC ${c?.channel??'?'}`;
function message(unit,text,error=false){const el=$(`message-${unit}`);if(el){el.textContent=text;el.className='unit-message'+(error?' error':'');}}
function build(){
 const key=JSON.stringify(state.units.map(u=>[u.unit,u.address]));if(key===layout)return;layout=key;
 $('units').replaceChildren();$('legend').replaceChildren();
 for(const u of state.units){
  const section=document.createElement('section');section.className='unit';section.setAttribute('aria-label',`DAC unit ${u.unit}`);
  section.innerHTML=`<div class="unit-head"><div><h2>Unit ${u.unit} <span class="unit-range">DAC ${u.first_channel}–${u.last_channel}</span></h2><p id="address-${u.unit}" class="caption"></p></div><div class="unit-health"><div id="network-${u.unit}" class="signal amber" role="status"><span class="dot"></span><strong id="network-label-${u.unit}">Connecting</strong></div><div id="network-detail-${u.unit}" class="caption"></div></div></div><div class="toolbar"><div class="toolbar-left"><span id="operation-${u.unit}" class="operation">Waiting</span><button id="connect-${u.unit}">Connect</button><button id="disconnect-${u.unit}">Disconnect</button><button id="initialize-${u.unit}">Initialize unit</button></div><div class="toolbar-right"><button id="abort-${u.unit}">Stop ramp</button><button id="network-reset-${u.unit}">Reset network · unit ${u.unit}</button><button id="safe-zero-${u.unit}" class="danger" title="Ramp this unit to its stored zero at up to 0.02 V/s">Safe zero · DAC ${u.first_channel}–${u.last_channel}</button></div></div><div class="channels" id="channels-${u.unit}"></div><div class="unit-foot"><div id="message-${u.unit}" class="unit-message" role="status">Connecting only reads values. Set and Ramp prepare their selected output.</div><div id="usb-${u.unit}" class="usb"></div></div>`;
  $('units').append(section);$(`address-${u.unit}`).textContent=u.address+' · four physical channels';
  for(const [id,action] of [['connect','connect'],['disconnect','disconnect'],['initialize','initialize'],['abort','abort'],['network-reset','network'],['safe-zero','safe_zero']])
   $(`${id}-${u.unit}`).onclick=()=>send(u.unit,{action,unit:u.unit});
  for(const c of state.channels.filter(c=>c.unit===u.unit)){
   const ch=c.channel,card=document.createElement('article');card.className='card channel-'+c.local_channel;card.id=`card-${ch}`;card.setAttribute('aria-label',`DAC ${ch}`);
   card.innerHTML=`<div class="card-head"><div class="channel-name"><span class="channel-color"></span><span id="channel-label-${ch}">DAC ${ch}</span></div><span class="tag" id="cal-${ch}">Unknown</span></div><div class="channel-identity"><div class="local-channel">DAC ${ch} · Unit ${u.unit} · local ${c.local_channel}</div><button type="button" class="rename-channel" id="rename-${ch}" aria-label="Rename DAC ${ch}">Rename</button></div><form id="label-form-${ch}" class="label-editor" hidden><label>Channel label<input type="text" maxlength="80" id="label-input-${ch}" aria-label="DAC ${ch} label" placeholder="e.g. Bias coil"></label><div class="card-buttons"><button type="submit" id="save-label-${ch}">Save name</button><button type="button" id="clear-label-${ch}">Reset</button><button type="button" id="cancel-label-${ch}">Cancel</button></div></form><div class="voltage" id="voltage-${ch}">— <small>V</small></div><div class="secondary-reading" id="secondary-${ch}" hidden></div><div class="source" id="source-${ch}">Awaiting readback</div><form class="channel-controls" id="form-${ch}"><div class="input-row"><label><span id="target-label-${ch}">Target · V</span><input id="target-${ch}" aria-label="DAC ${ch} target voltage" type="number" step="any" min="-10" max="10" value="0" required></label><label><span id="speed-label-${ch}">Ramp · V/s</span><input id="speed-${ch}" aria-label="DAC ${ch} ramp speed" type="number" step="any" min="0" value="0.1" required></label></div><div class="card-buttons"><button type="button" id="set-${ch}">Set voltage</button><button type="submit" id="ramp-${ch}" class="primary">Ramp</button></div><div class="limits" id="limits-${ch}"></div></form><details class="resistor-controls" id="resistor-details-${ch}"><summary id="resistor-summary-${ch}">Add resistor</summary><label>Resistance · Ω<input id="resistor-${ch}" aria-label="DAC ${ch} resistance in ohms" type="number" min="0" step="any" placeholder="e.g. 1000"></label><div class="card-buttons"><button type="button" id="save-resistor-${ch}">Save resistor</button><button type="button" id="remove-resistor-${ch}">Remove</button></div><p>Use the total load resistance. I = V / R is calculated. Saving leaves the output unchanged.</p></details>`;
   $(`channels-${u.unit}`).append(card);
   $(`rename-${ch}`).onclick=()=>{const latest=state.channels.find(row=>row.channel===ch);$(`label-input-${ch}`).value=latest.label||'';$(`label-form-${ch}`).hidden=false;$(`label-input-${ch}`).focus();};
   $(`label-form-${ch}`).onsubmit=e=>{e.preventDefault();const input=$(`label-input-${ch}`);if(input.reportValidity())send(c.unit,{action:'label',unit:c.unit,channel:ch,label:input.value});};
   $(`clear-label-${ch}`).onclick=()=>send(c.unit,{action:'label',unit:c.unit,channel:ch,label:''});
   $(`cancel-label-${ch}`).onclick=()=>{$(`label-form-${ch}`).hidden=true;};
   $(`set-${ch}`).onclick=()=>channelAction(ch,'set');$(`form-${ch}`).onsubmit=e=>{e.preventDefault();channelAction(ch,'ramp');};
   $(`save-resistor-${ch}`).onclick=()=>{const input=$(`resistor-${ch}`);input.setCustomValidity('');if(!input.value||!Number.isFinite(Number(input.value))||Number(input.value)<=0)input.setCustomValidity('Enter a finite resistance greater than zero.');if(input.reportValidity())send(c.unit,{action:'resistor',unit:c.unit,channel:ch,resistance_ohms:Number(input.value)});};
   $(`resistor-${ch}`).oninput=()=>{$(`resistor-${ch}`).setCustomValidity('');};
   $(`remove-resistor-${ch}`).onclick=()=>send(c.unit,{action:'resistor',unit:c.unit,channel:ch,resistance_ohms:null});
   const legend=document.createElement('span');legend.className='ch'+c.local_channel;legend.textContent=ch;$('legend').append(legend);
  }
 }
 const legend=document.createElement('span');legend.className='meter-key';legend.textContent='Meter '+state.meter.channel;$('legend').append(legend);
 $('meter-heading').textContent='INDEPENDENT MEASUREMENT / DAC '+state.meter.channel;
 $('meter-note').textContent=`The Keysight is physically connected to DAC ${state.meter.channel}. Other channels show device values without an independent meter. Changing this label requires updating the bench configuration and the actual wiring.`;
}
function channelAction(channel,action){
 const c=state.channels.find(c=>c.channel===channel),target=$(`target-${channel}`),speed=$(`speed-${channel}`);
 speed.setCustomValidity('');if(action==='ramp'&&!(Number(speed.value)>0))speed.setCustomValidity('Enter a positive ramp speed.');
 if(!target.reportValidity()||(action==='ramp'&&!speed.reportValidity()))return;
 const data={action,unit:c.unit,channel,step_size:10};
 if(c.resistance_ohms!=null){data.action=action+'_current';data.current_mA=Number(target.value);data.speed_mA_s=Number(speed.value);data.resistance_ohms=c.resistance_ohms;}
 else{data.voltage=Number(target.value);data.speed=Number(speed.value);}
 send(c.unit,data);
}
function channelMode(c){
 const ch=c.channel,r=c.resistance_ohms??null,old=modes.get(ch),current=r!=null;
 if(!modes.has(ch)||old!==r){
  // Preserve the physical target/rate when switching units; never reinterpret the same number.
  for(const name of ['target','speed']){const el=$(`${name}-${ch}`);if(el.value!==''){let v=Number(el.value)*(old==null?1:old/1000);el.value=String(current?v/r*1000:v);}}
  modes.set(ch,r);$(`resistor-${ch}`).value=current?String(r):'';
 }
 $(`target-label-${ch}`).textContent='Target · '+(current?'mA':'V');
 $(`speed-label-${ch}`).textContent='Ramp · '+(current?'mA/s':'V/s');
 $(`target-${ch}`).setAttribute('aria-label',`DAC ${ch} target ${current?'current in mA':'voltage in V'}`);
 $(`speed-${ch}`).setAttribute('aria-label',`DAC ${ch} ramp speed in ${current?'mA/s':'V/s'}`);
 $(`set-${ch}`).textContent=current?'Set current':'Set voltage';
 $(`resistor-summary-${ch}`).textContent=current?`Resistor · ${r.toLocaleString()} Ω · edit`:'Add resistor';
 const limits=current?c.current_limits_mA:c.limits,unit=current?'mA':'V';
 $(`limits-${ch}`).textContent=limits?`${volts(limits[0])} to ${volts(limits[1])} ${unit}`:'';
 if(limits){$(`target-${ch}`).min=limits[0];$(`target-${ch}`).max=limits[1];}
 else{$(`target-${ch}`).removeAttribute('min');$(`target-${ch}`).removeAttribute('max');}
 return current;
}
async function send(unit,data){
 if(posting.has(unit)||pending.has(unit))return;
 const request_id=crypto.randomUUID();posting.add(unit);pending.set(unit,request_id);
 message(unit,'Sending '+data.action.replaceAll('_',' ')+'…');render();
 try{
  const response=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json','X-DAC-Token':document.querySelector('meta[name="dac-token"]').content},body:JSON.stringify({...data,request_id}),signal:AbortSignal.timeout(6000)});
  const result=await response.json();if(!response.ok)throw new Error(result.error||'Command rejected');
 }catch(error){message(unit,error.name==='TimeoutError'?'Response timed out. Outcome unknown; check this unit before retrying.':error.message,true);pending.delete(unit);}
 finally{posting.delete(unit);render();}
}
async function poll(){
 try{
  const response=await fetch('/api/state',{signal:AbortSignal.timeout(2000)});if(!response.ok)throw new Error('Local server unavailable');
  const next=await response.json();if(session!==null&&session!==next.server_started){location.reload();return;}
  session=next.server_started;state=next;received=performance.now();build();
  for(const [unit,id] of pending){const job=state.jobs[id];if(job&&job.state!=='pending'){
   message(unit,job.state==='failed'?job.error:['ramp','ramp_current'].includes(job.action)?'Ramp started.':job.action==='resistor'?'Resistor setting saved. Output unchanged.':job.action==='label'?'Channel name saved. Output unchanged.':job.action==='safe_zero'?'Safe zero started on this unit’s four channels.':job.action==='network'?'Network reset requested; reconnecting this unit.':job.action.toUpperCase()+' complete.',job.state==='failed');pending.delete(unit);
   if(job.action==='label'&&job.state==='complete')$(`label-form-${job.channel}`).hidden=true;
  }}
  render();drawTrace();
 }catch(error){render();}
 setTimeout(poll,250);
}
function render(){
 const serverFresh=state&&performance.now()-received<2500;
 $('server-alert').hidden=!!serverFresh;
 $('server-alert').textContent=state?'Dashboard connection lost. Values are stale; no output commands have been replayed.':'Connecting to the local dashboard…';
 if(!state)return;
 const now=state.now+(performance.now()-received)/1000;
 let goodCount=0;
 for(const u of state.units){
  const id=u.unit,n=u.network,r=u.recovery;
  const networkFresh=serverFresh&&n.state==='good'&&age(n.last_ok,now)<2.5;
  if(networkFresh)goodCount++;
  const labels={good:'Network good',connecting:'Connecting',failed:'Network unavailable',disconnected:'Disconnected',suspended:'Network paused · safe zero'};
  $(`network-label-${id}`).textContent=!serverFresh?'Dashboard offline':n.state==='good'&&!networkFresh?'Response overdue':labels[n.state]||n.state;
  $(`network-${id}`).className='signal '+(networkFresh?'good':['connecting','suspended','disconnected'].includes(n.state)&&serverFresh?'amber':'bad');
  $(`network-detail-${id}`).textContent=`Last reply ${ago(age(n.last_ok,now))}`+(networkFresh?` · ${n.latency_ms} ms`:n.error?' · '+n.error:'');
  const busy=u.ramp.state==='RUNNING',safe=r.state==='ACTIVE',latched=['LATCHED','FAILED'].includes(r.state),blocked=posting.has(id)||pending.has(id)||!!u.pending;
  $(`operation-${id}`).textContent=safe?'Safe zero running':r.state==='FAILED'?'Safe zero failed':latched?'Zero target · latched':busy?`Ramping ${channelName(state.channels.find(c=>c.channel===u.ramp.channel))}`:networkFresh?(u.device_error?'Readback unavailable':'Ready'):'Waiting for connection';
  $(`operation-${id}`).className='operation '+(safe||busy?'busy':'');
  for(const c of state.channels.filter(c=>c.unit===id)){
   const ch=c.channel,current=channelMode(c),fresh=serverFresh&&age(c.at,now)<2.5&&(networkFresh||safe||latched);
   $(`channel-label-${ch}`).textContent=c.label||`DAC ${ch}`;
   for(const name of ['rename','save-label','clear-label'])$(`${name}-${ch}`).disabled=blocked||!serverFresh;
   $(`voltage-${ch}`).innerHTML=`${volts(current?c.current_mA:c.voltage)} <small>${current?'mA':'V'}</small>`;
   $(`secondary-${ch}`).hidden=!current;$(`secondary-${ch}`).textContent=`${volts(c.voltage)} V · I = V/R · ${c.resistance_ohms?.toLocaleString()} Ω`;$(`secondary-${ch}`).className='secondary-reading'+(fresh?'':' stale');$(`voltage-${ch}`).className='voltage'+(fresh?'':' stale');
   $(`source-${ch}`).textContent=c.voltage==null?'Unknown · no valid device value':(!fresh?'Stale · last value ':c.source==='write'?'Device value · last write · ':'Readback · ')+ago(age(c.at,now));
   $(`cal-${ch}`).textContent=c.limits?(c.calibrated?'Calibrated':'Nominal'):'Unknown';$(`cal-${ch}`).className='tag'+(c.calibrated?' measured':'');
   for(const a of ['set','ramp'])$(`${a}-${ch}`).disabled=blocked||!networkFresh||busy||safe||latched;
   $(`save-resistor-${ch}`).disabled=blocked||!serverFresh||busy||safe;
   $(`remove-resistor-${ch}`).disabled=blocked||!serverFresh||busy||safe||!current;
  }
  $(`connect-${id}`).disabled=blocked||networkFresh||safe||latched;
  $(`disconnect-${id}`).disabled=blocked||!networkFresh;
  $(`initialize-${id}`).disabled=blocked||!networkFresh||busy||safe||latched;
  $(`abort-${id}`).disabled=blocked||!busy||!serverFresh;
  const usbAvailable=!!u.usb_port&&r.state!=='unavailable'&&r.state!=='unsupported';
  $(`network-reset-${id}`).disabled=blocked||safe||!serverFresh||!usbAvailable;
  $(`safe-zero-${id}`).disabled=blocked||safe||!serverFresh||!usbAvailable;
  $(`usb-${id}`).textContent=u.usb_port?'USB '+u.usb_port+' · '+r.state.toLowerCase():'Recovery: physical buttons only';
  if(u.device_error)message(id,u.device_error,true);
 }
 $('network-label').textContent=`${goodCount}/${state.units.length} units responding`;
 $('network').className='signal '+(goodCount===state.units.length?'good':goodCount?'amber':'bad');
 $('network-detail').textContent=`${state.channel_count} channels · fixed IP-list order`;
 const m=state.meter,c=state.channels[m.channel-1],u=state.units[c.unit-1];
 const mFresh=serverFresh&&m.state==='good'&&age(m.at,now)<2.5;
 const moving=u.ramp.state==='RUNNING'||u.recovery.state==='ACTIVE';
 const deviceFresh=(u.network.state==='good'&&age(u.network.last_ok,now)<2.5)||(u.recovery.state==='LATCHED'&&age(u.recovery.at,now)<2.5);
 const paired=mFresh&&deviceFresh&&age(c.at,now)<2.5&&c.voltage!=null&&!moving;
 const difference=paired?(m.voltage-c.voltage)*1000:null;
 $('meter-heading').textContent='INDEPENDENT MEASUREMENT / '+channelName(c);
 const meterCurrent=m.resistance_ohms!=null;
 $('meter-voltage').innerHTML=`${volts(meterCurrent?m.current_mA:m.voltage)} <small>${meterCurrent?'mA':'V'}</small>`;
 $('meter-secondary').hidden=!meterCurrent;$('meter-secondary').textContent=`${volts(m.voltage)} V measured · current calculated using ${m.resistance_ohms?.toLocaleString()} Ω`;
 $('meter-secondary').className='secondary-reading'+(mFresh?'':' stale');
 $('meter-note').textContent=meterCurrent?`Calculated current through the configured resistor on ${channelName(c)}, based on measured voltage. The meter is measuring voltage, not current directly.`:`The Keysight measures voltage on ${channelName(c)}. Other channels show device values without an independent meter.`;
 $('meter-voltage').className='meter-value'+(mFresh?'':' stale');$('meter-status').textContent=mFresh?'Live':m.voltage==null?'Unavailable':'Stale';
 $('meter-age').textContent=`${m.address} · ${ago(age(m.at,now))}`+(m.error?' · '+m.error:'');
 $('meter-difference').textContent=difference==null?'—':(difference>=0?'+':'')+difference.toFixed(3)+' mV';
 $('accuracy').textContent=paired?(Math.abs(difference)<=.5?'Within ±0.5 mV':'Outside ±0.5 mV'):moving?'Tracking ramp · samples are not simultaneous':'Waiting for fresh paired readings';
 $('accuracy').className='accuracy '+(paired?(Math.abs(difference)<=.5?'pass':'fail'):'');
 const hasResistors=state.channels.some(c=>c.resistance_ohms!=null);$('trace-current-option').disabled=!hasResistors;if(hasResistors&&!hadResistors)$('trace-mode').value='current';if(!hasResistors)$('trace-mode').value='voltage';hadResistors=hasResistors;
 const events=JSON.stringify(state.events);if(events!==lastEvents){lastEvents=events;$('events').replaceChildren();for(const e of state.events){const li=document.createElement('li');li.className=e.level;const t=document.createElement('time');t.textContent=new Date(e.at*1000).toLocaleTimeString();li.append(t,document.createTextNode('Unit '+e.unit+' · '+e.message));$('events').append(li);}}
 $('updated').textContent=serverFresh?'Live · '+new Date(state.now*1000).toLocaleTimeString():'Updates stopped';
}
function drawTrace(){
 if(!state)return;
 const current=$('trace-mode').value==='current',now=state.now,h=state.history.filter(p=>p.at>=now-60);
 const selected=state.channels.filter(c=>!current||c.resistance_ohms!=null),meterVisible=!current||state.meter.resistance_ohms!=null;
 const key=JSON.stringify([current,selected.map(c=>[c.channel,c.label]),meterVisible,channelName(state.channels[state.meter.channel-1])]);
 if(key!==traceKey){traceKey=key;$('legend').replaceChildren();for(const c of selected){const el=document.createElement('span');el.className='ch'+c.local_channel;el.textContent=channelName(c);$('legend').append(el);}if(meterVisible){const el=document.createElement('span');el.className='meter-key';el.textContent='Meter · '+channelName(state.channels[state.meter.channel-1]);$('legend').append(el);}}
 $('trace-note').textContent=current?'Calculated current (mA) for channels with resistors. Gaps mark unavailable data or changed resistance.':'Voltage (V) for all channels. Device values follow programmed codes; gaps mark unavailable data.';
 $('trace').setAttribute('aria-label',current?'Recent calculated DAC current in mA':'Recent DAC voltages in V');
 if(!h.length){$('trace').innerHTML='';return;}
 const value=(p,ch)=>current?(p.currents?.[ch-1]??null):p.channels[ch-1];
 const meterValue=p=>current?(p.meter_current??null):p.meter;
 const values=h.flatMap(p=>[...selected.map(c=>value(p,c.channel)),...(meterVisible?[meterValue(p)]:[])]).filter(v=>v!=null);
 let min=Math.min(0,...values),max=Math.max(0,...values);const pad=Math.max(current?.00001:.005,(max-min)*.12);min-=pad;max+=pad;
 const x=t=>55+(t-(now-60))/60*770,y=v=>190-(v-min)/(max-min)*170;let svg='';
 for(let i=0;i<5;i++){const v=min+(max-min)*i/4,yy=y(v);svg+=`<line x1="55" x2="825" y1="${yy}" y2="${yy}" stroke="#e9eeee"/><text x="43" y="${yy+4}" text-anchor="end" fill="#829398" font-size="10">${Math.abs(v)<.001?v.toExponential(1):v.toFixed(3)}</text>`;}
 for(const ch of [...selected.map(c=>c.channel),...(meterVisible?[0]:[])]){
  const meter=ch===0;let path='',open=false,lastR=null;
  for(const p of h){const v=meter?meterValue(p):value(p,ch),r=p.resistances?.[(meter?state.meter.channel:ch)-1];if(v==null){open=false;continue;}if(current&&r!==lastR)open=false;path+=(open?'L':'M')+x(p.at).toFixed(1)+','+y(v).toFixed(1)+' ';open=true;lastR=r;}
  svg+=`<path d="${path}" fill="none" stroke="${meter?'#263b42':color(ch)}" stroke-width="${meter?1.2:1.6}" ${meter?'stroke-dasharray="4 3"':ch>4?'stroke-dasharray="9 3"':''}/>`;
 }
 svg+='<text x="55" y="215" fill="#829398" font-size="10">−60 s</text><text x="825" y="215" text-anchor="end" fill="#829398" font-size="10">Now</text>';$('trace').innerHTML=svg;
}
$('trace-mode').onchange=drawTrace;
setInterval(render,250);poll();
