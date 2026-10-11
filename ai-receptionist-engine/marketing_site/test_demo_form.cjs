// No network or browser required: challenge callbacks and double-submit UI guard.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, 'demo.html'), 'utf8');
const source = html.match(/<script>\s*(function demoVerified[\s\S]*?)<\/script>/)[1];
const button = {disabled: true};
let submit;
const context = vm.createContext({document: {
  getElementById: id => { assert.equal(id, 'demo-submit'); return button; },
  querySelector: selector => ({addEventListener: (event, callback) => {
    assert.equal(selector, 'form[action="/demo"]');
    assert.equal(event, 'submit');
    submit = callback;
  }})
}});
vm.runInContext(source, context);
assert.equal(button.disabled, true);
context.demoVerified('local-token');
assert.equal(button.disabled, false);
context.demoExpired();
assert.equal(button.disabled, true);
context.demoVerified('new-local-token');
submit();
assert.equal(button.disabled, true);
assert.match(html, /data-error-callback="demoExpired"/);
assert.match(html, /data-expired-callback="demoExpired"/);
console.log('PASS: submit disabled until verification; expiry, errors and submission disable it again');
