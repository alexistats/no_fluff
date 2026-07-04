// NoFluff service worker.
// Bump VERSION when the cached shell/assets should be refreshed (see README).
const VERSION = 'v1';
const CACHE = `nofluff-${VERSION}`;
const OFFLINE_URL = '/offline';

// Precache the offline fallback page.
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches
            .open(CACHE)
            .then((cache) => cache.add(OFFLINE_URL))
            .then(() => self.skipWaiting())
    );
});

// Drop caches from older versions, then take control of open pages.
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches
            .keys()
            .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
            .then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', (event) => {
    const req = event.request;
    if (req.method !== 'GET') return; // never intercept logging/planning POSTs
    const url = new URL(req.url);
    if (url.origin !== self.location.origin) return;

    // Versioned static assets: cache-first (they change URL when they change).
    if (url.pathname.startsWith('/static/')) {
        event.respondWith(
            caches.open(CACHE).then((cache) =>
                cache.match(req).then(
                    (hit) =>
                        hit ||
                        fetch(req).then((res) => {
                            if (res.ok) cache.put(req, res.clone());
                            return res;
                        })
                )
            )
        );
        return;
    }

    // Page navigations: network-first, fall back to the offline page. Nothing
    // authenticated is cached, so this is safe on a shared device.
    if (req.mode === 'navigate') {
        event.respondWith(fetch(req).catch(() => caches.match(OFFLINE_URL)));
    }
});
