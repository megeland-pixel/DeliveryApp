const CACHE = 'delivery-v6';
const PRECACHE = [
    '/static/css/style.css',
    '/static/images/usa_LOGO_Transparent.png',
    '/static/images/truckLogo.png',
    '/static/images/icon-192.png',
    '/static/images/icon-512.png',
    '/static/manifest.json',
];

self.addEventListener('install', e => {
    e.waitUntil(caches.open(CACHE).then(c => c.addAll(PRECACHE)));
    self.skipWaiting();
});

self.addEventListener('activate', e => {
    e.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
        )
    );
    self.clients.claim();
});

self.addEventListener('fetch', e => {
    const url = new URL(e.request.url);

    // Always go to the network for HTML pages and API calls — never serve stale
    if (e.request.mode === 'navigate' || url.pathname.startsWith('/api/')) {
        e.respondWith(fetch(e.request));
        return;
    }

    // Cache-first only for static assets under /static/
    if (url.pathname.startsWith('/static/')) {
        e.respondWith(
            caches.match(e.request).then(cached => {
                if (cached) return cached;
                return fetch(e.request).then(res => {
                    if (res.ok) {
                        const clone = res.clone();
                        caches.open(CACHE).then(c => c.put(e.request, clone));
                    }
                    return res;
                });
            })
        );
        return;
    }

    // Everything else: network only
    e.respondWith(fetch(e.request));
});
