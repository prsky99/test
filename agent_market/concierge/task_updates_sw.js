/* Purpose-scoped notifications. No session tokens or page caching in this worker. */
self.addEventListener('install', event => event.waitUntil(self.skipWaiting()));
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('push', event => {
  event.waitUntil((async () => {
    let data;
    try { data = event.data.json(); } catch (error) { return; }
    if (data?.type === 'browser_verification' && Number(data.expires_at) > Date.now()/1000 && /^tw_[0-9a-f]{32}$/.test(data.watch_id) && /^[A-Za-z0-9_-]{43}$/.test(data.challenge)) {
      await self.registration.showNotification('Confirm browser notifications', {
        body: 'Select this notification to confirm Agent Concierge updates. Choose Decline to delete the request.',
        tag: 'verify-' + data.watch_id,
        actions: [{action: 'confirm', title: 'Confirm notifications'}, {action: 'decline', title: 'Decline and delete'}],
        data: {type: 'browser_verification', watch_id: data.watch_id, challenge: data.challenge, expires_at: data.expires_at}
      });
    } else if (data?.type === 'task_update') {
      await self.registration.showNotification('Agent Concierge', {
        body: 'New verification is available for a task you follow.', tag: 'task-' + String(data.event_id || '').slice(0,80),
        data: {type: 'task_update'}
      });
    }
  })());
});
self.addEventListener('notificationclick', event => {
  const data = event.notification.data || {};
  event.notification.close();
  event.waitUntil((async () => {
    if (data.type === 'browser_verification') {
      const decision = event.action === 'decline' ? 'decline' : 'confirm';
      let state = 'unavailable';
      try {
        if (Number(data.expires_at) > Date.now()/1000) {
          const response = await fetch('/api/task-updates/browser-confirm', {
            method: 'POST', credentials: 'omit', cache: 'no-store', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({watch_id:data.watch_id,challenge:data.challenge,decision})
          });
          if (response.ok) state = (await response.json()).state;
        }
      } catch (error) {}
      const windows = await self.clients.matchAll({type:'window',includeUncontrolled:true});
      for (const client of windows) client.postMessage({type:'task-browser-check',watch_id:data.watch_id,state});
      if (decision === 'confirm' && state === 'active' && !windows.length) await self.clients.openWindow('/#cancellation');
    } else if (data.type === 'task_update') {
      await self.clients.openWindow('/#cancellation');
    }
  })());
});
