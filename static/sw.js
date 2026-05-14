// Visionary Service Worker
// 策略:
//   靜態資源 → stale-while-revalidate
//   /api/papers, /api/trending → SWR + 背景刷新後 postMessage 通知前端
//   其他 /api/* → 不快取
const VERSION = 'v8';
const STATIC_CACHE = `visionary-static-${VERSION}`;
const API_CACHE    = `visionary-api-${VERSION}`;
const STATIC_ASSETS = [
    '/',
    '/static/style.css',
    '/static/washi.css',
    '/static/script.js',
    '/static/auth.js',
    '/static/value-metrics.js',
    '/static/disciplines.js',
    '/static/index.html',
    '/static/manifest.json',
    '/static/og-image.svg',
];

const SWR_API_PATHS = ['/api/papers', '/api/trending'];

self.addEventListener('install', (e) => {
    e.waitUntil(
        caches.open(STATIC_CACHE).then(c => c.addAll(STATIC_ASSETS)).catch(() => {})
    );
    self.skipWaiting();
});

self.addEventListener('activate', (e) => {
    e.waitUntil(
        caches.keys().then(keys =>
            Promise.all(
                keys.filter(k => k !== STATIC_CACHE && k !== API_CACHE).map(k => caches.delete(k))
            )
        )
    );
    self.clients.claim();
});

async function broadcast(msg) {
    const clients = await self.clients.matchAll({ includeUncontrolled: true, type: 'window' });
    for (const c of clients) c.postMessage(msg);
}

async function apiSWR(req, url) {
    const cache = await caches.open(API_CACHE);
    const cached = await cache.match(req);

    const networkPromise = fetch(req).then(async (resp) => {
        // 304 (ETag 命中) → 不更新 cache,沿用舊版本
        if (resp && resp.status === 200) {
            try {
                await cache.put(req, resp.clone());
                broadcast({ type: 'api-updated', path: url.pathname, search: url.search });
            } catch (err) {
                // QuotaExceededError → 清掉最舊的一半項目再試一次
                if (err && (err.name === 'QuotaExceededError' || /quota/i.test(err.message || ''))) {
                    try {
                        const keys = await cache.keys();
                        const drop = Math.max(1, Math.floor(keys.length / 2));
                        await Promise.all(keys.slice(0, drop).map(k => cache.delete(k)));
                        await cache.put(req, resp.clone());
                        broadcast({ type: 'api-updated', path: url.pathname, search: url.search });
                    } catch (_) { /* give up */ }
                }
            }
        }
        return resp;
    }).catch(() => null);

    if (cached) {
        // 不 await network → 立刻回 cache,網路在背景刷新
        networkPromise;
        return cached;
    }
    // 沒 cache 才等網路
    const fresh = await networkPromise;
    return fresh || new Response('{"papers":[]}', {
        status: 503,
        headers: { 'Content-Type': 'application/json' },
    });
}

async function staticSWR(req) {
    const cache = await caches.open(STATIC_CACHE);
    const cached = await cache.match(req);
    const fetchPromise = fetch(req).then(resp => {
        if (resp && resp.ok) cache.put(req, resp.clone()).catch(() => {});
        return resp;
    }).catch(() => cached);
    return cached || fetchPromise;
}

self.addEventListener('fetch', (e) => {
    const req = e.request;
    if (req.method !== 'GET') return;
    const url = new URL(req.url);
    if (url.origin !== location.origin) return;

    if (url.pathname.startsWith('/api/')) {
        if (SWR_API_PATHS.includes(url.pathname)) {
            e.respondWith(apiSWR(req, url));
        }
        // 其餘 /api/* 不攔截(由 browser 直連)
        return;
    }

    e.respondWith(staticSWR(req));
});
