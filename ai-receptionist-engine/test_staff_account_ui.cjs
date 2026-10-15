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
    document: {getElementById: () => hasField ? field : null},
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
