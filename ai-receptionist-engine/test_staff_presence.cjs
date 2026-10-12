const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');

test('manager polling separates fresh outside GPS, stale evidence and active breaks',async()=>{
  const card={dataset:{state:'on_shift'}};
  const status={dataset:{shiftStatus:'7'},closest:()=>card,textContent:''};
  const cell={dataset:{presenceShift:'7'},hasAttribute:()=>false,textContent:''};
  const root={dataset:{presenceUrl:'/staff/local/presence/status',csrf:'local-test'},querySelectorAll:q=>q==='[data-shift-status]'?[status]:[cell]};
  const intervals=new Map();
  let state={status:'on_site',display_status:'outside_site',last_location_at:new Date().toISOString(),last_confirmed_at:null,stale_seconds:120,break_started_at:new Date().toISOString(),break_minutes:4};
  const document={hidden:false,querySelector:q=>q==='[data-presence-dashboard]'?root:null,addEventListener(){},dispatchEvent(){}};
  const context={document,Date,Event,URLSearchParams,AbortController,setTimeout,clearTimeout,
    setInterval:(fn,ms)=>intervals.set(ms,fn),fetch:async()=>({ok:true,headers:{get:()=> 'application/json'},json:async()=>({shifts:{7:state}})})};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'static/staff_presence.js'),'utf8'),context);
  const settle=()=>new Promise(resolve=>setImmediate(resolve));
  await settle();
  assert.match(cell.textContent,/Outside site/);
  assert.match(status.textContent,/On break.*4 min/);
  assert.equal(card.dataset.state,'on_break');
  intervals.get(1000)();
  assert.match(cell.textContent,/Outside site/,'fresh sample must not age against absent prior confirmation');
  state={...state,display_status:'location_unverified',break_started_at:null,break_minutes:null};
  await intervals.get(30000)();
  assert.match(cell.textContent,/Location unverified/);
  assert.equal(status.textContent,'On shift');
  assert.equal(card.dataset.state,'on_shift');
  cell.dataset.lastReceived=new Date(Date.now()-121000).toISOString();
  intervals.get(1000)();
  assert.match(cell.textContent,/Location unverified/);
  assert.doesNotMatch(cell.textContent,/Outside site/);
});
