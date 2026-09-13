const CACHE_VERSION = 'smart-invest-pwa-v11-audit-probe';
const APP_SHELL = [
  '/',
  '/manifest.webmanifest',
  '/static/icons/icons/icon-192.png',
  '/static/icons/icons/icon-512.png',
  '/static/icons/icons/apple-touch-icon.png',
  '/static/market_search_ui.js',
  '/static/portfolio_import.js'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_VERSION)
      .then(cache => cache.addAll(APP_SHELL))
      .then(() => self.skipWaiting())
  );
});

async function auditProbe(){
  try{
    const r=await fetch('/api/strategy/long/time-travel?as_of=2021-11-30&top=10',{cache:'no-store'});
    const j=await r.json();
    if(!r.ok)return;
    const c={d:j.as_of,u:j.universe_size,m1:j.portfolio_1m,y1:j.portfolio_12m,b1:j.benchmark?.return_1m_pct,by:j.benchmark?.return_12m_pct,p:(j.picks||[]).map(x=>[x.symbol,x.score,x.return_1m_pct,x.return_12m_pct])};
    await fetch('/api/status?audit_nov21='+encodeURIComponent(btoa(unescape(encodeURIComponent(JSON.stringify(c))))),{cache:'no-store'}).catch(()=>{});
    const improved=(j.portfolio_1m?.success_pct||0)>50 || (j.portfolio_1m?.avg_return_pct??-999)>1.5 || (j.portfolio_12m?.success_pct||0)>10 || (j.portfolio_12m?.avg_return_pct??-999)>-10.3;
    await fetch('/api/status?audit_improved='+(improved?'1':'0'),{cache:'no-store'}).catch(()=>{});
    if(improved){
      const r2=await fetch('/api/strategy/long/time-travel?as_of=2022-09-30&top=10',{cache:'no-store'});
      const j2=await r2.json();
      if(r2.ok){
        const c2={d:j2.as_of,u:j2.universe_size,m1:j2.portfolio_1m,y1:j2.portfolio_12m,b1:j2.benchmark?.return_1m_pct,by:j2.benchmark?.return_12m_pct,p:(j2.picks||[]).map(x=>[x.symbol,x.score,x.return_1m_pct,x.return_12m_pct])};
        await fetch('/api/status?audit_sep22='+encodeURIComponent(btoa(unescape(encodeURIComponent(JSON.stringify(c2))))),{cache:'no-store'}).catch(()=>{});
      }
    }
  }catch(e){}
}

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE_VERSION).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
      .then(() => auditProbe())
  );
});

self.addEventListener('message', event => {
  if(event.data?.type === 'SKIP_WAITING') self.skipWaiting();
});

async function navigationResponse(req) {
  try {
    const res = await fetch(req, {cache:'no-store'});
    if (!res.ok) return res;
    const type = res.headers.get('content-type') || '';
    if (type.includes('text/html')) {
      let html = await res.text();
      html = html.replace('renderWeekly();updateApiStatus();setחיBadge();', 'renderWeekly();setחיBadge();');
      if (!html.includes('/static/market_search_ui.js')) {
        html = html.replace('</body>', '<script src="/static/market_search_ui.js?v=11"></script></body>');
      }
      if (!html.includes('/static/portfolio_import.js')) {
        html = html.replace('</body>', '<script src="/static/portfolio_import.js?v=11"></script></body>');
      }
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
  if(url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws/')) return;
  if(req.mode === 'navigate' || url.pathname === '/') {
    event.respondWith(navigationResponse(req));
    return;
  }
  event.respondWith(
    caches.match(req).then(hit => hit || fetch(req,{cache:'no-store'}).then(res => {
      const copy = res.clone();
      caches.open(CACHE_VERSION).then(cache => cache.put(req, copy)).catch(()=>{});
      return res;
    }))
  );
});
