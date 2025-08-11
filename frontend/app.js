async function fetchJSON(url, options = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error('HTTP ' + res.status + ' ' + res.statusText + ' — ' + text);
  }
  return res.json();
}

document.addEventListener('DOMContentLoaded', function () {
  const providersForm = document.getElementById('providers-form');
  const providersResults = document.getElementById('providers-results');
  const askForm = document.getElementById('ask-form');
  const askResult = document.getElementById('ask-result');

  providersForm.addEventListener('submit', async function (e) {
    e.preventDefault();
    providersResults.textContent = 'Loading...';
    const drg = document.getElementById('drg').value.trim();
    const zip = document.getElementById('zip').value.trim();
    const radius = document.getElementById('radius').value.trim();
    const params = new URLSearchParams({ drg: drg, zip: zip, radius_km: radius || '40' });
    try {
      const data = await fetchJSON('/providers?' + params.toString());
      providersResults.textContent = JSON.stringify(data, null, 2);
    } catch (err) {
      providersResults.textContent = String(err);
    }
  });

  askForm.addEventListener('submit', async function (e) {
    e.preventDefault();
    askResult.textContent = 'Loading...';
    const question = document.getElementById('question').value.trim();
    try {
      const data = await fetchJSON('/ask', {
        method: 'POST',
        body: JSON.stringify({ question: question }),
      });
      askResult.textContent = JSON.stringify(data, null, 2);
    } catch (err) {
      askResult.textContent = String(err);
    }
  });
});


