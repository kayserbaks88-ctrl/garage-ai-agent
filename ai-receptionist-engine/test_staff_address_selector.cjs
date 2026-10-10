// Run with node test_staff_address_selector.cjs. No network or database access.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Element {
  constructor() { this.children = []; this.events = {}; this.dataset = {}; this.value = ''; this.attributes = {}; }
  addEventListener(name, callback) { (this.events[name] ||= []).push(callback); }
  async dispatchEvent(event) { for (const callback of this.events[event.type] || []) await callback(event); }
  setAttribute(name, value) { this.attributes[name] = value; }
  append(child) { this.children.push(child); }
  after(child) { this.sibling = child; }
  replaceChildren(...children) { this.children = children; this.observer?.(); }
  add(child) { this.append(child); this.observer?.(); }
  get options() { return this.children; }
  get selectedOptions() { return this.children.filter(child => child.value === this.value); }
  set disabled(value) { this._disabled = value; this.observer?.(); }
  get disabled() { return this._disabled; }
}

async function check(company) {
  const search = new Element(), results = new Element(), address = new Element();
  const message = new Element(), review = new Element(), coordinateReview = new Element();
  const selected = new Element(), latitude = new Element(), longitude = new Element();
  const button = new Element(), locationMessage = new Element(), radius = new Element();
  const csrf = new Element(), form = new Element(), fields = new Element();
  csrf.value = 'local-test-csrf'; radius.value = '250'; latitude.value = '51.5'; longitude.value = '-0.1';
  form.querySelector = () => csrf;
  fields.closest = () => form;
  fields.dataset.addressUrl = '/staff/test/sites/address-lookup';
  const elements = {
    '[data-address-search]': search, '[data-address-results]': results,
    '[name="address"], [name="company_address"]': address, '[data-address-message]': message,
    '[data-coordinates-reviewed]': company ? null : review,
    '[data-coordinate-review]': coordinateReview, '[name="address_lookup_selected"]': selected,
    '[name="latitude"]': company ? null : latitude, '[name="longitude"]': company ? null : longitude,
    '[data-use-location]': company ? null : button, '[data-location-message]': company ? null : locationMessage,
    '[name="allowed_radius_metres"]': radius
  };
  fields.querySelector = selector => elements[selector] || null;
  let timer, fetched = [];
  const context = {
    document: {getElementById: () => null, querySelector: () => null,
      querySelectorAll: () => [fields], createElement: () => new Element()},
    Option: function(label, value) { this.textContent = label; this.value = value; this.dataset = {}; },
    MutationObserver: class { constructor(callback) { this.callback = callback; } observe(element) { element.observer = this.callback; } },
    Event: class { constructor(type) { this.type = type; } }, URLSearchParams, AbortController,
    setTimeout: callback => { timer = callback; }, clearTimeout: () => { timer = null; },
    navigator: {},
    fetch: async (url, options) => {
      assert.equal(options.credentials, 'same-origin');
      assert.equal(options.body.get('csrf_token'), csrf.value);
      fetched.push(options.body);
      const data = options.body.has('query') ? {suggestions: Array.from({length: 20}, (_, i) => ({id: 'paf_' + i, label: i + ' Long Street, London'}))} : {address: '19 Long Street, London SW1A 1AA'};
      return {ok: true, headers: {get: () => 'application/json'}, json: async () => data};
    }
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'static/staff_manager.js'), 'utf8'), context);
  search.value = 'SW1A 1AA';
  await search.dispatchEvent({type: 'input'});
  await timer();
  assert.equal(results.sibling.children.length, 20, 'all returned addresses must be selectable');
  assert.equal(results.hidden, true, 'replace the native mobile picker');
  await results.sibling.children[19].dispatchEvent({type: 'click'});
  // Browser dispatchEvent does not await asynchronous listeners.
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(address.value, '19 Long Street, London SW1A 1AA');
  assert.equal(fetched[1].get('address_id'), 'paf_19');
  assert.equal(latitude.value, '51.5', 'address selection must not replace GPS');
  if (!company) { assert.equal(review.required, true); assert.equal(review.checked, false); }
  address.value = 'Manually entered address';
  await address.dispatchEvent({type: 'input'});
  assert.equal(address.value, 'Manually entered address');
}

(async () => {
  await check(true);
  await check(false);
  const css = fs.readFileSync(path.join(__dirname, 'static/staff_manager.css'), 'utf8');
  assert.match(css, /\.address-choices\{[^}]*max-height:[^}]*overflow-y:auto/);
  console.log('PASS: company and site selectors expose all 20 results, preserve GPS review, CSRF and manual entry; scrolling CSS present');
})().catch(error => { console.error(error); process.exitCode = 1; });
