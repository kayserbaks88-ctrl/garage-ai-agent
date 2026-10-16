// Run with node test_staff_account_ui.cjs. No browser, database or network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, 'static/staff_account.js'), 'utf8');

function run(hash, value = '', hasField = true) {
  const help = {hidden: false}, history = [];
  const field = {value, type: 'text', name: 'token', closest: () => help};
  vm.runInNewContext(source, {
    URLSearchParams,
    document: {getElementById: () => hasField ? field : null, querySelector: () => null},
    window: {location: {hash, pathname: '/staff/account/reset'},
      history: {replaceState: (...args) => history.push(args)}}
  });
  return {field, help, history};
}

const token = 'A'.repeat(43);
for (const result of [run('#token=' + token), run('', token)]) {
  assert.equal(result.field.value, token);
  assert.equal(result.field.name, 'token');
  assert.equal(result.field.type, 'hidden');
  assert.equal(result.help.hidden, true);
}
assert.equal(run('#token=' + token).history[0][2], '/staff/account/reset');
for (const hash of ['', '#token=short', '#token=' + 'A'.repeat(44), '#token=' + '%3Cscript%3E']) {
  const result = run(hash);
  assert.equal(result.field.type, 'text');
  assert.equal(result.help.hidden, false); // Manual entry / no-JavaScript fallback stays usable.
  assert.equal(result.field.value, '');
}
const invalidRetry = run('', 'A'.repeat(44));
assert.equal(invalidRetry.field.value.length, 44);
assert.equal(invalidRetry.help.hidden, false);
assert.doesNotThrow(() => run('', '', false));
console.log('PASS: email codes hidden, fragment cleared, retries preserved, invalid links and manual fallback retained');

const handlers = {}, lifecycle = {};
const submitButton = {textContent: 'Save new password', disabled: false};
vm.runInNewContext(source, {
  URLSearchParams,
  document: {getElementById: () => null, querySelector: () => ({
    querySelector: () => submitButton, addEventListener: (name, fn) => handlers[name] = fn
  })},
  window: {addEventListener: (name, fn) => lifecycle[name] = fn}
});
let prevented = 0;
const submit = () => handlers.submit({preventDefault: () => prevented++});
submit();
assert.equal(prevented, 0);
assert.equal(submitButton.disabled, true);
submit();
assert.equal(prevented, 1);
lifecycle.pageshow({persisted: true}); // Safari back/forward-cache restoration.
assert.equal(submitButton.disabled, false);
assert.equal(submitButton.textContent, 'Save new password');
submit();
assert.equal(prevented, 1); // A restored page remains usable.
console.log('PASS: duplicate reset submissions blocked; back/forward restoration unlocks controls');

const loginTemplate = fs.readFileSync(path.join(__dirname, 'templates/staff_employee_login.html'), 'utf8');
const dialogScript = loginTemplate.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
const dialogEvents = {}, helpEvents = {};
let focusTarget;
const gotIt = {focus: () => focusTarget = 'got-it'};
const help = {addEventListener: (name, fn) => helpEvents[name] = fn, focus: () => focusTarget = 'help'};
const dialog = {
  open: false, showModal() {this.open = true; gotIt.focus();},
  close() {this.open = false; dialogEvents.close();},
  addEventListener: (name, fn) => dialogEvents[name] = fn,
  querySelector: () => gotIt,
  getBoundingClientRect: () => ({left: 20, right: 340, top: 100, bottom: 400})
};
vm.runInNewContext(dialogScript, {document: {getElementById: id => id === 'password-help' ? help : dialog}});
helpEvents.click();assert.equal(dialog.open, true);assert.equal(focusTarget, 'got-it');
for (const shiftKey of [false, true]) {
  let trapped = false;
  dialogEvents.keydown({key: 'Tab', shiftKey, preventDefault: () => trapped = true});
  assert.equal(trapped, true);assert.equal(focusTarget, 'got-it');
}
dialogEvents.keydown({key: 'Escape', preventDefault: () => assert.fail('Native Escape must remain enabled')});
dialogEvents.click({target: dialog, clientX: 30, clientY: 110});assert.equal(dialog.open, true);
dialogEvents.click({target: dialog, clientX: 1, clientY: 1});
assert.equal(dialog.open, false);assert.equal(focusTarget, 'help');
console.log('PASS: employee help dialog opens, contains keyboard focus, preserves Escape and dismisses outside with focus return');
