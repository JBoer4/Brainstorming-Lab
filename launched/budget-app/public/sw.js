const CACHE_NAME = 'budget-app-v9';
const ASSETS = [
  '/',
  '/index.html',
  '/style.css',
  '/manifest.json',
  '/icon.svg',
  '/js/app.js',
  '/js/router.js',
  '/js/db.js',
  '/js/sync.js',
  '/js/api.js',
  '/js/utils.js',
  '/js/vendor/preact.js',
  '/js/vendor/preact-hooks.js',
  '/js/vendor/htm.js',
  '/js/vendor/htm-preact.js',
  '/js/components/Dashboard.js',
  '/js/components/BudgetHome.js',
  '/js/components/DailyLog.js',
  '/js/components/Categories.js',
  '/js/components/History.js',
  '/js/components/MoneyHome.js',
  '/js/components/MoneyCategories.js',
  '/js/components/Transactions.js',
  '/js/components/ImportOFX.js',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(async (cache) => {
      // Cache each asset individually so one failure doesn't block the rest.
      // This is critical on LAN with self-signed certs where requests can be flaky.
      for (const url of ASSETS) {
        try {
          await cache.add(url);
        } catch (e) {
          console.warn('SW: failed to cache', url, e.message);
        }
      }
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Let API requests go straight to network (never cache)
  if (url.pathname.startsWith('/api/')) return;

  // For navigation requests: serve cached index.html (SPA shell),
  // update cache in background when online.
  if (event.request.mode === 'navigate') {
    event.respondWith(
      caches.match('/index.html').then((cached) => {
        // Always try to update in background
        const fetchPromise = fetch(event.request).then((res) => {
          if (res.ok) {
            const clone = res.clone();
            caches.open(CACHE_NAME).then((c) => c.put('/index.html', clone));
          }
          return res;
        }).catch(() => null);

        // Return cache immediately if available, otherwise wait for network
        return cached || fetchPromise;
      })
    );
    return;
  }

  // All other assets: cache-first, update in background (stale-while-revalidate)
  event.respondWith(
    caches.match(event.request).then((cached) => {
      const fetchPromise = fetch(event.request).then((res) => {
        if (res.ok) {
          const clone = res.clone();
          caches.open(CACHE_NAME).then((c) => c.put(event.request, clone));
        }
        return res;
      }).catch(() => null);

      // Return cache immediately if available, otherwise wait for network
      return cached || fetchPromise;
    })
  );
});
