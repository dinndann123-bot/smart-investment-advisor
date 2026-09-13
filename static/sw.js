const CACHE_VERSION = 'smart-invest-pwa-v4-runtime-init-fix';
const APP_SHELL = [
  '/',
  '/manifest.webmanifest',
  '/static/icons/icons/icon-192.png',
  '/static/icons/icons/icon-512.png',
  '/static/icons/icons/apple-touch-icon.png'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_VERSION)
      .then(cache => cache.addAll(APP_SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE_VERSION).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('message', event => {
  if(event.data?.type === 'SKIP_WAITING') self.skipWaiting();
});

async function navigationResponse(req) {
  try {
    const res = await fetch(req, {cache:'no-store'});
    if (!res.ok) return res;

    // Temporary runtime repair for the current UI bundle: an old initializer
    // still calls updateApiStatus(), which no longer exists. That ReferenceError
    // aborts the rest of startup (backend status, clocks, health polling, etc.).
    // Remove only that stale call while preserving the real checkBackendStatus().
    const type = res.headers.get('content-type') || '';
    if (type.includes('text/html')) {
      let html = await res.text();
      html = html.replace('renderWeekly();updateApiStatus();setחיBadge();', 'renderWeekly();setחיBadge();');
      const headers = new Headers(res.headers);
      headers.set('Cache-Control', 'no-cache, no-store, must-revalidate');
      headers.delete('content-length');
      return new Response(html, {status: res.status, statusText: res.statusText, headers});
    }
    return res;
  } catch (e) {
    return (await caches.match('/')) || new Response('Offline', {status:503});
  }
}

self.addEventListener('fetch', event => {
  const req = event.request;
  const url = new URL(req.url);
  if(req.method !== 'GET' || url.origin !== self.location.origin) return;

  // Never cache market/API data. Fresh data must always come from the server.
  if(url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws/')) return;

  // HTML/navigation is network-first, so deployed UI updates appear immediately.
  if(req.mode === 'navigate' || url.pathname === '/') {
    event.respondWith(navigationResponse(req));
    return;
  }

  // Small static shell can be cached; version changes replace old cached assets.
  event.respondWith(
    caches.match(req).then(hit => hit || fetch(req).then(res => {
      const copy = res.clone();
      caches.open(CACHE_VERSION).then(cache => cache.put(req, copy)).catch(()=>{});
      return res;
    }))
  );
});
