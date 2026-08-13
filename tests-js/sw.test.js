'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const sourcePath = path.resolve(__dirname, '..', 'static', 'sw.js');

function requestKey(request) {
    return typeof request === 'string' ? request : request.url;
}

function createCaches() {
    const stores = new Map();

    function createCache() {
        const responses = new Map();
        return {
            async match(request) {
                const response = responses.get(requestKey(request));
                return response ? response.clone() : undefined;
            },
            async put(request, response) {
                responses.set(requestKey(request), response.clone());
            },
            async delete(request) {
                return responses.delete(requestKey(request));
            },
            async keys() {
                return [...responses.keys()].map((url) => new Request(url));
            },
        };
    }

    return {
        async open(name) {
            if (!stores.has(name)) stores.set(name, createCache());
            return stores.get(name);
        },
        async keys() {
            return [...stores.keys()];
        },
        async delete(name) {
            return stores.delete(name);
        },
    };
}

function createWorker(fetchImpl) {
    const handlers = {};
    const messages = [];
    const caches = createCaches();
    const self = {
        addEventListener(type, handler) {
            handlers[type] = handler;
        },
        skipWaiting() {},
        clients: {
            async matchAll() {
                return [{ postMessage(message) { messages.push(message); } }];
            },
            claim() {},
        },
    };
    const sandbox = {
        self,
        caches,
        fetch: fetchImpl,
        Headers,
        Request,
        Response,
        URL,
        location: { origin: 'https://scholarly.test' },
    };
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync(sourcePath, 'utf8'), sandbox, { filename: sourcePath });
    return {
        apiCache: vm.runInContext('API_CACHE', sandbox),
        staticCache: vm.runInContext('STATIC_CACHE', sandbox),
        handlers,
        messages,
        caches,
    };
}

function dispatchFetch(worker, pathname) {
    const event = {
        request: new Request(`https://scholarly.test${pathname}`),
        waitUntilCalls: [],
        respondWith(response) {
            this.responsePromise = Promise.resolve(response);
        },
        waitUntil(promise) {
            this.waitUntilCalls.push(Promise.resolve(promise));
        },
    };
    worker.handlers.fetch(event);
    return event;
}

test('metrics and unknown same-origin requests bypass the service worker', () => {
    const worker = createWorker(async () => new Response('network'));

    for (const pathname of ['/metrics', '/api/metrics', '/robots.txt', '/sitemap.xml', '/sw.js', '/unknown']) {
        const event = dispatchFetch(worker, pathname);
        assert.equal(event.responsePromise, undefined, pathname);
    }
});

test('unchanged API ETags do not broadcast an update and use conditional revalidation', async () => {
    let networkRequest;
    const worker = createWorker(async (request) => {
        networkRequest = request;
        return new Response('fresh', { headers: { ETag: '"same"' } });
    });
    const request = new Request('https://scholarly.test/api/papers?discipline=cv');
    const cache = await worker.caches.open(worker.apiCache);
    await cache.put(request, new Response('cached', { headers: { ETag: '"same"' } }));

    const event = dispatchFetch(worker, '/api/papers?discipline=cv');
    const response = await event.responsePromise;
    assert.equal(await response.text(), 'cached');
    assert.equal(event.waitUntilCalls.length, 1);
    await Promise.all(event.waitUntilCalls);
    assert.equal(networkRequest.headers.get('If-None-Match'), '"same"');
    assert.deepEqual(worker.messages, []);
});

test('changed API ETags broadcast exactly one update after caching', async () => {
    const worker = createWorker(async () => new Response('fresh', { headers: { ETag: '"new"' } }));
    const request = new Request('https://scholarly.test/api/papers?discipline=cv');
    const cache = await worker.caches.open(worker.apiCache);
    await cache.put(request, new Response('cached', { headers: { ETag: '"old"' } }));

    const event = dispatchFetch(worker, '/api/papers?discipline=cv');
    await event.responsePromise;
    assert.equal(event.waitUntilCalls.length, 1);
    await Promise.all(event.waitUntilCalls);
    assert.equal(worker.messages.length, 1);
    assert.equal(worker.messages[0].type, 'api-updated');
    assert.equal(worker.messages[0].path, '/api/papers');
    assert.equal(worker.messages[0].search, '?discipline=cv');
});

test('cached static assets register their revalidation with waitUntil', async () => {
    let resolveNetwork;
    const worker = createWorker(() => new Promise((resolve) => { resolveNetwork = resolve; }));
    const request = new Request('https://scholarly.test/static/script.js');
    const cache = await worker.caches.open(worker.staticCache);
    await cache.put(request, new Response('cached'));

    const event = dispatchFetch(worker, '/static/script.js');
    const response = await event.responsePromise;
    assert.equal(await response.text(), 'cached');
    assert.equal(event.waitUntilCalls.length, 1);

    resolveNetwork(new Response('fresh'));
    await Promise.all(event.waitUntilCalls);
    const refreshed = await cache.match(request);
    assert.equal(await refreshed.text(), 'fresh');
});
