// Visionary Service Worker
// 策略：靜態資源 stale-while-revalidate；API 不快取（除 /api/me/config）
const VERSION = 'v1';
const STATIC_CACHE = `visionary-static-${VERSION}`;
const STATIC_ASSETS = [
    '/',
    '/static/style.css',
    '/static/script.js',
    '/static/auth.js',
    '/static/index.html',
    '/static/manifest.json',
];

self.addEventListener('install', (e) => {
    e.waitUntil(
        caches.open(STATIC_CACHE).then(c => c.addAll(STATIC_ASSETS)).catch(() => {})
    );
    self.skipWaiting();
});

self.addEventListener('activate', (e) => {
    e.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== STATIC_CACHE).map(k => caches.delete(k)))
        )
    );
    self.clients.claim();
});

self.addEventListener('fetch', (e) => {
    const req = e.request;
    if (req.method !== 'GET') return;
    const url = new URL(req.url);
    if (url.origin !== location.origin) return;

    // API 不快取（避免快取過期資料），只讓首頁/靜態檔離線可用
    if (url.pathname.startsWith('/api/')) return;

    e.respondWith((async () => {
        const cache = await caches.open(STATIC_CACHE);
        const cached = await cache.match(req);
        const fetchPromise = fetch(req).then(resp => {
            if (resp && resp.ok) cache.put(req, resp.clone()).catch(() => {});
            return resp;
        }).catch(() => cached);
        return cached || fetchPromise;
    })());
});
