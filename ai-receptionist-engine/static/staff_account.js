// Email tokens stay in the fragment, outside server logs and referrers.
'use strict';
const tokenField = document.getElementById('token');
if (tokenField && window.location.hash) {
  const token = new URLSearchParams(window.location.hash.slice(1)).get('token');
  window.history.replaceState(null, '', window.location.pathname);
  if (token && /^[A-Za-z0-9_-]{43}$/.test(token)) tokenField.value = token;
}
