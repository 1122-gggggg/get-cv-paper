// ── Google 登入 + 雲端同步 ────────────────────────────────────────
// 策略：登入後拉雲端資料 → 與本地 localStorage 合併（聯集） → 寫回本地與雲端
// 之後本地任何 setItem 變更同步鍵，會 debounced PUT 整包到後端。
// 登入/登出後重新整理頁面，讓 script.js 從新 localStorage 重新初始化記憶體狀態。

// 使用前綴匹配：discipline-scoped keys（例如 visionary_pinned_topics:nlp）也會同步
const SYNC_PREFIXES = [
    'visionary_favorites',
    'visionary_read_v1',
    'visionary_notes_v1',
    'visionary_pinned_topics',
    'visionary_custom_topics',
    'visionary_deleted_builtins',
    'visionary_renamed_builtins',
    'visionary_paper_tags_v1',
    'visionary_discipline',
    'visionary_last_category',
];
function _isSyncKey(k) {
    return SYNC_PREFIXES.some(p => k === p || k.startsWith(p + ':'));
}
function _listSyncKeys() {
    const out = [];
    for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k && _isSyncKey(k)) out.push(k);
    }
    return out;
}

// GIS ID token (JWT) 過期檢查
function _tokenExpMs(tok) {
    try {
        const p = JSON.parse(atob(tok.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
        return (p.exp || 0) * 1000;
    } catch (e) { return 0; }
}
function _isTokenExpired(tok, skewMs = 60_000) {
    const exp = _tokenExpMs(tok);
    return !exp || Date.now() + skewMs >= exp;
}

const TOKEN_KEY = 'visionary_id_token';
const USER_KEY = 'visionary_user';

let _idToken = localStorage.getItem(TOKEN_KEY) || null;
let _user = (() => { try { return JSON.parse(localStorage.getItem(USER_KEY) || 'null'); } catch (e) { return null; } })();
let _syncTimer = null;

// 啟動時若 token 已過期，直接清除（避免 401 迴圈）
if (_idToken && _isTokenExpired(_idToken, 0)) {
    _idToken = null;
    localStorage.removeItem(TOKEN_KEY);
}

function isLoggedIn() { return !!_idToken && !_isTokenExpired(_idToken, 0); }

// ── 包裝 setItem：同步鍵變更時觸發雲端推送 ──────────────────────
const _origSetItem = Storage.prototype.setItem;
Storage.prototype.setItem = function (key, value) {
    _origSetItem.call(this, key, value);
    if (this === localStorage && isLoggedIn() && _isSyncKey(key)) {
        scheduleCloudPush();
    }
};

function collectLocalData() {
    const out = {};
    for (const k of _listSyncKeys()) {
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
    for (const k of Object.keys(merged)) {
        if (_isSyncKey(k) && merged[k] !== undefined) {
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

// GIS script 延載：點登入才動態注入 <script>
let _gsiLoading = null;
function loadGsi() {
    if (window.google?.accounts?.id) return Promise.resolve();
    if (_gsiLoading) return _gsiLoading;
    _gsiLoading = new Promise((resolve, reject) => {
        const s = document.createElement('script');
        s.src = 'https://accounts.google.com/gsi/client';
        s.async = true;
        s.defer = true;
        s.onload = () => resolve();
        s.onerror = reject;
        document.head.appendChild(s);
    });
    return _gsiLoading;
}

let _gsiReady = false;
async function ensureGsiInitialized(clientId) {
    if (_gsiReady) return;
    await loadGsi();
    google.accounts.id.initialize({
        client_id: clientId,
        callback: handleCredential,
        auto_select: false,
        use_fedcm_for_prompt: true,
    });
    _gsiReady = true;
}

async function initAuth() {
    renderAuthUI();
    document.getElementById('signOutBtn')?.addEventListener('click', signOut);

    let cfg;
    try {
        cfg = await (await fetch('/api/me/config')).json();
    } catch (e) { return; }
    if (!cfg.google_client_id) return;

    const signInBtn = document.getElementById('signInBtn');
    if (!signInBtn || _idToken) return;

    // 點擊登入才載入 GIS script（節省首屏 200KB JS）
    signInBtn.addEventListener('click', async () => {
        try {
            await ensureGsiInitialized(cfg.google_client_id);
            let host = document.getElementById('gsiBtnHost');
            if (!host) {
                host = document.createElement('div');
                host.id = 'gsiBtnHost';
                host.style.cssText = 'position:absolute;opacity:0;pointer-events:none;width:0;height:0;overflow:hidden;';
                document.body.appendChild(host);
                google.accounts.id.renderButton(host, { type: 'standard', theme: 'outline', size: 'large' });
            }
            const realBtn = host.querySelector('div[role=button], button');
            if (realBtn) realBtn.click();
            else google.accounts.id.prompt();
        } catch (e) { console.error('GIS load failed', e); }
    });
}

document.addEventListener('DOMContentLoaded', initAuth);

// 對外（script.js）暴露必要輔助
window.visionaryAuth = {
    isLoggedIn,
    getSyncKeys: () => _listSyncKeys(),
    pushNow: () => pushToCloud(),
};
