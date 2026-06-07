// Service worker. Strategy: network-first with a cache fallback.
//  - Online  -> always fetch the latest files (and refresh the cache), so code
//    updates apply on a normal reload with no hard-refresh needed.
//  - Offline -> serve the last cached copy, so the installed app still runs with
//    no network.
const CACHE_NAME = 'sketchpad-v5';

const ASSETS = [
  './',
  './index.html',
  './style.css',
  './manifest.json',
  './icon.svg',
  './js/app.js',
  './js/canvas.js',
  './js/backgrounds.js',
  './js/storage.js',
  './js/pdf.js',
  './js/vendor/jspdf.umd.min.js',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(async (cache) => {
      for (const url of ASSETS) {
        try { await cache.add(url); }
        catch (e) { console.warn('SW: failed to cache', url, e.message); }
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
  const req = event.request;
  if (req.method !== 'GET') return;

  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res && res.ok) {
          const clone = res.clone();
          caches.open(CACHE_NAME).then((c) => c.put(req, clone));
        }
        return res;
      })
      .catch(async () => {
        const cached = await caches.match(req);
        if (cached) return cached;
        if (req.mode === 'navigate') return caches.match('./index.html');
        return Response.error();
      })
  );
});
