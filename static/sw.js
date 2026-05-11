const CACHE = 'delivery-v9';
const PDF_CACHE = 'pdf-v1';
const DATA_CACHE = 'data-v1';
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
            Promise.all(keys.filter(k => k !== CACHE && k !== PDF_CACHE && k !== DATA_CACHE).map(k => caches.delete(k)))
        )
    );
    self.clients.claim();
});

self.addEventListener('fetch', e => {
    const url = new URL(e.request.url);

    // PDFs: cache-first in dedicated pdf cache
    if (url.pathname.startsWith('/pdf/')) {
        e.respondWith(
            caches.match(e.request).then(cached => {
                if (cached) return cached;
                return fetch(e.request).then(res => {
                    if (res.ok) caches.open(PDF_CACHE).then(c => c.put(e.request, res.clone()));
                    return res;
                });
            })
        );
        return;
    }

    // Static assets: cache-first in main cache
    if (url.pathname.startsWith('/static/')) {
        e.respondWith(
            caches.match(e.request).then(cached => {
                if (cached) return cached;
                return fetch(e.request).then(res => {
                    if (res.ok) caches.open(CACHE).then(c => c.put(e.request, res.clone()));
                    return res;
                });
            })
        );
        return;
    }

    // Schedule page: network-first, fall back to cached copy when offline
    if (url.pathname === '/schedule') {
        e.respondWith(
            fetch(e.request)
                .then(res => {
                    if (res.ok) caches.open(DATA_CACHE).then(c => c.put(e.request, res.clone()));
                    return res;
                })
                .catch(() => caches.match(e.request))
        );
        return;
    }

    // Order lines: cache-first (prefetched at login, static during a shift)
    if (url.pathname === '/api/order-lines') {
        e.respondWith(
            caches.match(e.request).then(cached => {
                if (cached) return cached;
                return fetch(e.request).then(res => {
                    if (res.ok) caches.open(DATA_CACHE).then(c => c.put(e.request, res.clone()));
                    return res;
                });
            })
        );
        return;
    }

    // Drive times and live ETA: network only, never cache
    if (url.pathname === '/api/eta' || url.pathname === '/api/stop-to-stop') {
        e.respondWith(fetch(e.request));
        return;
    }

    // Everything else (other pages, other API calls): network only
    e.respondWith(fetch(e.request));
});

self.addEventListener('push', event => {
    const data = event.data ? event.data.json() : {};
    const title = data.title || 'Delivery Alert';
    event.waitUntil(
        self.registration.showNotification(title, {
            body: data.body || '',
            icon: '/static/images/icon-192.png',
            badge: '/static/images/icon-192.png',
            data: data,
            tag: 'eta-alert',
            requireInteraction: true,
            actions: [
                { action: 'send_text',    title: data.send_label || 'Send Text' },
                { action: 'edit_message', title: 'Edit Message' },
            ],
        })
    );
});

self.addEventListener('notificationclick', event => {
    const data = event.notification.data || {};
    event.notification.close();

    if (event.action === 'send_text' && data.sms_data) {
        event.waitUntil(
            fetch('/api/send-sms', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data.sms_data),
            }).catch(() => {})
        );
    } else {
        // edit_message or tapping the notification body — open/focus the navigate page
        const target = (data.navigate_url || '/') + (event.action === 'edit_message' ? '&open_sms=1' : '');
        event.waitUntil(
            clients.matchAll({ type: 'window', includeUncontrolled: true }).then(wins => {
                for (const w of wins) {
                    if (w.url.includes('/navigate') && 'focus' in w) return w.focus();
                }
                return clients.openWindow(target);
            })
        );
    }
});
