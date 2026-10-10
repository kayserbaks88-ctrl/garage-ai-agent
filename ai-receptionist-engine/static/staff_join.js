'use strict';
const joiningForm = document.getElementById('joining-form');
if (joiningForm) {
  const field = joiningForm.elements.token;
  const preview = async () => {
    const label = document.getElementById('joining-company');
    const requestedToken = field.value;
    if (!/^[A-Za-z0-9_-]{43}$/.test(requestedToken)) {
      label.textContent = 'Enter the complete joining code from your employer.';
      return;
    }
    label.textContent = 'Checking company…';
    try {
      const body = new URLSearchParams({token: requestedToken, csrf_token: joiningForm.elements.csrf_token.value});
      const response = await fetch(joiningForm.dataset.previewUrl, {method: 'POST', body, credentials: 'same-origin'});
      const result = await response.json();
      if (field.value !== requestedToken) return;
      label.textContent = response.ok ? 'Joining ' + result.company : (result.error || 'Unable to check this joining link.');
    } catch (_) { if (field.value === requestedToken) label.textContent = 'Unable to check the company. Please retry before registering.'; }
  };
  field.addEventListener('change', preview);
  preview();
}
document.querySelectorAll('[data-copy-joining]').forEach(button => {
  button.addEventListener('click', async () => {
    const field = document.getElementById('joining-url');
    try { await navigator.clipboard.writeText(field.value); button.textContent = 'Copied'; }
    catch (_) { field.focus(); field.select(); button.textContent = 'Select and copy the link'; }
  });
});
