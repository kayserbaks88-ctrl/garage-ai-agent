'use strict';
// Optional provider adapter: window.staffAddressSearch(query) -> Promise<string[]>.
// Connect an authenticated same-origin UK address service here; never embed API keys.
// Results fill addresses only. GPS remains explicitly captured/reviewed by the manager.
document.querySelectorAll('[data-site-fields]').forEach(fields => {
  const search = fields.querySelector('[data-address-search]');
  const results = fields.querySelector('[data-address-results]');
  const address = fields.querySelector('[name="address"]');
  const message = fields.querySelector('[data-address-message]');
  const saved = Array.from(results.options, option => option.value);
  let timer, sequence = 0;
  search.addEventListener('input', () => {
    clearTimeout(timer);
    const current = ++sequence;
    const query = search.value.trim();
    if (typeof window.staffAddressSearch !== 'function' || query.length < 3) return;
    timer = setTimeout(async () => {
      try {
        const matches = await window.staffAddressSearch(query);
        if (current !== sequence) return;
        results.replaceChildren();
        [...new Set([...saved, ...matches.filter(value => typeof value === 'string')])]
          .slice(0, 100).forEach(value => results.append(new Option('', value)));
        message.textContent = 'Choose a matching address, or enter it manually below. Review the site coordinates.';
      } catch (_) {
        if (current === sequence) message.textContent = 'Address search unavailable. Enter the full address and postcode below.';
      }
    }, 300);
  });
  search.addEventListener('change', () => {
    if (Array.from(results.options).some(option => option.value === search.value)) {
      address.value = search.value;
      message.textContent = 'Address filled. Check the postcode and site coordinates before saving.';
    }
  });
  const button = fields.querySelector('[data-use-location]');
  const locationMessage = fields.querySelector('[data-location-message]');
  button.addEventListener('click', () => {
    if (!navigator.geolocation) {
      locationMessage.textContent = 'Location unavailable. Enter verified coordinates manually.';
      return;
    }
    button.disabled = true;
    locationMessage.textContent = 'Getting your location…';
    navigator.geolocation.getCurrentPosition(position => {
      button.disabled = false;
      const c = position.coords;
      const limit = Math.min(100, Number(fields.querySelector('[name="allowed_radius_metres"]').value) || 100);
      if (!Number.isFinite(c.accuracy) || c.accuracy > limit) {
        locationMessage.textContent = 'Location is too approximate. Try outside or enter verified coordinates.';
        return;
      }
      fields.querySelector('[name="latitude"]').value = c.latitude.toFixed(7);
      fields.querySelector('[name="longitude"]').value = c.longitude.toFixed(7);
      locationMessage.textContent = 'Coordinates filled. Accuracy: ' + Math.round(c.accuracy) + ' metres. Check you are at the intended site before saving.';
    }, error => {
      button.disabled = false;
      locationMessage.textContent = error.code === 1 ? 'Location permission denied. Allow access or enter coordinates manually.' : 'Could not obtain location. Try again or enter coordinates manually.';
    }, {enableHighAccuracy: true, maximumAge: 0, timeout: 20000});
  });
});

const newSiteForm = document.querySelector('[data-inline-site]');
if (newSiteForm) {
  newSiteForm.addEventListener('submit', async event => {
    event.preventDefault();
    const button = newSiteForm.querySelector('[type="submit"]');
    const message = newSiteForm.querySelector('[data-save-message]');
    button.disabled = true;
    message.textContent = 'Saving site…';
    try {
      const response = await fetch(newSiteForm.action, {
        method: 'POST', body: new FormData(newSiteForm),
        headers: {Accept: 'application/json'}, credentials: 'same-origin', redirect: 'error'
      });
      if (!(response.headers.get('content-type') || '').includes('application/json')) {
        throw new Error('Your session may have expired. Open Staff Manager in another tab to sign in, then retry.');
      }
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Could not save the work site.');
      const select = document.querySelector('#assignment-form [name="site_id"]');
      const site = data.site;
      select.add(new Option(site.name + (site.client_reference ? ' · ' + site.client_reference : ''), site.id, false, true));
      select.value = String(site.id);
      select.dispatchEvent(new Event('change', {bubbles: true}));
      newSiteForm.reset();
      newSiteForm.closest('details').open = false;
      document.querySelector('[data-assignment-message]').textContent = 'Work site saved and selected. Complete the assignment below.';
      select.focus();
      message.textContent = '';
    } catch (error) {
      message.textContent = error.message + ' Your assignment entries have been kept.';
    } finally {
      button.disabled = false;
    }
  });
}
