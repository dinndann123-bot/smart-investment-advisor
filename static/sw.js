// V22 stability kill-switch Service Worker.
// The previous worker modified navigation HTML and injected multiple UX scripts.
// For production stabilization we deliberately remove all caches and unregister.
self.addEventListener('install', event => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    try {
      const keys = await caches.keys();
      await Promise.all(keys.map(key => caches.delete(key)));
      await self.registration.unregister();
      const clients = await self.clients.matchAll({type: 'window', includeUncontrolled: true});
      for (const client of clients) {
        try { client.postMessage({type: 'V22_SW_REMOVED'}); } catch (_) {}
      }
    } catch (_) {}
  })());
});

// Intentionally no fetch handler. Network requests and navigation go directly
// to FastAPI/browser networking and cannot be rewritten by this worker.
