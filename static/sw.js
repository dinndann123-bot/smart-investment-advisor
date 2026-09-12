const CACHE_VERSION = 'smart-invest-pwa-v2-brand-install';
const APP_SHELL = [
  '/',
  '/manifest.webmanifest',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/apple-touch-icon.png'
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_VERSION).then(cache => cache.addAll(APP_SHELL)));
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

self.addEventListener('fetch', event => {
  const req = event.request;
  const url = new URL(req.url);
  if(req.method !== 'GET' || url.origin !== self.location.origin) return;

  // Never cache market/API data. Fresh data must always come from the server.
  if(url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws/')) return;

  // HTML/navigation is network-first, so a deployed UI update appears on refresh.
  if(req.mode === 'navigate' || url.pathname === '/') {
    event.respondWith(
      fetch(req, {cache:'no-store'})
        .then(res => res)
        .catch(() => caches.match('/') || new Response('Offline', {status:503}))
    );
    return;
  }

  // Small static shell can be cached; the service worker version controls replacement.
  event.respondWith(caches.match(req).then(hit => hit || fetch(req)));
});
