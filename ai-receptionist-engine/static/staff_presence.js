'use strict';
(() => {
  const portal = document.querySelector('[data-presence-portal]');
  async function post(url, values) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(),15000);
    let response;
    try {
      response = await fetch(url, {method:'POST', body:new URLSearchParams(values),
        credentials:'same-origin', headers:{Accept:'application/json'}, redirect:'error', signal:controller.signal});
    } finally {clearTimeout(timeout);}
    if (!(response.headers.get('content-type') || '').includes('application/json')) {
      throw new Error('Your session may have expired. Refresh the page to continue.');
    }
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Location update unavailable.');
    return data;
  }
  if (portal) {
    const start = portal.querySelector('[data-presence-start]');
    const stop = portal.querySelector('[data-presence-stop]');
    const state = portal.querySelector('[data-presence-state]');
    const message = portal.querySelector('[data-presence-message]');
    let enabled=false, busy=false, timer, lastReceived=0, staleSeconds=120, generation=0;
    const schedule = () => { clearTimeout(timer); if(enabled && !document.hidden) timer=setTimeout(update,30000); };
    async function update() {
      if (!enabled || busy || document.hidden) return;
      busy=true;
      const current=generation;
      try {
        const position = await new Promise((resolve,reject) => navigator.geolocation.getCurrentPosition(resolve,reject,
          {enableHighAccuracy:true,maximumAge:0,timeout:20000}));
        if (!enabled || current!==generation || document.hidden) return;
        const data = await post(portal.dataset.presenceUrl, {csrf_token:portal.dataset.csrf,
          shift_id:portal.dataset.shiftId,latitude:position.coords.latitude,longitude:position.coords.longitude,
          accuracy:position.coords.accuracy,captured_at:new Date(position.timestamp).toISOString()});
        if (current!==generation) return;
        state.textContent=data.status;
        lastReceived=Date.parse(data.last_received_at);
        staleSeconds=data.stale_seconds;
        message.textContent='Location received. Updates run only while this page is visible.';
      } catch(error) {
        if(current===generation) message.textContent=error.code===1 ? 'Location permission denied. Allow location access, then restart updates.' :
          'Unable to send a fresh location. Status becomes location_stale if updates stop. ' + (error.message || '');
      } finally { busy=false; schedule(); }
    }
    start.addEventListener('click', () => {
      if (!window.isSecureContext || !navigator.geolocation) {
        message.textContent='Presence needs HTTPS and browser location access. Clocking is unchanged.'; return;
      }
      enabled=true;generation++;start.disabled=true;stop.disabled=false;update();
    });
    stop.addEventListener('click', () => {
      enabled=false;generation++;clearTimeout(timer);start.disabled=false;stop.disabled=true;
      message.textContent='Updates stopped. The last location will become location_stale when it expires.';
    });
    document.addEventListener('visibilitychange', () => {
      clearTimeout(timer);
      if(document.hidden) message.textContent='Updates paused while this page is hidden. Your location may become stale.';
      else if(enabled) update();
    });
    setInterval(() => { if(!lastReceived || Date.now()-lastReceived>=staleSeconds*1000) state.textContent='location_stale'; },1000);
  }
  const dashboard = document.querySelector('[data-presence-dashboard]');
  if(dashboard) {
    const cells=Array.from(dashboard.querySelectorAll('[data-presence-shift]'));
    let busy=false;
    async function refresh() {
      if(busy || document.hidden) return;
      busy=true;
      try {
        const data=await post(dashboard.dataset.presenceUrl,{csrf_token:dashboard.dataset.csrf});
        cells.forEach(cell => {
          const state=data.shifts[cell.dataset.presenceShift];
          cell.textContent=state ? state.status : 'Shift ended — refresh attendance';
          cell.dataset.lastReceived=state ? state.last_received_at || '' : '';
          cell.dataset.staleSeconds=state ? state.stale_seconds : '0';
          cell.title=state && state.last_received_at ? 'Last received: '+new Date(state.last_received_at).toLocaleString('en-GB') : 'No fresh location';
        });
      } catch(_) {
        cells.forEach(cell => { cell.title='Presence refresh failed. Refresh this page to retry.'; });
      } finally {busy=false;}
    }
    setInterval(() => cells.forEach(cell => {
      if(Number(cell.dataset.staleSeconds)>0 && (!cell.dataset.lastReceived ||
        Date.now()-Date.parse(cell.dataset.lastReceived)>=Number(cell.dataset.staleSeconds)*1000)) cell.textContent='location_stale';
    }),1000);
    setInterval(refresh,30000);
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
    refresh();
  }
})();
