'use strict';
const requestId = new URLSearchParams(location.hash.slice(1)).get('request') || '';
history.replaceState(null, '', location.pathname);
const form = document.querySelector('form');
const status = document.getElementById('status');
if (/^[A-Za-z0-9_-]{43}$/.test(requestId)) {
  fetch('/preview', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({id:requestId})})
    .then(response => {if (!response.ok) throw Error(); return response.json();})
    .then(data => {
      status.textContent = data.summary;
      form.elements.id.value = requestId;
      form.hidden = false;
    })
    .catch(() => { status.textContent = 'This request is unavailable. Ask the bot for a new link.'; });
}
