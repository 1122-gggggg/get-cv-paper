import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const utilsPath = fileURLToPath(new URL("../static/app-utils.js", import.meta.url));
const scriptPath = fileURLToPath(new URL("../static/script.js", import.meta.url));

class MemoryStorage {
    constructor(entries = []) {
        this.values = new Map(entries);
    }

    get length() {
        return this.values.size;
    }

    key(index) {
        return [...this.values.keys()][index] ?? null;
    }

    getItem(key) {
        return this.values.has(key) ? this.values.get(key) : null;
    }

    setItem(key, value) {
        this.values.set(String(key), String(value));
    }

    removeItem(key) {
        this.values.delete(String(key));
    }
}

class OneShotFailingStorage extends MemoryStorage {
    constructor(entries, failingKey) {
        super(entries);
        this.failingKey = failingKey;
        this.failed = false;
    }

    setItem(key, value) {
        if (key === this.failingKey && !this.failed) {
            this.failed = true;
            throw new Error('Quota exceeded');
        }
        super.setItem(key, value);
    }
}

function loadUtils({ storage, unavailable = false } = {}) {
    const window = {};
    if (unavailable) {
        Object.defineProperty(window, 'localStorage', {
            get() {
                throw new Error('Storage unavailable');
            },
        });
    } else {
        window.localStorage = storage || new MemoryStorage();
    }
    const sandbox = { window, URL, TextEncoder, module: { exports: {} } };
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync(utilsPath, 'utf8'), sandbox, { filename: utilsPath });
    return { sandbox, utils: window.ScholarlyUtils };
}

function loadImportApi(storage) {
    const { sandbox } = loadUtils({ storage });
    sandbox.localStorage = storage;
    sandbox.window.DISCIPLINES = {
        cv: { topics: ['object detection'], confs: [{ key: 'cvpr' }] },
        nlp: { topics: ['language model'], confs: [{ key: 'acl' }] },
    };
    const source = fs.readFileSync(scriptPath, 'utf8');
    const end = source.indexOf('function bindStorageTools()');
    assert.notEqual(end, -1, 'import implementation anchor must exist');
    vm.runInContext(source.slice(0, end), sandbox, { filename: scriptPath });
    return sandbox;
}

function applyImportedState(sandbox, payload) {
    sandbox.__payload = JSON.stringify(payload);
    return vm.runInContext('_applyImportedUserState(JSON.parse(__payload))', sandbox);
}

function makePayload(localStorage) {
    return { app: 'Scholarly', version: 1, localStorage };
}

test('storage safely falls back when unavailable or JSON is corrupt', () => {
    const unavailable = loadUtils({ unavailable: true }).utils;
    assert.equal(unavailable.storage.get('missing'), null);
    assert.equal(unavailable.storage.set('key', 'value'), false);
    assert.equal(unavailable.storage.remove('key'), false);
    assert.deepEqual(unavailable.storage.readJson('key', ['fallback']), ['fallback']);

    const corruptStorage = new MemoryStorage([['corrupt', '{not json']]);
    const utils = loadUtils({ storage: corruptStorage }).utils;
    assert.deepEqual(utils.storage.readJson('corrupt', { safe: true }), { safe: true });
});

test('safeHttpUrl only accepts absolute credential-free HTTP(S) URLs', () => {
    const { utils } = loadUtils();
    assert.equal(utils.safeHttpUrl('https://example.test/paper?id=1'), 'https://example.test/paper?id=1');
    assert.equal(utils.safeHttpUrl('http://example.test/'), 'http://example.test/');

    for (const invalid of [
        '',
        '/relative',
        '//example.test/path',
        'javascript:alert(1)',
        'data:text/html,unsafe',
        'https://reader@example.test/paper',
        'https://reader:secret@example.test/paper',
        'https://',
    ]) {
        assert.equal(utils.safeHttpUrl(invalid), '', invalid);
    }
});

test('backup import validates shape, version, and byte limits before writing', () => {
    const storage = new MemoryStorage([['visionary_favorites', '["existing"]']]);
    const sandbox = loadImportApi(storage);
    const original = storage.getItem('visionary_favorites');

    assert.throws(
        () => applyImportedState(sandbox, makePayload({ visionary_favorites: '{"not":"an array"}' })),
        /格式/,
    );
    assert.equal(storage.getItem('visionary_favorites'), original);

    assert.throws(
        () => applyImportedState(sandbox, { app: 'Scholarly', version: 2, localStorage: {} }),
        /版本/,
    );
    assert.equal(storage.getItem('visionary_favorites'), original);

    const tooManyKeys = Object.fromEntries(
        Array.from({ length: 513 }, (_, index) => [`invalid_${index}`, 'x']),
    );
    assert.throws(() => applyImportedState(sandbox, makePayload(tooManyKeys)), /512/);

    assert.throws(
        () => applyImportedState(sandbox, makePayload({ visionary_favorites: 'x'.repeat(262145) })),
        /容量/,
    );

    const tooLargeOverall = Object.fromEntries(
        Array.from({ length: 21 }, (_, index) => [`invalid_${index}`, 'x'.repeat(250000)]),
    );
    assert.throws(() => applyImportedState(sandbox, makePayload(tooLargeOverall)), /總容量/);
    assert.equal(storage.getItem('visionary_favorites'), original);
});

test('backup import accepts only established state schemas', () => {
    const storage = new MemoryStorage();
    const sandbox = loadImportApi(storage);
    const payload = makePayload({
        visionary_favorites: '["https://example.test/paper"]',
        visionary_read_v1: '["https://example.test/paper"]',
        'visionary_pinned_topics:cv': '["object detection"]',
        'visionary_deleted_builtins:cv': '["legacy-topic"]',
        visionary_notes_v1: '{"https://example.test/paper":"note"}',
        'visionary_renamed_builtins:cv': '{"legacy-topic":"renamed topic"}',
        visionary_paper_tags_v1: '{"https://example.test/paper":["survey","benchmark"]}',
        visionary_sort_v3: 'hot',
        visionary_time_range_v1: 'week',
        visionary_semantic_on: '1',
        visionary_cross_disc_on: '0',
        visionary_discipline: 'cv',
        'visionary_last_category:cv': 'object detection',
    });

    assert.equal(applyImportedState(sandbox, payload), Object.keys(payload.localStorage).length);
    assert.equal(storage.getItem('visionary_sort_v3'), 'hot');
    assert.equal(storage.getItem('visionary_notes_v1'), '{"https://example.test/paper":"note"}');
});

test('backup import restores every affected key after a storage write failure', () => {
    const storage = new OneShotFailingStorage(
        [
            ['visionary_favorites', '["existing favorite"]'],
            ['visionary_notes_v1', '{"existing":"note"}'],
        ],
        'visionary_notes_v1',
    );
    const sandbox = loadImportApi(storage);
    const payload = makePayload({
        visionary_favorites: '["new favorite"]',
        visionary_notes_v1: '{"new":"note"}',
        visionary_read_v1: '["new read"]',
    });

    assert.throws(() => applyImportedState(sandbox, payload), /本機儲存/);
    assert.equal(storage.getItem('visionary_favorites'), '["existing favorite"]');
    assert.equal(storage.getItem('visionary_notes_v1'), '{"existing":"note"}');
    assert.equal(storage.getItem('visionary_read_v1'), null);
});
