const CACHE = 'whatzabi-pwa-v13';

const ASSETS = [
  '/auth/app?v=8',
  '/auth/styles.css?v=8',
  '/auth/app.js?v=8',
  '/auth/smart-catalog.js?v=13',
  '/auth/manifest.webmanifest',
  '/auth/icon.svg',
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))).then(() => self.clients.claim()));
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.pathname.startsWith('/pwa/') || url.pathname === '/auth/me') return;

  if (url.pathname === '/auth/app.js') {
    event.respondWith(Promise.all([
      fetch(event.request, { cache: 'no-store' }),
      fetch('/auth/smart-catalog.js?v=13', { cache: 'no-store' }),
    ]).then(async ([appResponse, scannerResponse]) => {
      if (!appResponse.ok) return appResponse;
      const appCode = await appResponse.text();
      const scannerCode = scannerResponse.ok ? await scannerResponse.text() : '';
      return new Response(`${appCode}\n${scannerCode}`, { status: 200, headers: { 'Content-Type': 'application/javascript; charset=utf-8', 'Cache-Control': 'no-store' } });
    }).catch(() => caches.match(event.request)));
    return;
  }

  if (url.pathname === '/auth/app' || url.pathname === '/auth/styles.css') {
    event.respondWith(fetch(event.request, { cache: 'no-store' }).then((response) => {
      if (response.ok) { const copy = response.clone(); caches.open(CACHE).then((cache) => cache.put(event.request, copy)); }
      return response;
    }).catch(() => caches.match(event.request)));
    return;
  }

  event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request).then((response) => {
    if (response.ok) { const copy = response.clone(); caches.open(CACHE).then((cache) => cache.put(event.request, copy)); }
    return response;
  })));
});