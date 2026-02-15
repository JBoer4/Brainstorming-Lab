const CACHE_NAME = 'budget-app-v5';
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
  '/js/components/Dashboard.js',
  '/js/components/BudgetHome.js',
  '/js/components/DailyLog.js',
  '/js/components/Categories.js',
  '/js/components/History.js',
];

const CDN_URLS = [
  'https://esm.sh/preact@10.25.4',
  'https://esm.sh/preact@10.25.4/hooks',
  'https://esm.sh/htm@3.1.1/preact?external=preact',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(async (cache) => {
      await cache.addAll(ASSETS);
      // Cache CDN separately — don't block install on CDN failure
      for (const url of CDN_URLS) {
        try { await cache.add(url); } catch {}
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

  // Let API requests go straight to network
  if (url.pathname.startsWith('/api/')) return;

  // SPA fallback: non-asset navigation requests get index.html
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(() => caches.match('/index.html'))
    );
    return;
  }

  // Stale-while-revalidate for everything else
  event.respondWith(
    caches.match(event.request).then((cached) => {
      const fetchPromise = fetch(event.request).then((res) => {
        if (res.ok) {
          const clone = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return res;
      }).catch(() => cached);

      return cached || fetchPromise;
    })
  );
});
