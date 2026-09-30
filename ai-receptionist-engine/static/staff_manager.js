'use strict';
const assignmentForm = document.getElementById('assignment-form');
if (assignmentForm) {
  const startDate = assignmentForm.elements.namedItem('start_date');
  const endDate = assignmentForm.elements.namedItem('end_date');
  let previousStart = startDate.value;
  startDate.addEventListener('change', () => {
    if (!endDate.value || endDate.value === previousStart) endDate.value = startDate.value;
    endDate.min = startDate.value;
    previousStart = startDate.value;
  });
}
// Ideal Postcodes is proxied by the authenticated staging server. No browser API key.
// Selecting an address never fills or verifies coordinates.
document.querySelectorAll('[data-site-fields]').forEach(fields => {
  const search = fields.querySelector('[data-address-search]');
  const results = fields.querySelector('[data-address-results]');
  const address = fields.querySelector('[name="address"]');
  const message = fields.querySelector('[data-address-message]');
  const review = fields.querySelector('[data-coordinates-reviewed]');
  function requireCoordinateReview() {
    fields.querySelector('[data-coordinate-review]').hidden = false;
    fields.querySelector('[name="address_lookup_selected"]').value = '1';
    review.required = true;
    review.checked = false;
  }
  address.addEventListener('input', () => {
    if (review.required) review.checked = false;
  });
  ['latitude', 'longitude'].forEach(name => fields.querySelector('[name="' + name + '"]')
    .addEventListener('input', () => { if (review.required) review.checked = false; }));
  let timer, sequence = 0;
  let controller;
  fields.closest('form').addEventListener('reset', () => {
    clearTimeout(timer);
    ++sequence;
    if (controller) controller.abort();
    review.required = false;
    fields.querySelector('[data-coordinate-review]').hidden = true;
    results.replaceChildren(new Option('Type above to search', ''));
    results.disabled = false;
    message.textContent = 'Type at least 3 characters, then choose a match.';
  });
  async function lookup(values, signal) {
    const form = fields.closest('form');
    const body = new URLSearchParams({...values, csrf_token: form.querySelector('[name="csrf_token"]').value});
    const response = await fetch(fields.dataset.addressUrl, {
      method: 'POST', body, signal, credentials: 'same-origin',
      headers: {Accept: 'application/json'}, redirect: 'error'
    });
    if (!(response.headers.get('content-type') || '').includes('application/json')) {
      throw new Error('Your session has expired. Refresh the page before searching again.');
    }
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Address lookup unavailable. Enter the address manually.');
    return data;
  }
  search.addEventListener('input', () => {
    clearTimeout(timer);
    if (controller) controller.abort();
    const current = ++sequence;
    const query = search.value.trim();
    results.replaceChildren(new Option('Choose an address', ''));
    results.disabled = true;
    if (query.length < 3) {
      message.textContent = 'Type at least 3 characters to search.';
      return;
    }
    message.textContent = 'Searching UK addresses…';
    timer = setTimeout(async () => {
      controller = new AbortController();
      try {
        const data = await lookup({query}, controller.signal);
        if (current !== sequence) return;
        data.suggestions.forEach(hit => results.add(new Option(hit.label, hit.id)));
        results.disabled = data.suggestions.length === 0;
        message.textContent = data.suggestions.length ? 'Choose a matching address below.' : 'No matches. Try adding the town or postcode, or enter the address manually.';
      } catch (error) {
        if (current === sequence && error.name !== 'AbortError') message.textContent = error.message;
      }
    }, 300);
  });
  results.addEventListener('change', async () => {
    if (!results.value) return;
    const option = results.selectedOptions[0];
    const current = ++sequence;
    clearTimeout(timer);
    if (controller) controller.abort();
    controller = new AbortController();
    const previousAddress = address.value;
    results.disabled = true;
    message.textContent = 'Loading full address…';
    try {
      const data = option.dataset.savedAddress ? {address: option.dataset.savedAddress} :
        await lookup({address_id: results.value}, controller.signal);
      if (current !== sequence) return;
      // Do not overwrite a manual edit made while the provider request was running.
      if (address.value !== previousAddress) {
        message.textContent = 'Your manual address edit was kept. Select the match again to replace it.';
        return;
      }
      address.value = data.address;
      requireCoordinateReview();
      message.textContent = 'Full address filled. GPS is not verified: capture your location at the site or verify the coordinates below.';
      fields.querySelector('[data-location-message]').textContent = 'Address selected. Existing coordinates have not been verified for this address. Capture or verify them before saving.';
    } catch (error) {
      if (current === sequence && error.name !== 'AbortError') message.textContent = error.message;
    } finally {
      if (current === sequence) results.disabled = false;
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
      if (review.required) review.checked = true;
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
