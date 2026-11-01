'use strict';
(() => {
  const authorize = document.getElementById('authorize');
  const run = document.getElementById('run');
  const status = document.getElementById('status');
  authorize.addEventListener('change', () => { run.disabled = !authorize.checked; });
  document.getElementById('task').addEventListener('input', () => { authorize.checked = false; run.disabled = true; });
  run.addEventListener('click', async () => {
    if (run.disabled) return;
    run.disabled = true;
    run.setAttribute('aria-busy', 'true');
    run.textContent = 'Running preview…';
    status.textContent = 'Preparing the illustrative result…';
    try {
      await new Promise(resolve => setTimeout(resolve, 500));
      document.getElementById('result').hidden = false;
      status.textContent = 'Preview complete · No external agent was executed';
    } finally {
      run.removeAttribute('aria-busy');
      run.textContent = 'Run workflow';
      authorize.checked = false;
      run.disabled = true;
    }
  });
})();
