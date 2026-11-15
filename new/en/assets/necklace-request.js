// Necklace request status (11-15): reads the request number from the address fragment, which the browser never sends,
// and posts it; every value from the server is set as text.
(function () {
  var id = decodeURIComponent((location.hash || '').slice(1));
  var note = document.getElementById('nrStatusNote');
  if (!note) return;
  if (!/^inq_[A-Za-z0-9_-]{24}$/.test(id)) { note.textContent = 'This address has no request number after #.'; return; }
  fetch('/api/necklace-requests/status', {method: 'POST', credentials: 'omit', cache: 'no-store',
    headers: {'content-type': 'application/json'}, body: JSON.stringify({request_id: id})})
    .then(function (r) { return r.json().then(function (d) { return [r.ok, d]; }); })
    .then(function (pair) {
      var d = pair[1];
      if (!pair[0] || !d.ok) { note.textContent = 'We could not find this request.'; return; }
      note.textContent = d.note;
      var list = document.getElementById('nrStatus');
      [['Received', d.received_at], ['Task', d.task], ['Example input', d.example_input], ['Wanted output', d.wanted_output]]
        .forEach(function (row) {
          var dt = document.createElement('dt'), dd = document.createElement('dd');
          dt.textContent = row[0]; dd.textContent = row[1] || ''; list.append(dt, dd);
        });
      list.hidden = false;
      if (d.answer) { document.getElementById('nrAnswerText').textContent = d.answer; document.getElementById('nrAnswerBox').hidden = false; }
    })
    .catch(function () { note.textContent = 'We could not load this request. Try again in a minute.'; });
})();
