// ── Google 登入 + 雲端同步 ────────────────────────────────────────
// 策略：登入後拉雲端資料 → 與本地 localStorage 合併（聯集） → 寫回本地與雲端
// 之後本地任何 setItem 變更同步鍵，會 debounced PUT 整包到後端。
// 登入/登出後重新整理頁面，讓 script.js 從新 localStorage 重新初始化記憶體狀態。

const SYNC_KEYS = [
    'visionary_favorites',
    'visionary_read_v1',
    'visionary_notes_v1',
    'visionary_pinned_topics',
    'visionary_custom_topics',
    'visionary_deleted_builtins',
    'visionary_renamed_builtins',
];

const TOKEN_KEY = 'visionary_id_token';
const USER_KEY = 'visionary_user';

let _idToken = localStorage.getItem(TOKEN_KEY) || null;
let _user = (() => { try { return JSON.parse(localStorage.getItem(USER_KEY) || 'null'); } catch (e) { return null; } })();
let _syncTimer = null;

function isLoggedIn() { return !!_idToken; }

// ── 包裝 setItem：同步鍵變更時觸發雲端推送 ──────────────────────
const _origSetItem = Storage.prototype.setItem;
Storage.prototype.setItem = function (key, value) {
    _origSetItem.call(this, key, value);
    if (this === localStorage && isLoggedIn() && SYNC_KEYS.includes(key)) {
        scheduleCloudPush();
    }
};

function collectLocalData() {
    const out = {};
    for (const k of SYNC_KEYS) {
        const v = localStorage.getItem(k);
        if (v != null) {
            try { out[k] = JSON.parse(v); } catch (e) { out[k] = v; }
        }
    }
    return out;
}

async function pushToCloud() {
    if (!isLoggedIn()) return;
    try {
        const res = await fetch('/api/me/data', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + _idToken },
            body: JSON.stringify({ data: collectLocalData() }),
        });
        if (res.status === 401) signOut();
    } catch (e) { /* 網路錯誤略過，下次變更會再推 */ }
}

function scheduleCloudPush(delay = 1500) {
    clearTimeout(_syncTimer);
    _syncTimer = setTimeout(pushToCloud, delay);
}

// ── 合併規則：陣列 union；物件 merge（本地優先）─────────────────
function mergeData(remote, local) {
    const merged = {};
    const keys = new Set([...Object.keys(remote || {}), ...Object.keys(local || {})]);
    for (const k of keys) {
        const r = remote?.[k], l = local?.[k];
        if (Array.isArray(r) || Array.isArray(l)) {
            const set = new Set([...(Array.isArray(r) ? r : []), ...(Array.isArray(l) ? l : [])]);
            merged[k] = [...set];
        } else if ((r && typeof r === 'object') || (l && typeof l === 'object')) {
            merged[k] = { ...(r || {}), ...(l || {}) };
        } else {
            merged[k] = l ?? r;
        }
    }
    return merged;
}

async function fetchAndMerge() {
    const res = await fetch('/api/me/data', {
        headers: { 'Authorization': 'Bearer ' + _idToken },
    });
    if (!res.ok) {
        if (res.status === 401) signOut();
        return null;
    }
    const { user, data: remote } = await res.json();
    const local = collectLocalData();
    const merged = mergeData(remote, local);

    // 寫回 localStorage（用原始 setItem 避免遞迴觸發 push）
    for (const k of SYNC_KEYS) {
        if (merged[k] !== undefined) {
            _origSetItem.call(localStorage, k, JSON.stringify(merged[k]));
        }
    }
    // 推送合併結果到雲端
    await fetch('/api/me/data', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + _idToken },
        body: JSON.stringify({ data: merged }),
    });
    return user;
}

// ── 登入流程（Google Identity Services token credential）─────────
async function handleCredential(response) {
    _idToken = response.credential;
    localStorage.setItem(TOKEN_KEY, _idToken);
    try {
        const user = await fetchAndMerge();
        if (user) {
            _user = user;
            localStorage.setItem(USER_KEY, JSON.stringify(user));
        }
        // 重新載入頁面讓 script.js 用合併後的資料重新初始化
        location.reload();
    } catch (e) {
        console.error('login sync failed', e);
        signOut();
    }
}

function signOut() {
    _idToken = null;
    _user = null;
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    if (window.google?.accounts?.id) {
        try { google.accounts.id.disableAutoSelect(); } catch (e) {}
    }
    location.reload();
}

function renderAuthUI() {
    const signInBtn = document.getElementById('signInBtn');
    const userInfo = document.getElementById('userInfo');
    if (!signInBtn || !userInfo) return;
    if (_user) {
        signInBtn.hidden = true;
        userInfo.hidden = false;
        document.getElementById('userAvatar').src = _user.picture || '';
        document.getElementById('userName').textContent = _user.name || _user.email || '';
    } else {
        signInBtn.hidden = false;
        userInfo.hidden = true;
    }
}

async function initAuth() {
    renderAuthUI();
    document.getElementById('signOutBtn')?.addEventListener('click', signOut);

    let cfg;
    try {
        cfg = await (await fetch('/api/me/config')).json();
    } catch (e) { return; }
    if (!cfg.google_client_id) return;

    // 等 GIS script 載入
    const waitGsi = () => new Promise((resolve) => {
        if (window.google?.accounts?.id) return resolve();
        const t = setInterval(() => {
            if (window.google?.accounts?.id) { clearInterval(t); resolve(); }
        }, 100);
    });
    await waitGsi();

    google.accounts.id.initialize({
        client_id: cfg.google_client_id,
        callback: handleCredential,
        auto_select: false,
    });

    const signInBtn = document.getElementById('signInBtn');
    if (signInBtn && !_idToken) {
        signInBtn.addEventListener('click', () => google.accounts.id.prompt());
    }
}

document.addEventListener('DOMContentLoaded', initAuth);
