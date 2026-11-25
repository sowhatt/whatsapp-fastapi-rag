const CACHE = 'whatzabi-merchant-shell-v2';
const STATIC = [
  '/merchant/assets/index.html', '/merchant/assets/offline.html', '/merchant/assets/styles.css',
  '/merchant/assets/app.js', '/merchant/assets/api.js', '/merchant/assets/store.js',
  '/merchant/assets/router.js', '/merchant/assets/push.js',
  '/merchant/assets/components/ui.js', '/merchant/assets/components/app-shell.js',
  '/merchant/assets/views/home.js', '/merchant/assets/views/orders.js',
  '/merchant/assets/views/notifications.js', '/merchant/assets/views/catalog.js', '/merchant/assets/views/module-placeholder.js',
  '/merchant/assets/assets/icon.svg', '/merchant/assets/assets/icon-192.png', '/merchant/assets/assets/icon-512.png',
  '/merchant/manifest.webmanifest'
];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(STATIC)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('whatzabi-merchant-shell-') && key !== CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  // Exact static allowlist only. APIs, Push endpoints, storefront and customer data
  // never reach respondWith or cache.put. Query-bearing requests are never cached.
  if (event.request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/merchant-api/') || url.pathname.startsWith('/online-admin/') || url.pathname.startsWith('/shop/')) return;
  if (!url.search && STATIC.includes(url.pathname)) {
    event.respondWith(caches.open(CACHE).then(cache => cache.match(url.pathname)).then(hit => hit || fetch(event.request)));
    return;
  }
  const shellRoute = /^\/merchant\/?$|^\/merchant\/(orders|notifications|catalog)$|^\/merchant\/module\/[a-z-]+$/.test(url.pathname);
  if (event.request.mode === 'navigate' && shellRoute) {
    // Do not cache the navigation response (including URLs with resource identifiers).
    event.respondWith(fetch(event.request).catch(async () => (await caches.match('/merchant/assets/index.html')) || caches.match('/merchant/assets/offline.html')));
  }
});
self.addEventListener('push', event => {
  let data = {};
  try { data = event.data?.json() || {}; } catch { /* Generic notification remains safe. */ }
  let url = '/merchant/notifications';
  const match = /^\/online-admin-ui#order-(\d+)$/.exec(data.url || '');
  if (match) url = `/merchant/orders?order_id=${match[1]}`;
  // Keep lock-screen content generic; resource access still requires the session.
  event.waitUntil(self.registration.showNotification('Whatzabi', {
    body:'Une nouvelle notification vous attend dans votre boutique.',
    icon:'/merchant/assets/assets/icon-192.png', data:{url}
  }));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const candidate = event.notification.data?.url || '';
  const url = /^\/merchant\/orders\?order_id=\d+$/.test(candidate) ? candidate : '/merchant/notifications';
  event.waitUntil(self.clients.openWindow(url));
});
