const CACHE = 'whatzabi-pwa-v71-commercial-20261117';
const ASSETS = [
  '/auth/express-sale.css?v=2-cart-price-1',
  '/auth/app',
  '/auth/styles.css?v=34-commercial-20261117',
  '/auth/app.js?v=54-commercial-20261117',
  '/auth/offline-sales.js?v=4-commercial-20261117',
  '/auth/express-sale.js?v=18-commercial-20261117',
  '/auth/smart-catalog.js?v=47-auth-rc1-20261115',
  '/auth/quick-auth.js?v=2',
  '/auth/passkeys.js?v=1',
  '/auth/purchases.js?v=16-commercial-20261117',
  '/auth/manifest.webmanifest',
  '/auth/icon.svg',
];


// CacheStorage is only an asset store. Never touch IndexedDB or client outboxes.
function generation(name) {
  const match = /^whatzabi-pwa-v(\d+)-/.exec(name);
  return match ? Number(match[1]) : null;
}
const GENERATION = generation(CACHE);

async function pruneObsoleteAssets() {
  const keys = await caches.keys();
  await Promise.all(keys.filter(key => {
    const version = generation(key);
    return version !== null && version < GENERATION;
  }).map(key => caches.delete(key)));
}

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    // Corrected releases never replace a newer installed generation.
    // Operational rollback must also keep this worker (legacy code lacks this guard).
    if ((await caches.keys()).some(key => generation(key) > GENERATION)) {
      throw new Error('Refusing obsolete worker: newer generation exists');
    }
    try {
      const cache = await caches.open(CACHE);
      await cache.addAll(ASSETS.map(url =>
        new Request(new URL(url, self.location.origin), { cache: 'reload' })
      ));
    } catch (error) {
      await caches.delete(CACHE);
      throw error;
    }
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    await pruneObsoleteAssets();
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (event) => {
  // A legacy worker can finish an untracked cache.put after our activation.
  // Sweep again on controlled traffic; a stale cache is NEVER used for fallback.
  const cleanup = pruneObsoleteAssets();
  event.waitUntil(cleanup);
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin ||
      event.request.headers.has('Authorization') ||
      url.pathname.startsWith('/auth/quick/') || url.pathname === '/auth/passkeys' ||
      url.pathname.startsWith('/auth/passkeys/') ||
      !ASSETS.includes(url.pathname + url.search)) {
    return;
  }
  event.respondWith((async () => {
    try {
      // Precache is immutable for this generation: no asynchronous runtime writes
      // that could resurrect a retired worker's cache or mix asset generations.
      return await fetch(event.request, { cache: 'no-store' });
    } catch (error) {
      const cached = await caches.match(event.request, { cacheName: CACHE });
      if (cached) return cached;
      throw error;
    }
  })());
});
