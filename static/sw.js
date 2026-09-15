// V23 production UI cache kill-switch.
// Always remove old application caches so the synchronized home/day-trading UI is visible immediately.
self.addEventListener('install', event => {
  event.waitUntil(self.skipWaiting());
});
self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    try {
      const keys = await caches.keys();
      await Promise.all(keys.map(key => caches.delete(key)));
      await self.registration.unregister();
      const clients = await self.clients.matchAll({type:'window',includeUncontrolled:true});
      for (const client of clients) {
        try { client.postMessage({type:'V23_SW_REMOVED'}); client.navigate(client.url); } catch (_) {}
      }
    } catch (_) {}
  })());
});
// No fetch handler: all UI/API traffic goes directly to the current Render deployment.
