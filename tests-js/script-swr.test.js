import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const sourcePath = fileURLToPath(new URL("../static/script.js", import.meta.url));

function sourceBetween(source, startMarker, endMarker) {
    const start = source.indexOf(startMarker);
    assert.notEqual(start, -1, `missing ${startMarker}`);
    const end = source.indexOf(endMarker, start);
    assert.notEqual(end, -1, `missing ${endMarker}`);
    return source.slice(start, end);
}

function loadPaperMessageMatcher() {
    const source = fs.readFileSync(sourcePath, 'utf8');
    const requestHelpers = sourceBetween(source, 'function _paperFetchOptions', 'async function _readPaperPayloadIDB');
    const matcher = sourceBetween(source, 'function _isCurrentPapersPayload', 'function _onSWApiUpdated');
    const sandbox = { ACTIVE_DISCIPLINE: { id: 'cv' }, URLSearchParams };
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(`const PAPER_FETCH_MAX = 80;\n${requestHelpers}\n${matcher}`, sandbox, { filename: sourcePath });
    return (payload) => {
        sandbox.payload = payload;
        return vm.runInContext('_isCurrentPapersPayload(payload)', sandbox);
    };
}

test('paper refresh notices only match the current main feed request identity', () => {
    const matchesCurrentFeed = loadPaperMessageMatcher();

    assert.equal(matchesCurrentFeed({
        path: '/api/papers',
        search: '?max_results=80&days=7&discipline=cv',
    }), true);
    assert.equal(matchesCurrentFeed({
        path: '/api/papers',
        search: '?max_results=80&days=7&discipline=cv&topic=vision',
    }), false);
    assert.equal(matchesCurrentFeed({
        path: '/api/papers',
        search: '?max_results=100&days=7&discipline=cv',
    }), false);
});
