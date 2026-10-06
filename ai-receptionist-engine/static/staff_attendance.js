'use strict';
(() => {
  const root=document.querySelector('[data-attendance-mobile]');
  if(!root) return;
  const cards=Array.from(root.querySelectorAll('[data-attendance-person]'));
  const search=root.querySelector('[data-attendance-search]');
  const site=root.querySelector('[data-attendance-site]');
  const status=root.querySelector('[data-attendance-status]');
  const alert=root.querySelector('[data-attendance-alert]');
  const records=cards.map(card=>({card,sites:JSON.parse(card.dataset.sites),statuses:JSON.parse(card.dataset.statuses)}));
  function filter(){
    let shown=0,active=0,alerts=0;
    const query=search.value.trim().toLocaleLowerCase('en-GB');
    records.forEach(({card,sites,statuses})=>{
      const presence=card.querySelector('[data-presence-compact]');
      const state=presence ? presence.dataset.presenceState : '';
      const warning=card.dataset.alert==='1' || state==='left_site' || state==='location_stale';
      card.querySelector('[data-attendance-warning]').hidden=!warning;
      const matchAlert=!alert.value || (alert.value==='any' && warning) ||
        (alert.value==='late' && card.dataset.late==='1') || (alert.value==='missed' && card.dataset.missed==='1') ||
        (['left_site','location_stale'].includes(alert.value) && state===alert.value);
      const visible=card.dataset.name.toLocaleLowerCase('en-GB').includes(query) &&
        (!site.value || sites.includes(site.value)) &&
        (!status.value || card.dataset.state===status.value || statuses.includes(status.value)) && matchAlert;
      card.hidden=!visible;
      if(visible){shown++;if(card.dataset.state==='on_shift')active++;if(warning)alerts++;}
    });
    root.querySelector('[data-attendance-count]').textContent=`${shown} / ${cards.length} staff · ${active} on shift · ${alerts} alerts`;
    root.querySelector('[data-attendance-empty]').hidden=shown!==0;
  }
  [search,site,status,alert].forEach(control=>control.addEventListener('input',filter));
  root.querySelector('[data-attendance-reset]').addEventListener('click',()=>{[search,site,status,alert].forEach(c=>c.value='');filter();});
  document.addEventListener('staff-presence-updated',filter);
  filter();
})();
