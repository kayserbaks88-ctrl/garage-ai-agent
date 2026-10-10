// Run with node test_staff_joining.cjs; no browser, network or database access.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const account = fs.readFileSync(path.join(__dirname, 'static/staff_account.js'), 'utf8');
const joining = fs.readFileSync(path.join(__dirname, 'static/staff_join.js'), 'utf8');

async function run() {
  const token = 'A'.repeat(43), calls = [], events = {};
  const field = {value: '', addEventListener: (name, fn) => events[name] = fn};
  const label = {textContent: ''};
  const form = {elements: {token: field, csrf_token: {value: 'csrf'}}, dataset: {previewUrl: '/staff/join/preview'}};
  const context = vm.createContext({URLSearchParams, document: {
    getElementById: id => ({token: field, 'joining-form': form, 'joining-company': label}[id]), querySelectorAll: () => []
  }, window: {location: {hash: '#token=' + token, pathname: '/staff/join'}, history: {
    replaceState: (...args) => calls.push(args)
  }}, fetch: async (url, options) => {
    assert.equal(url, '/staff/join/preview');assert.equal(options.method, 'POST');
    assert.equal(options.body.get('token'), token);assert.equal(options.body.get('csrf_token'), 'csrf');
    return {ok: true, json: async () => ({company: '<script>company</script>'})};
  }});
  vm.runInContext(account, context);assert.equal(field.value, token);
  assert.equal(calls[0][2], '/staff/join'); // Raw token removed from visible URL/history.
  vm.runInContext(joining, context);await new Promise(resolve => setImmediate(resolve));
  assert.equal(label.textContent, 'Joining <script>company</script>'); // textContent, never HTML.
  context.fetch = async () => {throw Error('network');};await events.change();
  assert.match(label.textContent, /Unable to check the company/);
  assert.equal(field.value, token); // Failure preserves token for a later submission.
  let resolvePreview;
  context.fetch = () => new Promise(resolve => resolvePreview = resolve);
  const stale = events.change();
  field.value = 'B'.repeat(43);
  label.textContent = 'Joining the new company';
  resolvePreview({ok: true, json: async () => ({company: 'Old company'})});
  await stale;assert.equal(label.textContent, 'Joining the new company');
  field.value = 'incomplete';await events.change();assert.match(label.textContent, /complete joining code/);

  let handler, selected = false;
  const linkField = {value: 'https://example.test/staff/join#token=' + token, focus() {}, select() {selected = true;}};
  const button = {addEventListener: (_, fn) => handler = fn};
  const copyContext = vm.createContext({document: {getElementById: id => id === 'joining-url' ? linkField : null, querySelectorAll: () => [button]}, navigator: {clipboard: {writeText: async value => assert.equal(value, linkField.value)}}});
  vm.runInContext(joining, copyContext);await handler();assert.equal(button.textContent, 'Copied');
  copyContext.navigator.clipboard.writeText = async () => {throw Error('denied');};await handler();
  assert.equal(selected, true);assert.equal(button.textContent, 'Select and copy the link');
  console.log('PASS: joining fragment, secure POST preview, safe text, retry and clipboard fallback');
}
run().catch(error => {console.error(error);process.exitCode = 1;});
