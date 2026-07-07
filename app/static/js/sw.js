// NoFluff service worker.
// Bump VERSION when the cached shell/assets should be refreshed (see README).
const VERSION = 'v4';
const CACHE = `nofluff-${VERSION}`;
const RUNTIME = `nofluff-runtime-${VERSION}`;
const OFFLINE_URL = '/offline';

// Pages that must never land in the runtime cache: auth forms, settings (shows
// the API-key hint), the tokenized calendar feed, machine endpoints.
const NAV_EXCLUDE = [/^\/login/, /^\/register/, /^\/logout/, /^\/settings/, /^\/calendar\//, /^\/tasks\//, /^\/sync\//, /^\/sw\.js$/];

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
            .then((keys) =>
                Promise.all(keys.filter((k) => k !== CACHE && k !== RUNTIME).map((k) => caches.delete(k)))
            )
            .then(() => self.clients.claim())
    );
});

// The page asks for this on logout so personal pages don't outlive the session.
self.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'clear-runtime') {
        event.waitUntil(caches.delete(RUNTIME));
    }
});

// Background Sync (where supported): nudge any open page to flush the outbox.
// The page-side 'online' handler remains the baseline that works everywhere.
self.addEventListener('sync', (event) => {
    if (event.tag !== 'nofluff-sync') return;
    event.waitUntil(
        self.clients
            .matchAll({ type: 'window' })
            .then((clients) => clients.forEach((c) => c.postMessage({ type: 'do-sync' })))
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

    // Page navigations: network-first. Successful pages (minus the exclusion
    // list) are kept in a runtime cache so the gym floor works without signal;
    // on failure serve the cached copy, else the offline page. The runtime
    // cache holds personal content — the page clears it on logout.
    if (req.mode === 'navigate') {
        const cacheable = !NAV_EXCLUDE.some((re) => re.test(url.pathname));
        event.respondWith(
            fetch(req)
                .then((res) => {
                    if (res.ok && cacheable) {
                        const copy = res.clone();
                        caches.open(RUNTIME).then((cache) => cache.put(req, copy));
                    }
                    return res;
                })
                .catch(() =>
                    caches
                        .match(req, { cacheName: RUNTIME })
                        .then((hit) => hit || caches.match(OFFLINE_URL))
                )
        );
    }
});
