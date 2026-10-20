'use strict';
(() => {
  const status = document.querySelector('[data-pwa-status]');
  const update = () => {
    if (status) {
      status.hidden = navigator.onLine;
      status.textContent = 'You are offline. Reconnect before clocking, approving shifts, changing payroll, submitting forms or signing out. Nothing will be queued.';
    }
  };
  update();
  addEventListener('online', update);
  addEventListener('offline', update);
  // Capture before the existing GPS/submit handlers; never queue or replay a form.
  document.addEventListener('submit', event => {
    if (!navigator.onLine) {
      event.preventDefault();
      event.stopImmediatePropagation();
      update();
      status?.focus();
    }
  }, true);
  if ('serviceWorker' in navigator && window.isSecureContext) {
    navigator.serviceWorker.register('/staff/employee-sw.js', {
      scope: '/staff/', updateViaCache: 'none'
    }).catch(() => {
      const message = document.querySelector('[data-install-status]');
      if (message) message.textContent = 'Installation is unavailable in this browser. You can continue using the online employee portal.';
    });
  }
  let prompt;
  const install = document.querySelector('[data-install-app]');
  addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    prompt = event;
    if (install) install.hidden = false;
  });
  install?.addEventListener('click', async () => {
    if (!prompt) return;
    install.hidden = true;
    await prompt.prompt();
    prompt = null;
  });
  addEventListener('appinstalled', () => { if (install) install.hidden = true; });
})();
