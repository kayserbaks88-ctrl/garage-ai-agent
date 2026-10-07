'use strict';
(() => {
  const queue=document.querySelector('[data-payslip-queue]');
  if(!queue || Number(queue.dataset.pending)===0) return;
  const message=queue.querySelector('[data-queue-message]');
  async function next(){
    try {
      const controller=new AbortController();
      const timeout=setTimeout(()=>controller.abort(),25000);
      let response;
      try {
        response=await fetch(queue.dataset.url,{method:'POST',credentials:'same-origin',redirect:'error',
          headers:{Accept:'application/json'},body:new URLSearchParams({csrf_token:queue.dataset.csrf}),signal:controller.signal});
      } finally {clearTimeout(timeout);}
      if(!response.ok || !(response.headers.get('content-type') || '').includes('application/json')) throw new Error();
      const data=await response.json();
      let failed=0,sent=0;
      data.notices.forEach(notice=>{
        const cell=document.querySelector(`[data-notice-status="${notice.id}"]`);
        const retry=document.querySelector(`[data-notice-retry="${notice.id}"]`);
        const label=notice.status==='sent' ? 'Accepted by email provider (inbox delivery unconfirmed)' : notice.status;
        if(cell) cell.textContent='Email: '+label+(notice.error_code ? ' ('+notice.error_code.replaceAll('_',' ')+')' : '')+'. Payslip is available in the secure employee portal.';
        if(cell) cell.classList.toggle('alert',['failed','disabled'].includes(notice.status));
        if(retry) retry.hidden=!['failed','disabled'].includes(notice.status);
        if(['failed','disabled'].includes(notice.status)) failed++;
        if(notice.status==='sent') sent++;
      });
      message.textContent=`Payroll approved. ${sent} email notices accepted; ${failed} need attention; ${data.pending} pending. Failed notices can be retried individually.`;
      if(data.pending>0) setTimeout(next,600);
    } catch(_) {
      message.textContent='Payroll and portal payslips remain finalised. Email processing paused; reopen this review to resume pending notices. Successful emails will not be resent.';
    }
  }
  next();
})();
