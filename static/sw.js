// Scholarly Service Worker
// 策略:
//   靜態資源 → stale-while-revalidate
//   /api/papers, /api/trending → SWR + 背景刷新後 postMessage 通知前端
//   其他路徑 → 由瀏覽器直接連線
const VERSION = 'v12';
const STATIC_CACHE = `scholarly-static-${VERSION}`;
const API_CACHE = `scholarly-api-${VERSION}`;
const STATIC_ASSETS = [
    '/',
    '/static/style.css',
    '/static/washi.css',
    '/static/app-utils.js',
    '/static/script.js',
    '/static/value-metrics.js',
    '/static/disciplines.js',
    '/static/index.html',
    '/static/manifest.json',
    '/static/og-image.svg',
];

const SWR_API_PATHS = ['/api/papers', '/api/trending'];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(STATIC_CACHE).then(cache => cache.addAll(STATIC_ASSETS)).catch(() => {})
    );
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(
                keys.filter(key => key !== STATIC_CACHE && key !== API_CACHE).map(key => caches.delete(key))
            )
        )
    );
    self.clients.claim();
});

async function broadcast(message) {
    const clients = await self.clients.matchAll({ includeUncontrolled: true, type: 'window' });
    for (const client of clients) client.postMessage(message);
}

function conditionalRequest(request, cached) {
    if (!cached) return request;
    const headers = new Headers(request.headers);
    const etag = cached.headers.get('ETag');
    const lastModified = cached.headers.get('Last-Modified');
    if (etag) headers.set('If-None-Match', etag);
    else if (lastModified) headers.set('If-Modified-Since', lastModified);
    return new Request(request, { headers });
}

async function cacheApiResponse(cache, request, response) {
    try {
        await cache.put(request, response.clone());
        return true;
    } catch (error) {
        if (!error || (error.name !== 'QuotaExceededError' && !/quota/i.test(error.message || ''))) {
            return false;
        }
        try {
            const keys = await cache.keys();
            const drop = Math.max(1, Math.floor(keys.length / 2));
            await Promise.all(keys.slice(0, drop).map(key => cache.delete(key)));
            await cache.put(request, response.clone());
            return true;
        } catch (_) {
            return false;
        }
    }
}

async function apiSWR(request, url, event) {
    const cache = await caches.open(API_CACHE);
    const cached = await cache.match(request);
    const cachedEtag = cached?.headers.get('ETag') || null;
    const networkRequest = conditionalRequest(request, cached);
    const networkPromise = fetch(networkRequest).then(async (response) => {
        if (response?.status === 304 && cached) return cached;
        if (response?.status === 200) {
            const stored = await cacheApiResponse(cache, request, response);
            const nextEtag = response.headers.get('ETag') || null;
            if (stored && (!cached || cachedEtag !== nextEtag)) {
                await broadcast({ type: 'api-updated', path: url.pathname, search: url.search });
            }
        }
        return response;
    }).catch(() => null);

    if (cached) {
        event.waitUntil(networkPromise);
        return cached;
    }
    const fresh = await networkPromise;
    return fresh || new Response('{"papers":[]}', {
        status: 503,
        headers: { 'Content-Type': 'application/json' },
    });
}

async function staticSWR(request, event) {
    const cache = await caches.open(STATIC_CACHE);
    const cached = await cache.match(request);
    const networkRequest = conditionalRequest(request, cached);
    const networkPromise = fetch(networkRequest).then(async (response) => {
        if (response?.status === 304 && cached) return cached;
        if (response?.ok) {
            try {
                await cache.put(request, response.clone());
            } catch (_) {}
        }
        return response;
    }).catch((error) => {
        if (cached) return cached;
        throw error;
    });

    if (cached) {
        event.waitUntil(networkPromise);
        return cached;
    }
    return networkPromise;
}

self.addEventListener('fetch', (event) => {
    const request = event.request;
    if (request.method !== 'GET') return;
    const url = new URL(request.url);
    if (url.origin !== location.origin) return;

    if (SWR_API_PATHS.includes(url.pathname)) {
        event.respondWith(apiSWR(request, url, event));
        return;
    }

    if (url.pathname === '/' || url.pathname.startsWith('/static/')) {
        event.respondWith(staticSWR(request, event));
    }
});
