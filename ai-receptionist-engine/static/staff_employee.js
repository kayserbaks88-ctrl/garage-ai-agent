(() => {
  'use strict';
  document.querySelectorAll('[data-local-time]').forEach((el) => {
    const value = new Date(el.dateTime);
    if (!Number.isNaN(value.getTime())) {
      el.textContent = new Intl.DateTimeFormat('en-GB', {
        day:'2-digit', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit', timeZoneName:'short', timeZone:'Europe/London'
      }).format(value);
    }
  });
  const start = document.getElementById('start_date');
  const end = document.getElementById('end_date');
  if (start && end) start.addEventListener('change', () => {
    end.min = start.value;
    if (!end.value || (start.value && end.value < start.value)) end.value = start.value;
  });
  document.querySelectorAll('[data-submit-once]').forEach((form) => {
    form.addEventListener('submit', (event) => {
      if (form.dataset.busy === 'yes') { event.preventDefault(); return; }
      if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) { event.preventDefault(); return; }
      form.dataset.busy = 'yes';
      form.querySelectorAll('button[type="submit"]').forEach((button) => { button.disabled = true; });
    });
  });
  document.querySelectorAll('[data-location-form]').forEach((form) => {
    const button = form.querySelector('button[type="submit"]');
    const message = form.querySelector('.location-message');
    const originalLabel = button.textContent;
    const fail = (text) => {
      form.dataset.busy = '';
      button.disabled = false;
      button.textContent = originalLabel;
      message.textContent = text;
      message.classList.add('error');
    };
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      if (form.dataset.busy === 'yes') return;
      if (!form.reportValidity()) return;
      if (!window.isSecureContext || !navigator.geolocation) {
        fail('Location is unavailable. Open this page in Safari or Chrome using HTTPS.'); return;
      }
      form.dataset.busy = 'yes';
      button.disabled = true;
      button.textContent = 'Checking location…';
      message.classList.remove('error');
      message.textContent = 'Allow location access when prompted. Your location is checked only for this clocking action.';
      navigator.geolocation.getCurrentPosition((position) => {
        const {latitude, longitude, accuracy} = position.coords;
        if (![latitude,longitude,accuracy].every(Number.isFinite)) {
          fail('We could not get a valid location. Please try again.'); return;
        }
        form.elements.namedItem('latitude').value = latitude;
        form.elements.namedItem('longitude').value = longitude;
        form.elements.namedItem('accuracy').value = accuracy;
        form.elements.namedItem('captured_at').value = new Date(position.timestamp).toISOString();
        button.textContent = 'Saving…';
        message.textContent = 'Checking your work site and saving your shift…';
        HTMLFormElement.prototype.submit.call(form);
      }, (error) => {
        const messages = {
          1:'Location access was denied. Allow location for this website in your browser settings, then try again.',
          2:'Your location could not be found. Check Location Services and try again in an open area.',
          3:'The location check timed out. Please try again.'
        };
        fail(messages[error.code] || 'The location check failed. Please try again.');
      }, {enableHighAccuracy:true, timeout:20000, maximumAge:0});
    });
  });
  window.addEventListener('pageshow', (event) => { if (event.persisted) window.location.reload(); });
})();
