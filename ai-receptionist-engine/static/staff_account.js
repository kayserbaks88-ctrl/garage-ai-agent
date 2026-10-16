// Email tokens stay in the fragment, outside server logs and referrers.
'use strict';
const tokenField = document.getElementById('token');
if (tokenField && window.location.hash) {
  const token = new URLSearchParams(window.location.hash.slice(1)).get('token');
  window.history.replaceState(null, '', window.location.pathname);
  if (token && /^[A-Za-z0-9_-]{43}$/.test(token)) tokenField.value = token;
}
const resetForm = document.querySelector('[data-reset-form]');
if (resetForm) {
  const submitButton = resetForm.querySelector('button[type="submit"]');
  const originalLabel = submitButton.textContent;
  let submitting = false;
  resetForm.addEventListener('submit', event => {
    if (submitting) {
      event.preventDefault();
      return;
    }
    submitting = true;
    submitButton.disabled = true;
    submitButton.textContent = 'Updating password…';
  });
  // Safari can restore a form from its back/forward cache with disabled controls.
  window.addEventListener('pageshow', () => {
    submitting = false;
    submitButton.disabled = false;
    submitButton.textContent = originalLabel;
  });
}
if (tokenField && /^[A-Za-z0-9_-]{43}$/.test(tokenField.value)) {
  // Keep the submitted value while removing email-link details from password screens.
  const codeHelp = tokenField.closest('[data-email-code]');
  if (codeHelp) {
    tokenField.type = 'hidden';
    codeHelp.hidden = true;
  }
}
