let allPapers = [];      // 7 天
let monthPapers = [];    // 30 天（懶加載）
let currentCategory = 'all';
let currentSortValue = localStorage.getItem('visionary_sort_v2') || 'signal';
let PAPERS_PER_PAGE = parseInt(localStorage.getItem('visionary_per_page') || '9', 10);
let currentPage = 1;
let currentFilteredPapers = [];
let lastCustomTitle = null;

// ── 安全：HTML escape（防 XSS，arXiv 摘要可能含 <、> 等字元）─────
function escapeHtml(s) {
    if (s == null) return '';
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// ── 防抖動 localStorage 寫入（累積大量資料時避免頻繁序列化）──────
const _saveTimers = {};
function scheduleSave(key, getVal, delay = 800) {
    clearTimeout(_saveTimers[key]);
    _saveTimers[key] = setTimeout(() => {
        try { localStorage.setItem(key, JSON.stringify(getVal())); } catch (e) {}
    }, delay);
}

// ── 預計算 lower-case 欄位以加速搜尋/分類篩選 ─────────────────────
function indexPapers(papers) {
    for (const p of papers) {
        if (p._indexed) continue;
        p._titleLc   = (p.title   || '').toLowerCase();
        p._summaryLc = (p.summary || '').toLowerCase();
        p._authorsLc = (p.authors || []).join(' ').toLowerCase();
        p._indexed = true;
    }
    return papers;
}

// ── SVG 圖示（改用 sprite <use>，HTML 體積銳減）─────────────────
function svgUse(id, size = 12) {
    return `<svg width="${size}" height="${size}"><use href="#${id}"/></svg>`;
}
const ICONS = {
    unread:     svgUse('icon-circle') + ' 未讀',
    read:       svgUse('icon-check')  + ' 已讀',
    noteEmpty:  svgUse('icon-note')   + ' 筆記',
    noteFilled: svgUse('icon-note-filled') + ' 筆記',
};

// ── 研究領域（由 disciplines.js 提供）────────────────────────────
let ACTIVE_DISCIPLINE = null;   // 當前 discipline 物件（window.DISCIPLINES[x]）
// 頂會關鍵字與 patterns 於 applyDiscipline() 時依 discipline 動態填入
let TOP_CONF_KEYWORDS = [];
let VENUE_PATTERNS = [];

// 依 discipline id 為 localStorage key 加上後綴，隔離各領域的分類狀態
function _scopedKey(base, disciplineId) {
    return `${base}:${disciplineId}`;
}

function _escapeRegExp(s) {
    return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// 依 discipline 設定 CONF_FILTERS / VENUE_PATTERNS / TOPIC_SYNONYMS / SEARCH_SUGGESTIONS
// 以及各 localStorage key 的 scoped 後綴。呼叫時間點：
//   - DOMContentLoaded 最一開始（初次載入）
//   - 使用者從選擇器切換領域後（切換後 location.reload()，因此不需要熱切換重建 DOM）
function applyDiscipline(disciplineId) {
    const d = window.DISCIPLINES?.[disciplineId];
    if (!d) return false;
    ACTIVE_DISCIPLINE = d;

    // localStorage key 加上領域後綴，讓每個領域有自己的分類／釘選／筆記分類
    PINNED_TOPICS_KEY    = _scopedKey('visionary_pinned_topics', d.id);
    CUSTOM_TOPICS_KEY    = _scopedKey('visionary_custom_topics', d.id);
    DELETED_BUILTIN_KEY  = _scopedKey('visionary_deleted_builtins', d.id);
    RENAMED_BUILTIN_KEY  = _scopedKey('visionary_renamed_builtins', d.id);
    LAST_CATEGORY_KEY    = _scopedKey('visionary_last_category', d.id);

    // 建構 CONF_FILTERS：data-filter="conf_<key>"
    CONF_FILTERS = new Map(d.confs.map(c => [`conf_${c.key.replace(/\s+/g, '_')}`, c.key.toLowerCase()]));
    SPECIAL_FILTERS = new Set(['all', 'favorites', 'top_conf', 'hf_daily', ...CONF_FILTERS.keys()]);

    // VENUE_PATTERNS：顯示在卡片上的 venue 徽章
    VENUE_PATTERNS = d.confs.map(c => ({
        re: new RegExp('\\b' + _escapeRegExp(c.label) + '\\b', 'i'),
        label: c.label,
        color: c.color,
    }));

    // top_conf 篩選用的關鍵字
    TOP_CONF_KEYWORDS = d.confs.map(c => c.key.toLowerCase());

    TOPIC_SYNONYMS = d.synonyms || {};
    SEARCH_SUGGESTIONS = [
        ...d.topics.slice(0, 16),
        ...d.confs.slice(0, 3).map(c => `${c.label} ${new Date().getFullYear()}`),
    ];

    // 套用品牌／標題
    const brand = d.brand || 'Scholarly';
    document.title = `${brand} | ${d.name}最新論文`;
    const logo = document.getElementById('brandLogo');
    if (logo) logo.innerHTML = `${brand}<span>.</span>`;
    const badge = document.getElementById('activeDisciplineBadge');
    if (badge) badge.textContent = `${d.icon} ${d.name}`;

    // 設定 CSS 變數以渲染領域色調（logo gradient / hero tint / badge）
    const accent = d.accent || { from: '#3b82f6', to: '#a855f7', tint: 'rgba(59,130,246,0.18)' };
    const root = document.documentElement;
    root.style.setProperty('--accent-from', accent.from);
    root.style.setProperty('--accent-to', accent.to);
    root.style.setProperty('--hero-tint', accent.tint);
    return true;
}

// 在 DOM 裡動態產生 conf-submenu 與主題按鈕（取代原本寫死在 HTML 的 <button>）
function renderDisciplineFilters() {
    const d = ACTIVE_DISCIPLINE;
    if (!d) return;

    const confMenu = document.getElementById('confSubmenu');
    if (confMenu) {
        confMenu.innerHTML = '';
        for (const c of d.confs) {
            const btn = document.createElement('button');
            btn.className = 'conf-item';
            btn.dataset.filter = `conf_${c.key.replace(/\s+/g, '_')}`;
            btn.textContent = c.label;
            confMenu.appendChild(btn);
        }
    }

    const filtersDiv = document.querySelector('.category-filters');
    const wrapper = document.querySelector('.add-topic-wrapper');
    if (filtersDiv && wrapper) {
        // 先清掉舊主題按鈕（避免切換領域殘留，雖然目前切換會 reload）
        filtersDiv.querySelectorAll('.category-btn[data-discipline-topic="true"]').forEach(el => el.remove());
        for (const topic of d.topics) {
            const btn = document.createElement('button');
            btn.className = 'category-btn';
            btn.dataset.filter = topic.toLowerCase();
            btn.dataset.disciplineTopic = 'true';
            const label = document.createElement('span');
            label.className = 'label-span';
            label.textContent = topic;
            btn.appendChild(label);
            filtersDiv.insertBefore(btn, wrapper);
        }
    }
}

// ── 研究領域選擇器 UI ──────────────────────────────────────────
function openDisciplinePicker({ closable = true } = {}) {
    const picker = document.getElementById('disciplinePicker');
    const grid = document.getElementById('disciplineGrid');
    const closeBtn = document.getElementById('disciplinePickerClose');
    if (!picker || !grid) return;

    grid.innerHTML = '';
    const activeId = ACTIVE_DISCIPLINE?.id;
    for (const id of (window.DISCIPLINE_ORDER || Object.keys(window.DISCIPLINES || {}))) {
        const d = window.DISCIPLINES[id];
        if (!d) continue;
        const card = document.createElement('button');
        card.type = 'button';
        card.className = 'dp-card' + (id === activeId ? ' active' : '');
        card.dataset.disciplineId = id;
        const confsPreview = d.confs.slice(0, 5).map(c => c.label).join(' · ');
        card.innerHTML = `
            <div class="dp-card-icon">${d.icon}</div>
            <div class="dp-card-name">${d.name}</div>
            <div class="dp-card-name-en">${d.nameEn}</div>
            <div class="dp-card-arxiv">arXiv: ${d.arxivCat}</div>
            <div class="dp-card-confs">${confsPreview}</div>
        `;
        card.addEventListener('click', () => selectDiscipline(id));
        grid.appendChild(card);
    }

    if (closeBtn) closeBtn.hidden = !closable;
    picker.classList.remove('hidden');
}

function closeDisciplinePicker() {
    document.getElementById('disciplinePicker')?.classList.add('hidden');
}

function selectDiscipline(id) {
    const prev = localStorage.getItem('visionary_discipline');
    window.setActiveDiscipline(id);
    if (prev === id) {
        closeDisciplinePicker();
        return;
    }
    // 切換領域 → reload 使整個 UI／localStorage 狀態重新初始化
    location.reload();
}

// ── 收藏夾系統 ─────────────────────────────────────────────────
const FAVORITES_KEY = 'visionary_favorites';
let favorites = new Set(JSON.parse(localStorage.getItem(FAVORITES_KEY) || '[]'));

// ── 釘選主題系統 ────────────────────────────────────────────────
// 這些 key 由 applyDiscipline() 動態加上 discipline 後綴
let PINNED_TOPICS_KEY = 'visionary_pinned_topics';

function loadPinnedTopics() {
    const saved = JSON.parse(localStorage.getItem(PINNED_TOPICS_KEY) || '[]');
    saved.forEach(topic => addPinnedBtn(topic, false));
}

function savePinnedTopics() {
    const pinnedBtns = document.querySelectorAll('.category-btn[data-pinned="true"]');
    const topics = Array.from(pinnedBtns).map(b => b.dataset.filter);
    localStorage.setItem(PINNED_TOPICS_KEY, JSON.stringify(topics));
}

function addPinnedBtn(topic, save = true) {
    const label = topic.trim();
    if (!label) return;

    const existing = document.querySelector(`.category-btn[data-filter="${CSS.escape(label)}"]`);
    if (existing) {
        existing.scrollIntoView({ behavior: 'smooth', inline: 'center' });
        if (save) showToast(`「${label}」已在主題列表中`);
        return;
    }

    const filtersDiv = document.querySelector('.category-filters');
    const wrapper = document.querySelector('.add-topic-wrapper');

    const btn = document.createElement('button');
    btn.className = 'category-btn pinned-topic-btn';
    btn.dataset.filter = label;
    btn.dataset.pinned = 'true';

    const pin = document.createElement('span');
    pin.className = 'pin-icon';
    pin.textContent = '📌';

    const labelSpan = document.createElement('span');
    labelSpan.className = 'label-span';
    labelSpan.textContent = label;

    btn.appendChild(pin);
    btn.appendChild(labelSpan);
    filtersDiv.insertBefore(btn, wrapper);

    if (save) {
        savePinnedTopics();
        showToast(`已釘選「${label}」`);
    }
}

function deletePinnedBtn(btn) {
    if (currentCategory === btn.dataset.filter) {
        currentCategory = 'all';
        const allBtn = document.querySelector('.category-btn[data-filter="all"]');
        if (allBtn) {
            document.querySelectorAll('.category-btn').forEach(b => b.classList.remove('active'));
            allBtn.classList.add('active');
        }
        filterPapers();
    }
    btn.remove();
    savePinnedTopics();
}

// ── 已讀系統 ───────────────────────────────────────────────────
const READ_KEY = 'visionary_read_v1';
let readSet = new Set(JSON.parse(localStorage.getItem(READ_KEY) || '[]'));

function saveReadSet() {
    localStorage.setItem(READ_KEY, JSON.stringify([...readSet]));
}

function toggleRead(url, card) {
    const readBtn = card.querySelector('.read-btn');
    const use = readBtn.querySelector('use');
    const label = readBtn.querySelector('.read-label');
    if (readSet.has(url)) {
        readSet.delete(url);
        card.classList.remove('is-read');
        readBtn.classList.remove('is-read');
        use?.setAttribute('href', '#icon-circle');
        if (label) label.textContent = '未讀';
        showToast('已標記為未讀');
    } else {
        readSet.add(url);
        card.classList.add('is-read');
        readBtn.classList.add('is-read');
        use?.setAttribute('href', '#icon-check');
        if (label) label.textContent = '已讀';
        showToast('已標記為已讀');
    }
    saveReadSet();
}

// ── 筆記系統 ───────────────────────────────────────────────────
const NOTES_KEY = 'visionary_notes_v1';
let notesMap = {};
try { notesMap = JSON.parse(localStorage.getItem(NOTES_KEY) || '{}'); } catch (e) { }

function saveNotes() {
    localStorage.setItem(NOTES_KEY, JSON.stringify(notesMap));
}

function openNotePanel(url, card) {
    const panel = card.querySelector('.note-panel');
    const textarea = card.querySelector('.note-textarea');
    if (panel.classList.contains('open')) {
        panel.classList.remove('open');
        return;
    }
    textarea.value = notesMap[url] || '';
    panel.classList.add('open');
    textarea.focus();
}

function saveNote(url, card) {
    const textarea = card.querySelector('.note-textarea');
    const text = textarea.value.trim();
    const noteBtn = card.querySelector('.note-btn');
    const use = noteBtn.querySelector('use');
    if (text) {
        notesMap[url] = text;
        noteBtn.classList.add('has-note');
        use?.setAttribute('href', '#icon-note-filled');
        showToast('筆記已儲存');
    } else {
        delete notesMap[url];
        noteBtn.classList.remove('has-note');
        use?.setAttribute('href', '#icon-note');
        showToast('筆記已清除');
    }
    saveNotes();
    card.querySelector('.note-panel').classList.remove('open');
}


function saveFavorites() {
    localStorage.setItem(FAVORITES_KEY, JSON.stringify([...favorites]));
}

// ── 每篇論文自訂標籤 ─────────────────────────────────────────
const PAPER_TAGS_KEY = 'visionary_paper_tags_v1';
let paperTags = {};
try { paperTags = JSON.parse(localStorage.getItem(PAPER_TAGS_KEY) || '{}'); } catch (e) { paperTags = {}; }

function savePaperTags() {
    localStorage.setItem(PAPER_TAGS_KEY, JSON.stringify(paperTags));
}

function getPaperTags(url) { return paperTags[url] || []; }

function addPaperTag(url, tag) {
    const t = (tag || '').trim();
    if (!t || t.length > 24) return false;
    const arr = paperTags[url] || [];
    if (arr.includes(t)) return false;
    arr.push(t);
    paperTags[url] = arr;
    savePaperTags();
    return true;
}

function removePaperTag(url, tag) {
    const arr = paperTags[url];
    if (!arr) return;
    const i = arr.indexOf(tag);
    if (i < 0) return;
    arr.splice(i, 1);
    if (arr.length === 0) delete paperTags[url];
    else paperTags[url] = arr;
    savePaperTags();
}

function allKnownTags() {
    const s = new Set();
    for (const arr of Object.values(paperTags)) for (const t of arr) s.add(t);
    return [...s].sort();
}

function renderCardTags(card, url) {
    const chips = card.querySelector('.tag-chips');
    if (!chips) return;
    chips.innerHTML = '';
    for (const t of getPaperTags(url)) {
        const chip = document.createElement('span');
        chip.className = 'tag-chip';
        chip.dataset.tag = t;
        chip.innerHTML = `<span class="tag-label"></span><button class="tag-x" title="移除">×</button>`;
        chip.querySelector('.tag-label').textContent = '#' + t;
        chips.appendChild(chip);
    }
}

function promptAddTag(card, url) {
    const existing = new Set(getPaperTags(url));
    const known = allKnownTags().filter(t => !existing.has(t));
    const hint = known.length ? `\n\n已用過的標籤：${known.slice(0, 20).join(', ')}` : '';
    const v = window.prompt('輸入新標籤（最多 24 字）：' + hint);
    if (v == null) return;
    const t = v.trim();
    if (!t) return;
    if (addPaperTag(url, t)) {
        renderCardTags(card, url);
        showToast(`已加上 #${t}`);
    }
}

function toggleFavorite(url, starEl) {
    if (favorites.has(url)) {
        favorites.delete(url);
        starEl.classList.remove('starred');
        starEl.title = '加入收藏';
        showToast('已從收藏夾中移除');
    } else {
        favorites.add(url);
        starEl.classList.add('starred');
        starEl.title = '取消收藏';
        showToast('已加入收藏夾');
    }
    saveFavorites();
    // 若目前在收藏夾視圖，移除後立即重新渲染
    if (currentCategory === 'favorites') filterPapers();
}

// ── LRU 快取（有上限，避免 localStorage 爆量）──────────────────
function makeLRU(key, max) {
    let map;
    try {
        const raw = JSON.parse(localStorage.getItem(key) || '{}');
        // 舊格式（直接 {id: value}）→ 升級成 {_lru:[ids], data:{...}}
        if (raw && raw._lru && raw.data) {
            map = { order: raw._lru, data: raw.data };
        } else {
            map = { order: Object.keys(raw), data: raw };
        }
    } catch (e) { map = { order: [], data: {} }; }

    return {
        get(k) {
            if (!(k in map.data)) return undefined;
            const i = map.order.indexOf(k);
            if (i >= 0) { map.order.splice(i, 1); map.order.push(k); }
            return map.data[k];
        },
        set(k, v) {
            if (k in map.data) map.order.splice(map.order.indexOf(k), 1);
            map.data[k] = v;
            map.order.push(k);
            while (map.order.length > max) {
                const old = map.order.shift();
                delete map.data[old];
            }
        },
        save() {
            try {
                localStorage.setItem(key, JSON.stringify({ _lru: map.order, data: map.data }));
            } catch (e) {}
        },
        raw: map,
    };
}

// ── 中文摘要系統（Gemma）────────────────────────────────────────
const ZH_CACHE_KEY = 'zh_summary_v3';
const zhLRU = makeLRU(ZH_CACHE_KEY, 2000);

const translateQueue = [];
let translateBusy = false;

function getArxivIdFromUrl(url) {
    const m = url?.match(/abs\/(\d{4}\.\d+)/);
    return m ? m[1] : null;
}

async function fetchSummaryFromGroq(abstract, arxivId) {
    const res = await fetch('/api/summarize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            arxiv_id: arxivId || 'unknown',
            abstract,
            discipline: ACTIVE_DISCIPLINE?.id || 'cv',
        }),
    });
    if (!res.ok) throw new Error('groq error ' + res.status);
    const data = await res.json();
    return data.summary;
}

async function fetchSummaryFallback(text) {
    const res = await fetch('/api/translate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, target: 'zh-TW' }),
    });
    if (!res.ok) throw new Error('translate proxy error');
    const data = await res.json();
    return data.translated || '';
}

async function processTranslateQueue() {
    if (translateBusy || translateQueue.length === 0) return;
    translateBusy = true;
    const { text, cacheKey, arxivId, el } = translateQueue.shift();

    try {
        const summary = await fetchSummaryFromGroq(text, arxivId);
        zhLRU.set(cacheKey, summary);
        scheduleSave(ZH_CACHE_KEY, () => ({ _lru: zhLRU.raw.order, data: zhLRU.raw.data }));
        el.innerHTML = escapeHtml(summary).replace(/\n/g, '<br>');
        el.closest('.zh-summary-block').classList.remove('loading');
    } catch (e) {
        try {
            const short = text.length > 600 ? text.substring(0, 600) + '...' : text;
            const translated = await fetchSummaryFallback(short);
            zhLRU.set(cacheKey, translated);
            scheduleSave(ZH_CACHE_KEY, () => ({ _lru: zhLRU.raw.order, data: zhLRU.raw.data }));
            el.textContent = translated;
            el.closest('.zh-summary-block').classList.remove('loading');
        } catch (e2) {
            el.textContent = '（摘要暫時無法取得）';
            el.closest('.zh-summary-block').classList.remove('loading');
        }
    }

    translateBusy = false;
    setTimeout(processTranslateQueue, 100);
}

function queueTranslation(summary, cacheKey, textEl) {
    const cached = zhLRU.get(cacheKey);
    if (cached) {
        textEl.textContent = cached;
        textEl.closest('.zh-summary-block').classList.remove('loading');
        return;
    }
    const arxivId = getArxivIdFromUrl(cacheKey);
    translateQueue.push({ text: summary, cacheKey, arxivId, el: textEl });
    processTranslateQueue();
}

// IntersectionObserver：卡片進入視野才翻譯
const translateObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            const card = entry.target;
            const textEl = card.querySelector('.zh-summary-text');
            if (textEl && !textEl.dataset.queued) {
                textEl.dataset.queued = '1';
                queueTranslation(card.dataset.summary, card.dataset.cacheKey, textEl);
            }
            translateObserver.unobserve(card);
        }
    });
}, { rootMargin: '200px' });

const papersGrid = document.getElementById('papersGrid');
const loader = document.getElementById('loader');
const searchInput = document.getElementById('searchInput');
const noResults = document.getElementById('noResults');

let searchDebounceTimer = null;

// loader 動態提示訊息（讓使用者感受到載入進度，而非呆呆等待）
function buildLoaderMessages() {
    const extra = ACTIVE_DISCIPLINE?.loaderHints || [];
    return [
        '正在自動為您抓取最新論文...',
        ...extra,
        '快好了，正在處理論文資料...',
    ];
}

let loaderMsgInterval = null;

function startLoaderMessages() {
    const loaderP = loader.querySelector('p');
    if (!loaderP) return;
    const msgs = buildLoaderMessages();
    let idx = 0;
    loaderP.textContent = msgs[0];
    loaderMsgInterval = setInterval(() => {
        idx = (idx + 1) % msgs.length;
        loaderP.textContent = msgs[idx];
    }, 2200);
}

function stopLoaderMessages() {
    clearInterval(loaderMsgInterval);
    loaderMsgInterval = null;
}

async function fetchPapers() {
    // Show loader
    papersGrid.classList.add('hidden');
    noResults.classList.add('hidden');
    loader.classList.remove('hidden');
    startLoaderMessages();

    try {
        // 一次拿1000篇(大約一週的量)，後端已有快取機制
        const disc = ACTIVE_DISCIPLINE?.id || 'cv';
        const res = await fetch(`/api/papers?max_results=1000&discipline=${encodeURIComponent(disc)}`);
        if (!res.ok) throw new Error('Failed to fetch data');
        const data = await res.json();
        allPapers = indexPapers(data.papers);
        filterPapers(); // Auto filter after fetch
        // 背景抓 S2 venue + 引用數，完成後重新渲染以顯示出處
        fetchCitationCounts(allPapers).then(() => renderPapers(currentFilteredPapers, lastCustomTitle));
    } catch (e) {
        console.error(e);
        alert('獲取論文失敗，請稍後再試。 Error: ' + e.message);
        loader.classList.add('hidden');
    } finally {
        stopLoaderMessages();
    }
}

function goToPage(page) {
    currentPage = page;
    renderPapers(currentFilteredPapers, lastCustomTitle);
    papersGrid.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderPagination(total) {
    const totalPages = Math.ceil(total / PAPERS_PER_PAGE);
    if (totalPages <= 1) return;

    const nav = document.createElement('div');
    nav.className = 'pagination';
    nav.style.gridColumn = '1 / -1';

    function pageBtn(label, page, isActive, isDisabled) {
        const btn = document.createElement('button');
        btn.className = 'page-btn' + (isActive ? ' active' : '') + (isDisabled ? ' disabled' : '');
        btn.textContent = label;
        btn.disabled = isDisabled;
        if (!isDisabled) btn.addEventListener('click', () => goToPage(page));
        return btn;
    }

    // Prev
    nav.appendChild(pageBtn('‹', currentPage - 1, false, currentPage === 1));

    // Page numbers with ellipsis
    const range = [];
    for (let p = 1; p <= totalPages; p++) {
        if (p === 1 || p === totalPages || (p >= currentPage - 2 && p <= currentPage + 2)) {
            range.push(p);
        }
    }
    let prev = null;
    range.forEach(p => {
        if (prev !== null && p - prev > 1) {
            const dots = document.createElement('span');
            dots.className = 'page-dots';
            dots.textContent = '…';
            nav.appendChild(dots);
        }
        nav.appendChild(pageBtn(p, p, p === currentPage, false));
        prev = p;
    });

    // Next
    nav.appendChild(pageBtn('›', currentPage + 1, false, currentPage === totalPages));

    papersGrid.appendChild(nav);
}

// ── 會議/期刊出處偵測（VENUE_PATTERNS 在 applyDiscipline 時填入）─

function detectVenue(paper) {
    // 優先使用 Semantic Scholar 的正式 venue 名稱
    const s2venue = getS2Venue(paper.url);
    if (s2venue) {
        for (const v of VENUE_PATTERNS) {
            if (v.re.test(s2venue)) return v;
        }
        // S2 有 venue 但不在已知清單中，顯示原始名稱（截短）
        const short = s2venue.length > 20 ? s2venue.slice(0, 18) + '…' : s2venue;
        return { label: short, color: '#475569' };
    }
    // Fallback：從標題/摘要偵測
    const text = paper.title + ' ' + paper.summary;
    for (const v of VENUE_PATTERNS) {
        if (v.re.test(text)) return v;
    }
    return null;
}

let _pwcPageFetching = false;

// ── 事件委派：所有卡片互動由 papersGrid 一個 listener 處理 ────────
function _bindPapersGridDelegation() {
    if (papersGrid._delegated) return;
    papersGrid._delegated = true;

    papersGrid.addEventListener('click', (e) => {
        const card = e.target.closest('.paper-card');
        if (!card) return;
        const url = card.dataset.url;
        if (!url) return;

        const starBtn = e.target.closest('.star-btn');
        if (starBtn && card.contains(starBtn)) {
            e.stopPropagation();
            toggleFavorite(url, starBtn);
            const use = starBtn.querySelector('use');
            use?.setAttribute('href', favorites.has(url) ? '#icon-star-filled' : '#icon-star');
            return;
        }

        const readBtn = e.target.closest('.read-btn');
        if (readBtn && card.contains(readBtn)) {
            e.stopPropagation();
            toggleRead(url, card);
            return;
        }

        const noteBtn = e.target.closest('.note-btn');
        if (noteBtn && card.contains(noteBtn)) {
            e.stopPropagation();
            openNotePanel(url, card);
            return;
        }

        const saveBtn = e.target.closest('.note-save-btn');
        if (saveBtn && card.contains(saveBtn)) {
            e.stopPropagation();
            saveNote(url, card);
            return;
        }

        const cancelBtn = e.target.closest('.note-cancel-btn');
        if (cancelBtn && card.contains(cancelBtn)) {
            e.stopPropagation();
            card.querySelector('.note-panel')?.classList.remove('open');
            return;
        }

        const authorBtn = e.target.closest('.author-btn');
        if (authorBtn && card.contains(authorBtn)) {
            e.preventDefault();
            const author = authorBtn.dataset.author;
            if (author) {
                searchInput.value = author;
                searchAllPapers(author);
            }
            return;
        }

        const tagAdd = e.target.closest('.tag-add-btn');
        if (tagAdd && card.contains(tagAdd)) {
            e.stopPropagation();
            promptAddTag(card, url);
            return;
        }

        const tagX = e.target.closest('.tag-x');
        if (tagX && card.contains(tagX)) {
            e.stopPropagation();
            const chip = tagX.closest('.tag-chip');
            if (chip) {
                removePaperTag(url, chip.dataset.tag);
                renderCardTags(card, url);
            }
            return;
        }

        const tagLabel = e.target.closest('.tag-label');
        if (tagLabel && card.contains(tagLabel)) {
            e.stopPropagation();
            const raw = tagLabel.textContent || '';
            const name = raw.startsWith('#') ? raw.slice(1) : raw;
            filterByTag(name);
            return;
        }

        const toggleBtn = e.target.closest('.summary-toggle-btn');
        if (toggleBtn && toggleBtn.tagName !== 'SUMMARY' && card.contains(toggleBtn)) {
            e.stopPropagation();
            const summaryEl = card.querySelector('.paper-summary');
            if (!summaryEl) return;
            const isCollapsed = summaryEl.classList.contains('collapsed');
            summaryEl.classList.toggle('collapsed', !isCollapsed);
            toggleBtn.textContent = isCollapsed ? '收合摘要 ▴' : '展開原文摘要 ▾';
            return;
        }
    });
}

// ── 卡片 template（一次取得，之後 clone）──────────────────────
let _cardTpl = null;
function getCardTemplate() {
    if (_cardTpl) return _cardTpl;
    const tpl = document.getElementById('paperCardTemplate');
    _cardTpl = tpl ? tpl.content.firstElementChild : null;
    return _cardTpl;
}

function buildCard(paper, index) {
    const tpl = getCardTemplate();
    const card = tpl ? tpl.cloneNode(true) : document.createElement('div');
    if (!tpl) card.className = 'paper-card';

    card.style.animationDelay = `${(index % 20) * 0.03}s`;
    card.dataset.summary = paper.summary;
    card.dataset.cacheKey = paper.url;
    card.dataset.url = paper.url;

    const isStarred = favorites.has(paper.url);
    const isRead = readSet.has(paper.url);
    const hasNote = !!notesMap[paper.url];
    if (isRead) card.classList.add('is-read');

    // Star
    const starBtn = card.querySelector('.star-btn');
    if (isStarred) {
        starBtn.classList.add('starred');
        starBtn.title = '取消收藏';
        starBtn.querySelector('use')?.setAttribute('href', '#icon-star-filled');
    }

    // Read
    const readBtn = card.querySelector('.read-btn');
    readBtn.querySelector('use')?.setAttribute('href', isRead ? '#icon-check' : '#icon-circle');
    readBtn.querySelector('.read-label').textContent = isRead ? '已讀' : '未讀';
    if (isRead) readBtn.classList.add('is-read');

    // Venue
    const venue = detectVenue(paper);
    const venueSlot = card.querySelector('.venue-badge-slot');
    if (venue && venueSlot) {
        const span = document.createElement('span');
        span.className = 'venue-badge';
        span.style.setProperty('--venue-color', venue.color);
        span.textContent = venue.label;
        venueSlot.replaceWith(span);
    } else {
        venueSlot?.remove();
    }

    // Signal 6 軸分數
    renderSignalBlock(card, paper);

    // Title / link
    const titleLink = card.querySelector('.paper-title-link');
    titleLink.href = paper.url;
    titleLink.textContent = paper.title;

    // Authors
    const authorsEl = card.querySelector('.paper-authors');
    paper.authors.forEach((a, i) => {
        if (i > 0) {
            const sep = document.createElement('span');
            sep.className = 'author-sep';
            sep.textContent = ', ';
            authorsEl.appendChild(sep);
        }
        const btn = document.createElement('button');
        btn.className = 'author-btn';
        btn.dataset.author = a;
        btn.textContent = a;
        authorsEl.appendChild(btn);
    });

    // Summary
    card.querySelector('.paper-summary').textContent = paper.summary;

    // Footer
    card.querySelector('.paper-date').textContent = paper.published;

    // Badges（引用、高影響、綜述）
    const badgeSlot = card.querySelector('.badge-slot');
    const citCount = getCitationCount(paper.url);
    const inflCount = getInfluentialCitations(paper.url);
    const refCount = getRefCount(paper.url);
    const badgeFrag = document.createDocumentFragment();
    if (citCount >= 0) {
        const s = document.createElement('span');
        s.className = 'citation-badge';
        s.textContent = `📈 ${citCount} 引用`;
        badgeFrag.appendChild(s);
    }
    if (inflCount > 0) {
        const s = document.createElement('span');
        s.className = 'influential-badge';
        s.title = '高影響引用：被後續研究大量採用';
        s.textContent = `💡 ${inflCount} 高影響`;
        badgeFrag.appendChild(s);
    }
    if (refCount > 100) {
        const s = document.createElement('span');
        s.className = 'survey-badge';
        s.title = `引用文獻數 ${refCount}，可能為綜述論文`;
        s.textContent = '📚 綜述';
        badgeFrag.appendChild(s);
    }
    // 引用速度（快速竄紅指標）
    const speed = getCitationSpeed(paper);
    if (speed >= 2) {
        const s = document.createElement('span');
        s.className = 'speed-badge';
        s.title = '引用速度：每月新增的引用數';
        s.textContent = `🚀 ${speed >= 10 ? speed.toFixed(0) : speed.toFixed(1)}/月`;
        badgeFrag.appendChild(s);
    }
    // 頂會 h5 指標
    const h5 = getVenueH5(paper);
    if (h5 >= 100) {
        const s = document.createElement('span');
        s.className = 'h5-badge';
        s.title = 'Google Scholar h5-index：期刊/會議近 5 年影響力指標';
        s.textContent = `h5·${h5}`;
        badgeFrag.appendChild(s);
    }
    // HF Daily 社群 upvote
    if (paper.hf_upvotes >= 5) {
        const s = document.createElement('span');
        s.className = 'hf-badge';
        s.title = 'HuggingFace Daily Papers 社群 upvote 數';
        s.textContent = `🤗 ${paper.hf_upvotes}`;
        badgeFrag.appendChild(s);
    }
    badgeSlot.replaceWith(badgeFrag);

    // GitHub
    const pwcData = getPwcData(paper.url);
    const githubMatch = paper.summary.match(/https?:\/\/github\.com\/[\w\-]+\/[\w\-](?:[\w\-.]*[\w\-])?/i);
    const githubUrl = pwcData?.github_url || (githubMatch ? githubMatch[0] : null);
    const githubSlot = card.querySelector('.github-slot');
    if (githubUrl && githubSlot) {
        const pwcStars = pwcData?.stars || 0;
        const starsText = pwcStars > 0
            ? ` ⭐${pwcStars >= 1000 ? (pwcStars / 1000).toFixed(1) + 'k' : pwcStars}`
            : '';
        const a = document.createElement('a');
        a.href = githubUrl;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        a.className = 'github-link-btn';
        a.title = '查看程式碼';
        a.innerHTML = `<svg width="13" height="13"><use href="#icon-github"/></svg>Code${escapeHtml(starsText)}`;
        githubSlot.replaceWith(a);
    } else {
        githubSlot?.remove();
    }

    // Tags
    renderCardTags(card, paper.url);

    // Note button state
    const noteBtn = card.querySelector('.note-btn');
    if (hasNote) {
        noteBtn.classList.add('has-note');
        noteBtn.querySelector('use')?.setAttribute('href', '#icon-note-filled');
    }

    // Paper footer link
    card.querySelector('.paper-link').href = paper.url;

    return card;
}

function renderPapers(papers, customTitle) {
    _bindPapersGridDelegation();
    currentFilteredPapers = papers;
    lastCustomTitle = customTitle ?? null;
    papersGrid.innerHTML = '';

    if (papers.length === 0) {
        noResults.classList.remove('hidden');
        papersGrid.classList.add('hidden');
        loader.classList.add('hidden');
        const q = searchInput.value.trim() || currentCategory;
        renderTopicSuggestions(q);
        return;
    }

    noResults.classList.add('hidden');
    document.getElementById('topicSuggestions')?.classList.add('hidden');
    papersGrid.classList.remove('hidden');
    loader.classList.add('hidden');

    const totalPages = Math.ceil(papers.length / PAPERS_PER_PAGE);
    if (currentPage > totalPages) currentPage = totalPages;

    // 標題
    let themeTitle;
    if (customTitle) {
        themeTitle = customTitle;
    } else if (currentCategory === "all") {
        themeTitle = "本週所有最新論文";
    } else if (currentCategory === "top_conf") {
        themeTitle = `本週入選 ${ACTIVE_DISCIPLINE?.name || ''} 頂尖會議／期刊的論文`;
    } else if (CONF_FILTERS.has(currentCategory)) {
        const confName = document.querySelector(`.category-btn[data-filter="${currentCategory}"]`)?.innerText || currentCategory;
        themeTitle = `本週提及 ${confName} 的論文`;
    } else if (currentCategory === "favorites") {
        themeTitle = "⭐ 我的收藏論文";
    } else {
        const activeLabel = document.querySelector('.category-btn.active .label-span')?.textContent.trim()
            || document.querySelector('.category-btn.active')?.textContent.trim() || currentCategory;
        themeTitle = `本週關於「${activeLabel}」的論文`;
    }

    const countHeader = document.createElement('div');
    countHeader.className = 'count-header';
    const theme = document.createElement('span');
    theme.className = 'count-theme';
    theme.textContent = themeTitle;
    const meta = document.createElement('span');
    meta.className = 'count-meta';
    meta.textContent = `共 ${papers.length} 篇　第 ${currentPage} / ${totalPages} 頁`;
    countHeader.append(theme, meta);
    papersGrid.appendChild(countHeader);

    const start = (currentPage - 1) * PAPERS_PER_PAGE;
    const pagePapers = papers.slice(start, start + PAPERS_PER_PAGE);

    const frag = document.createDocumentFragment();
    pagePapers.forEach((paper, index) => {
        const card = buildCard(paper, index);
        frag.appendChild(card);
        translateObserver.observe(card);
    });
    papersGrid.appendChild(frag);

    renderPagination(papers.length);

    // 背景抓取當前頁面的 PwC 資料（code availability + stars）
    if (!_pwcPageFetching) {
        _pwcPageFetching = true;
        fetchPwcData(pagePapers).then(updated => {
            _pwcPageFetching = false;
            if (updated) renderPapers(currentFilteredPapers, lastCustomTitle);
        });
    }
}

// ── Semantic Scholar 引用次數 ──────────────────────────────────
const S2_CACHE_KEY = 's2_citations_v1';
const S2_TTL = 6 * 3600 * 1000; // 6 小時
const S2_MAX = 10000;
let s2Cache = {};
try { s2Cache = JSON.parse(localStorage.getItem(S2_CACHE_KEY) || '{}'); } catch (e) { }
function purgeS2() {
    const keys = Object.keys(s2Cache);
    if (keys.length <= S2_MAX) return;
    keys.sort((a, b) => (s2Cache[a]?.at || 0) - (s2Cache[b]?.at || 0));
    for (let i = 0; i < keys.length - S2_MAX; i++) delete s2Cache[keys[i]];
}

function getArxivId(url) {
    const m = url.match(/abs\/(\d{4}\.\d+)/);
    return m ? m[1] : null;
}

function getCitationCount(url) {
    const id = getArxivId(url);
    return (id && s2Cache[id] !== undefined) ? s2Cache[id].count : -1;
}

function getS2Venue(url) {
    const id = getArxivId(url);
    return (id && s2Cache[id]) ? (s2Cache[id].venue || '') : '';
}
function getInfluentialCitations(url) {
    const id = getArxivId(url);
    return (id && s2Cache[id] !== undefined) ? (s2Cache[id].influential ?? 0) : -1;
}
function getRefCount(url) {
    const id = getArxivId(url);
    return (id && s2Cache[id] !== undefined) ? (s2Cache[id].refs ?? 0) : -1;
}

// 以 arXiv id 推 (大約) 發表時間：yymm.nnnnn → 20yy-mm
function approxArxivDate(url) {
    const id = getArxivId(url);
    if (!id) return null;
    const m = id.match(/^(\d{2})(\d{2})\./);
    if (!m) return null;
    const year = 2000 + parseInt(m[1], 10);
    const month = parseInt(m[2], 10);
    if (month < 1 || month > 12) return null;
    return new Date(year, month - 1, 15);
}

function daysSincePublication(paper) {
    let d = null;
    if (paper.published) {
        const parsed = new Date(paper.published);
        if (!isNaN(parsed.getTime())) d = parsed;
    }
    if (!d) d = approxArxivDate(paper.url);
    if (!d) return null;
    return Math.max(1, (Date.now() - d.getTime()) / 86400000);
}

// 引用速度：每 30 天引用數。越大越熱。
function getCitationSpeed(paper) {
    const cit = getCitationCount(paper.url);
    if (cit <= 0) return 0;
    const days = daysSincePublication(paper);
    if (!days || days < 3) return 0;          // 太新 → 數據噪音
    return (cit / days) * 30;
}

// 頂會 venue → Google Scholar h5 近似值（2024 公開榜單，用於顯示權重）
const VENUE_H5 = {
    'cvpr': 440, 'nature': 440, 'neurips': 378, 'iccv': 291, 'eccv': 240,
    'icml': 268, 'iclr': 304, 'aaai': 220, 'acl': 192, 'emnlp': 156,
    'tpami': 179, 'ijcv': 111, 'tip': 124, 'tmlr': 80, 'wacv': 96,
    'bmvc': 66, 'siggraph': 101, 'miccai': 122, 'sigkdd': 150, 'kdd': 150,
};
function getVenueH5(paper) {
    const v = (getS2Venue(paper.url) || '').toLowerCase();
    if (!v) return 0;
    for (const [k, h5] of Object.entries(VENUE_H5)) {
        if (v.includes(k)) return h5;
    }
    return 0;
}

// ── 6 軸訊號分數（Signal）──────────────────────────────────────
// 每個軸歸一化到 0..1，composite 為加權平均後 × 100
const SIGNAL_WEIGHTS = {
    novelty: 0.12,  // 原創新穎度：投稿越新權重
    cite:    0.22,  // 總引用
    hf:      0.18,  // 社群投票
    venue:   0.18,  // 頂會/期刊 h5
    code:    0.12,  // 有開源 + star 數
    recency: 0.18,  // 引用速度（每月）
};
function _norm01(x) { return Math.max(0, Math.min(1, x)); }
function _logScale(v, cap) {
    // log(1+v) / log(1+cap) → 對數平滑，v>=cap 視為 1
    if (v <= 0) return 0;
    return _norm01(Math.log1p(v) / Math.log1p(cap));
}

const SIGNAL_AXIS_ORDER = ['novelty', 'cite', 'hf', 'venue', 'code', 'recency'];
const SIGNAL_AXIS_LABEL = {
    novelty: '新',     // Novelty
    cite:    '引',     // Citations
    hf:      '🤗',    // HF upvotes
    venue:   '會',     // Venue h5
    code:    '碼',     // Code / stars
    recency: '速',     // Citation speed
};
const SIGNAL_AXIS_TITLE = {
    novelty: '新穎度（發表時間越新越高）',
    cite:    '引用數（對數標準化）',
    hf:      'HuggingFace 社群 upvote',
    venue:   '頂會/期刊 h5 分數',
    code:    '開源釋出 + GitHub star',
    recency: '引用速度（每月新增）',
};

function renderSignalBlock(card, paper) {
    const block = card.querySelector('.signal-block');
    if (!block) return;
    const { score, axes } = computeSignal(paper);
    if (score <= 0) { block.remove(); return; }
    block.hidden = false;
    block.querySelector('.signal-score-num').textContent = score;
    const axesEl = block.querySelector('.signal-axes');
    const frag = document.createDocumentFragment();
    for (const k of SIGNAL_AXIS_ORDER) {
        const pct = Math.round((axes[k] || 0) * 100);
        const bar = document.createElement('span');
        bar.className = 'signal-axis';
        bar.dataset.axis = k;
        bar.title = `${SIGNAL_AXIS_TITLE[k]}：${pct}`;
        bar.innerHTML = `<span class="sa-label">${SIGNAL_AXIS_LABEL[k]}</span><span class="sa-track"><span class="sa-fill" style="width:${pct}%"></span></span>`;
        frag.appendChild(bar);
    }
    axesEl.appendChild(frag);
}

function computeSignal(paper) {
    const days = daysSincePublication(paper) || 14;
    // 越新越高（< 2 天 ≈ 1，7 天 ≈ 0.7，30 天 ≈ 0.3，> 180 天 → 0）
    const novelty = _norm01(Math.exp(-days / 30));

    const cit = Math.max(0, getCitationCount(paper.url));
    const cite = _logScale(cit, 500);

    const hfUp = Math.max(0, paper.hf_upvotes || 0);
    const hf = _logScale(hfUp, 200);

    const h5 = getVenueH5(paper);
    const venue = _norm01(h5 / 400);

    const pwc = getPwcData(paper.url) || {};
    const hasCode = !!pwc.github_url || /https?:\/\/github\.com\//i.test(paper.summary || '');
    const stars = pwc.stars || 0;
    const code = hasCode ? _norm01(0.35 + 0.65 * _logScale(stars, 5000)) : 0;

    const speed = getCitationSpeed(paper);           // cits/月
    const recency = _logScale(speed, 50);

    const axes = { novelty, cite, hf, venue, code, recency };
    let total = 0;
    for (const k in SIGNAL_WEIGHTS) total += axes[k] * SIGNAL_WEIGHTS[k];
    return { axes, score: Math.round(total * 100) };
}

async function fetchCitationCounts(papers) {
    const progressBar = document.getElementById('topProgressBar');
    if (progressBar) { progressBar.style.width = '0%'; progressBar.classList.add('active'); }

    const now = Date.now();
    const ids = [...new Set(papers.map(p => getArxivId(p.url)).filter(Boolean))];
    const needed = ids.filter(id => {
        const c = s2Cache[id];
        return !c || (now - (c.at || 0)) > S2_TTL;
    });
    const finish = () => {
        if (progressBar) {
            progressBar.style.width = '100%';
            setTimeout(() => { progressBar.classList.remove('active'); progressBar.style.width = '0%'; }, 600);
        }
    };
    if (!needed.length) { finish(); return; }

    // Server proxies Semantic Scholar with shared cache
    try {
        const res = await fetch('/api/citations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ arxiv_ids: needed }),
        });
        if (res.ok) {
            const data = await res.json();
            const t = Date.now();
            for (const [id, entry] of Object.entries(data.results || {})) {
                s2Cache[id] = { ...entry, at: t };
            }
            purgeS2();
            scheduleSave(S2_CACHE_KEY, () => s2Cache);
        }
    } catch (e) { /* ignore */ }
    finish();
}

// ── Papers with Code ──────────────────────────────────────────
const PWC_CACHE_KEY = 'pwc_cache_v1';
const PWC_TTL = 24 * 3600 * 1000; // 24 小時
const PWC_MAX = 10000;
let pwcCache = {};
try { pwcCache = JSON.parse(localStorage.getItem(PWC_CACHE_KEY) || '{}'); } catch(e) {}
function purgePwc() {
    const keys = Object.keys(pwcCache);
    if (keys.length <= PWC_MAX) return;
    keys.sort((a, b) => (pwcCache[a]?.at || 0) - (pwcCache[b]?.at || 0));
    for (let i = 0; i < keys.length - PWC_MAX; i++) delete pwcCache[keys[i]];
}

function getPwcData(url) {
    const id = getArxivId(url);
    return (id && pwcCache[id]) ? pwcCache[id] : null;
}

async function fetchPwcData(papers) {
    const now = Date.now();
    const ids = [...new Set(papers.map(p => getArxivId(p.url)).filter(Boolean))];
    const needed = ids.filter(id => {
        const c = pwcCache[id];
        return !c || (now - (c.at || 0)) > PWC_TTL;
    });
    if (!needed.length) return false;

    try {
        const res = await fetch(`/api/pwc?arxiv_ids=${encodeURIComponent(needed.join(','))}`);
        if (!res.ok) return false;
        const data = await res.json();
        const t = Date.now();
        for (const id of needed) {
            const entry = data.results?.[id];
            if (entry) {
                pwcCache[id] = { github_url: entry.github_url || null, stars: entry.stars || 0, at: t };
            } else {
                pwcCache[id] = { at: t };  // 標記已探測避免重複呼叫
            }
        }
        purgePwc();
        scheduleSave(PWC_CACHE_KEY, () => pwcCache);
        return true;
    } catch (e) {
        return false;
    }
}

function applyFilter(pool, query) {
    const cat = currentCategory === 'all' || currentCategory === 'favorites' || currentCategory === 'top_conf' || currentCategory === 'hf_daily' || CONF_FILTERS.has(currentCategory)
        ? null
        : currentCategory.toLowerCase();
    const confKey = CONF_FILTERS.get(currentCategory);

    return pool.filter(paper => {
        const tLc = paper._titleLc   ?? paper.title.toLowerCase();
        const sLc = paper._summaryLc ?? paper.summary.toLowerCase();
        const aLc = paper._authorsLc ?? paper.authors.join(' ').toLowerCase();

        const matchesQuery = !query ||
            tLc.includes(query) || aLc.includes(query) || sLc.includes(query);

        let matchesCategory = true;
        if (currentCategory === 'favorites') {
            matchesCategory = favorites.has(paper.url);
        } else if (currentCategory === 'top_conf') {
            matchesCategory = TOP_CONF_KEYWORDS.some(c => tLc.includes(c) || sLc.includes(c));
        } else if (confKey) {
            matchesCategory = tLc.includes(confKey) || sLc.includes(confKey);
        } else if (cat) {
            matchesCategory = tLc.includes(cat) || sLc.includes(cat);
        }

        return matchesQuery && matchesCategory;
    });
}

async function ensureMonthPapers() {
    if (monthPapers.length > 0) return;
    loader.classList.remove('hidden');
    papersGrid.classList.add('hidden');
    try {
        const disc = ACTIVE_DISCIPLINE?.id || 'cv';
        const res = await fetch(`/api/papers?days=30&discipline=${encodeURIComponent(disc)}`);
        if (!res.ok) throw new Error();
        monthPapers = indexPapers((await res.json()).papers);
    } catch (e) {
        monthPapers = allPapers; // fallback
    } finally {
        loader.classList.add('hidden');
        papersGrid.classList.remove('hidden');
    }
}

let _hfDailyCache = null;        // 原始（全領域）結果
let _hfDailyFiltered = null;     // 依當前 discipline 篩過的結果
async function ensureHfDaily() {
    if (!_hfDailyCache) {
        const res = await fetch('/api/trending?source=hf_daily&days=14');
        if (!res.ok) throw new Error('HF Daily fetch failed');
        const data = await res.json();
        _hfDailyCache = indexPapers(data.papers || []);
    }
    if (_hfDailyFiltered) return _hfDailyFiltered;
    _hfDailyFiltered = filterHfDailyByDiscipline(_hfDailyCache);
    return _hfDailyFiltered;
}

// 依當前 discipline 的 conf 關鍵字 + 主題關鍵字做 substring 匹配
// 找不到任何匹配時回傳原始清單（避免 HF Daily 顯示完全空白）
function filterHfDailyByDiscipline(papers) {
    const d = ACTIVE_DISCIPLINE;
    if (!d || !papers?.length) return papers || [];
    const keywords = new Set();
    for (const c of d.confs) keywords.add(c.key.toLowerCase());
    for (const t of d.topics) keywords.add(t.toLowerCase());
    for (const arr of Object.values(d.synonyms || {})) for (const s of arr) keywords.add(s.toLowerCase());
    const kwList = [...keywords].filter(k => k.length >= 2);
    const hit = papers.filter(p => {
        const tLc = p._titleLc ?? p.title.toLowerCase();
        const sLc = p._summaryLc ?? p.summary.toLowerCase();
        return kwList.some(k => tLc.includes(k) || sLc.includes(k));
    });
    return hit.length > 0 ? hit : papers;
}

async function filterPapers() {
    currentPage = 1;
    const query = searchInput.value.toLowerCase().trim();
    const sortValue = currentSortValue;

    // HF Daily：由後端拉 HuggingFace 每日精選
    if (currentCategory === 'hf_daily') {
        papersGrid.classList.add('hidden');
        noResults.classList.add('hidden');
        loader.classList.remove('hidden');
        try {
            let papers = await ensureHfDaily();
            if (query) papers = applyFilter(papers, query);
            // 依社群 upvote 排序
            papers = [...papers].sort((a, b) => (b.hf_upvotes || 0) - (a.hf_upvotes || 0));
            const disciplineTag = ACTIVE_DISCIPLINE ? `${ACTIVE_DISCIPLINE.icon} ${ACTIVE_DISCIPLINE.name}` : '';
            const allTotal = _hfDailyCache?.length || 0;
            const filteredTotal = papers.length;
            const suffix = disciplineTag && filteredTotal !== allTotal
                ? `（${disciplineTag} 相關 · 依社群 upvote）`
                : '（依社群 upvote 排序）';
            renderPapers(papers, `🤗 HuggingFace 每日精選${suffix}`);
        } catch (e) {
            loader.classList.add('hidden');
            alert('HF Daily 載入失敗：' + e.message);
        }
        return;
    }

    // 會議篩選：搜尋全 arXiv，不受 7 天視窗限制
    if (CONF_FILTERS.has(currentCategory)) {
        const keyword = CONF_FILTERS.get(currentCategory);
        const confName = document.querySelector(`.conf-item[data-filter="${currentCategory}"]`)?.textContent.trim() || keyword.toUpperCase();
        papersGrid.classList.add('hidden');
        noResults.classList.add('hidden');
        loader.classList.remove('hidden');
        try {
            const searchQ = query ? `${keyword} ${query}` : keyword;
            const res = await fetch(`/api/search?q=${encodeURIComponent(searchQ)}&max_results=100`);
            if (!res.ok) throw new Error('Search failed');
            const data = await res.json();
            renderPapers(indexPapers(data.papers), `${confName} 相關論文（全網搜尋）`);
        } catch (e) {
            loader.classList.add('hidden');
            alert('搜尋失敗：' + e.message);
        }
        return;
    }

    let pool = allPapers;
    let titleSuffix = '';

    if (sortValue === 'hot_month') {
        await ensureMonthPapers();
        pool = monthPapers;
        titleSuffix = '（本月，依引用排序）';
    } else if (sortValue === 'hot_week') {
        titleSuffix = '（本週，依引用排序）';
    }

    let filtered = applyFilter(pool, query);

    if (sortValue === 'hot_week' || sortValue === 'hot_month') {
        await fetchCitationCounts(filtered);
        filtered.sort((a, b) => getCitationCount(b.url) - getCitationCount(a.url));
    } else if (sortValue === 'citations') {
        await fetchCitationCounts(filtered);
        filtered.sort((a, b) => getCitationCount(b.url) - getCitationCount(a.url));
        titleSuffix = '（依引用數排序）';
    } else if (sortValue === 'signal') {
        await fetchCitationCounts(filtered);
        filtered.sort((a, b) => computeSignal(b).score - computeSignal(a).score);
        titleSuffix = '（綜合 Signal 分數）';
    }

    const titlePrefix = sortValue === 'signal' ? '本週 Signal 推薦' :
                        sortValue === 'citations' ? '引用最多' : '熱門論文';
    renderPapers(filtered, titleSuffix ? `${titlePrefix} ${titleSuffix}` : null);
}

function filterByTag(tag) {
    if (!tag) return;
    const urls = new Set(Object.keys(paperTags).filter(u => (paperTags[u] || []).includes(tag)));
    const matched = allPapers.filter(p => urls.has(p.url));
    // 若 allPapers 沒收錄（可能是搜尋結果裡的論文），就組一個最小 stub
    if (matched.length === 0 && urls.size > 0) {
        for (const u of urls) {
            matched.push({ url: u, title: u.split('/abs/')[1] || u, summary: '', authors: [], published: '' });
        }
    }
    renderPapers(indexPapers(matched), `標籤 #${tag}`);
}

let _searchAbort = null;
async function searchAllPapers(query) {
    currentPage = 1;
    papersGrid.classList.add('hidden');
    noResults.classList.add('hidden');
    loader.classList.remove('hidden');

    // 取消上一個搜尋，避免舊結果蓋新結果
    if (_searchAbort) _searchAbort.abort();
    _searchAbort = new AbortController();
    const signal = _searchAbort.signal;
    try {
        const res = await fetch(`/api/search?q=${encodeURIComponent(query)}&max_results=50`, { signal });
        if (!res.ok) throw new Error('Search failed');
        const data = await res.json();
        if (signal.aborted) return;
        renderPapers(indexPapers(data.papers), `全網搜尋「${escapeHtml(query)}」`);
    } catch (e) {
        if (e.name === 'AbortError') return;
        loader.classList.add('hidden');
        alert('搜尋失敗：' + e.message);
    }
}

function handleSearchInput() {
    clearTimeout(searchDebounceTimer);
    const query = searchInput.value.trim();
    if (!query) {
        filterPapers();
        return;
    }
    searchDebounceTimer = setTimeout(() => searchAllPapers(query), 500);
}

// ── 模糊主題匹配（由 applyDiscipline 填入）─────────────────────
let TOPIC_SYNONYMS = {};

function _lev(a, b) {
    if (a === b) return 0;
    if (!a.length) return b.length;
    if (!b.length) return a.length;
    let prev = new Array(b.length + 1).fill(0).map((_, i) => i);
    for (let i = 1; i <= a.length; i++) {
        const curr = [i];
        for (let j = 1; j <= b.length; j++) {
            const cost = a[i - 1] === b[j - 1] ? 0 : 1;
            curr.push(Math.min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost));
        }
        prev = curr;
    }
    return prev[b.length];
}

function suggestTopics(query, limit = 3) {
    const q = (query || '').trim().toLowerCase();
    if (!q) return [];

    const btnMap = new Map();
    document.querySelectorAll('.category-btn').forEach(b => {
        const f = b.dataset.filter;
        if (!f || f === 'all' || f === 'favorites' || f === 'top_conf') return;
        const label = (b.querySelector('.label-span')?.textContent || b.textContent || f).trim();
        btnMap.set(f, label);
    });

    const scored = [];
    for (const [filter, label] of btnMap) {
        const candidates = [filter.toLowerCase(), label.toLowerCase(), ...(TOPIC_SYNONYMS[filter] || [])];
        let best = Infinity;
        for (const c of candidates) {
            if (!c) continue;
            if (c.includes(q) || q.includes(c)) { best = 0; break; }
            const d = _lev(q, c);
            const norm = d / Math.max(c.length, q.length);
            if (norm < best) best = norm;
        }
        if (best <= 0.45) scored.push({ filter, label, score: best });
    }
    scored.sort((a, b) => a.score - b.score);
    return scored.slice(0, limit);
}

function renderTopicSuggestions(query) {
    const box = document.getElementById('topicSuggestions');
    if (!box) return;
    const chips = box.querySelector('.ts-chips');
    chips.innerHTML = '';
    const list = suggestTopics(query, 3);
    if (list.length === 0) { box.classList.add('hidden'); return; }
    for (const { filter, label } of list) {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'ts-chip';
        chip.textContent = label;
        chip.addEventListener('click', () => {
            searchInput.value = '';
            const target = document.querySelector(`.category-btn[data-filter="${CSS.escape(filter)}"]`);
            if (target) target.click();
        });
        chips.appendChild(chip);
    }
    box.classList.remove('hidden');
}

// ── 搜尋推薦詞（由 applyDiscipline 填入）─────────────────────
let SEARCH_SUGGESTIONS = [];

function createSuggestionsDropdown() {
    const box = searchInput.closest('.search-box') || searchInput.parentElement;
    box.style.position = 'relative';

    const dropdown = document.createElement('div');
    dropdown.id = 'searchSuggestDropdown';
    dropdown.className = 'search-suggest-dropdown';

    SEARCH_SUGGESTIONS.forEach(kw => {
        const chip = document.createElement('button');
        chip.className = 'suggest-chip';
        chip.type = 'button';
        chip.textContent = kw;
        chip.addEventListener('mousedown', (e) => {
            e.preventDefault(); // 避免 blur 先觸發
            searchInput.value = kw;
            hideSuggestions();
            searchAllPapers(kw);
        });
        dropdown.appendChild(chip);
    });

    box.appendChild(dropdown);
    return dropdown;
}

let suggestDropdown = null;

function showSuggestions() {
    if (!suggestDropdown) suggestDropdown = createSuggestionsDropdown();
    suggestDropdown.classList.add('open');
}

function hideSuggestions() {
    if (suggestDropdown) suggestDropdown.classList.remove('open');
}

searchInput.addEventListener('focus', showSuggestions);
searchInput.addEventListener('blur', () => setTimeout(hideSuggestions, 150));

// Event Listeners
searchInput.addEventListener('input', handleSearchInput);

// ── 右鍵選單 ───────────────────────────────────────────────────
let ctxTarget = null;

function showCtxMenu(btn, x, y) {
    const menu = document.getElementById('ctxMenu');
    ctxTarget = btn;

    const isPinned = btn.dataset.pinned === 'true';
    document.getElementById('ctxUnpin').style.display = isPinned ? '' : 'none';
    document.getElementById('ctxEdit').style.display   = isPinned ? 'none' : '';
    document.getElementById('ctxDelete').style.display = isPinned ? 'none' : '';

    menu.style.left = x + 'px';
    menu.style.top = y + 'px';
    menu.classList.remove('hidden');
    requestAnimationFrame(() => {
        const r = menu.getBoundingClientRect();
        if (r.right > window.innerWidth) menu.style.left = (x - r.width) + 'px';
        if (r.bottom > window.innerHeight) menu.style.top = (y - r.height) + 'px';
    });
}

function hideCtxMenu() {
    document.getElementById('ctxMenu').classList.add('hidden');
    ctxTarget = null;
}

// ── 標籤文字 helper ─────────────────────────────────────────────
function getLabelText(btn) {
    const span = btn.querySelector('span.label-span');
    return span ? span.textContent.trim() : btn.textContent.trim();
}
function setLabelText(btn, text) {
    const span = btn.querySelector('span.label-span');
    if (span) span.textContent = text;
    else btn.textContent = text;
}

// ── 內建標籤刪除／重新命名持久化 ────────────────────────────────
let DELETED_BUILTIN_KEY = 'visionary_deleted_builtins';
let RENAMED_BUILTIN_KEY = 'visionary_renamed_builtins';

function loadDeletedBuiltins() {
    try { return new Set(JSON.parse(localStorage.getItem(DELETED_BUILTIN_KEY) || '[]')); } catch (e) { return new Set(); }
}
function saveDeletedBuiltins(s) { localStorage.setItem(DELETED_BUILTIN_KEY, JSON.stringify([...s])); }
function loadRenamedBuiltins() {
    try { return JSON.parse(localStorage.getItem(RENAMED_BUILTIN_KEY) || '{}'); } catch (e) { return {}; }
}
function saveRenamedBuiltins(map) { localStorage.setItem(RENAMED_BUILTIN_KEY, JSON.stringify(map)); }

// 特殊 filter：只改顯示名，不改 data-filter（篩選邏輯依賴它）
// 由 applyDiscipline 依當前 discipline 動態重建
let CONF_FILTERS = new Map();
let SPECIAL_FILTERS = new Set();

function applyBuiltinModifications() {
    const deleted = loadDeletedBuiltins();
    const renames = loadRenamedBuiltins();
    document.querySelectorAll('.category-btn:not([data-custom])').forEach(btn => {
        const orig = btn.dataset.filter;
        btn.dataset.originalFilter = orig;
        if (deleted.has(orig)) {
            if (currentCategory === orig) currentCategory = 'all';
            btn.remove();
        } else if (renames[orig]) {
            const { label, filter } = renames[orig];
            setLabelText(btn, label);
            btn.dataset.filter = filter;
        }
    });
}

// ── 編輯標籤 ────────────────────────────────────────────────────
function editBtnLabel(btn) {
    const origFilter = btn.dataset.originalFilter || btn.dataset.filter;
    const currentText = getLabelText(btn);
    const newLabel = prompt('輸入新名稱：', currentText);
    if (!newLabel || !newLabel.trim() || newLabel.trim() === currentText) return;
    const trimmed = newLabel.trim();

    setLabelText(btn, trimmed);

    const isSpecial = SPECIAL_FILTERS.has(origFilter);
    const newFilter = isSpecial ? origFilter : trimmed.toLowerCase();

    if (currentCategory === btn.dataset.filter) currentCategory = newFilter;
    btn.dataset.filter = newFilter;

    if (btn.dataset.custom === 'true') {
        saveCustomTopics();
    } else {
        const renames = loadRenamedBuiltins();
        renames[origFilter] = { label: trimmed, filter: newFilter };
        saveRenamedBuiltins(renames);
    }
    showToast(`已重新命名為「${trimmed}」`);
    filterPapers();
}

// ── 刪除標籤 ────────────────────────────────────────────────────
function deleteCategoryBtn(btn) {
    const label = getLabelText(btn);
    const origFilter = btn.dataset.originalFilter || btn.dataset.filter;
    const isCustom = btn.dataset.custom === 'true';

    if (currentCategory === btn.dataset.filter) {
        currentCategory = 'all';
        const allBtn = document.querySelector('.category-btn[data-filter="all"]');
        if (allBtn) {
            document.querySelectorAll('.category-btn').forEach(b => b.classList.remove('active'));
            allBtn.classList.add('active');
        }
        filterPapers();
    }

    btn.remove();
    bindCategoryBtns();

    if (isCustom) {
        saveCustomTopics();
    } else {
        const deleted = loadDeletedBuiltins();
        deleted.add(origFilter);
        saveDeletedBuiltins(deleted);
    }
    showToast(`已刪除「${label}」`);
}

// ── 分類按鈕綁定（事件委派，只綁一次，動態新增按鈕自動生效）────
function syncTopConfActiveState() {
    const topConfBtn = document.getElementById('topConfBtn');
    if (!topConfBtn) return;
    const isConfActive = CONF_FILTERS.has(currentCategory) || currentCategory === 'top_conf';
    topConfBtn.classList.toggle('active', isConfActive);
    document.querySelectorAll('.conf-item').forEach(item => {
        item.classList.toggle('active', item.dataset.filter === currentCategory);
    });
}

function _selectCategory(filter, activeEl) {
    document.querySelectorAll('.category-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.conf-item').forEach(b => b.classList.remove('active'));
    if (activeEl) activeEl.classList.add('active');
    currentCategory = filter;
    localStorage.setItem(LAST_CATEGORY_KEY, filter);
    syncTopConfActiveState();
    filterPapers();
}

function bindCategoryBtns() {
    const filtersDiv = document.querySelector('.category-filters');
    if (!filtersDiv || filtersDiv._delegated) return;
    filtersDiv._delegated = true;

    filtersDiv.addEventListener('click', (e) => {
        const btn = e.target.closest('.category-btn');
        if (!btn || btn.classList.contains('top-conf-btn')) return;
        _selectCategory(btn.dataset.filter, btn);
    });

    filtersDiv.addEventListener('contextmenu', (e) => {
        const btn = e.target.closest('.category-btn');
        if (!btn) return;
        e.preventDefault();
        showCtxMenu(btn, e.pageX, e.pageY);
    });
}

// ── 自訂主題 ────────────────────────────────────────────────────
let CUSTOM_TOPICS_KEY = 'visionary_custom_topics';
let LAST_CATEGORY_KEY = 'visionary_last_category';

function loadCustomTopics() {
    const saved = JSON.parse(localStorage.getItem(CUSTOM_TOPICS_KEY) || '[]');
    saved.forEach(topic => addTopicBtn(topic, false));
}

function saveCustomTopics() {
    const customBtns = document.querySelectorAll('.category-btn[data-custom="true"]');
    const topics = Array.from(customBtns).map(b => b.dataset.filter);
    localStorage.setItem(CUSTOM_TOPICS_KEY, JSON.stringify(topics));
}

function showToast(msg) {
    const t = document.createElement('div');
    t.className = 'toast';
    t.textContent = msg;
    document.body.appendChild(t);
    requestAnimationFrame(() => t.classList.add('toast-show'));
    setTimeout(() => {
        t.classList.remove('toast-show');
        setTimeout(() => t.remove(), 300);
    }, 1800);
}

function addTopicBtn(topic, save = true) {
    const label = topic.trim();
    if (!label) return;

    const existing = document.querySelector(`.category-btn[data-filter="${CSS.escape(label)}"]`);
    if (existing) {
        existing.scrollIntoView({ behavior: 'smooth', inline: 'center' });
        return;
    }

    const filtersDiv = document.querySelector('.category-filters');
    const wrapper = document.querySelector('.add-topic-wrapper');

    const btn = document.createElement('button');
    btn.className = 'category-btn custom-topic-btn';
    btn.dataset.filter = label;
    btn.dataset.custom = 'true';
    btn.dataset.originalFilter = label;

    const labelSpan = document.createElement('span');
    labelSpan.className = 'label-span';
    labelSpan.textContent = label;
    btn.appendChild(labelSpan);

    filtersDiv.insertBefore(btn, wrapper);

    if (save) saveCustomTopics();
}

// Initial Load
document.addEventListener('DOMContentLoaded', () => {
    // 1) 先綁定切換領域按鈕（無論有沒有選領域都要能開啟）
    document.getElementById('switchDisciplineBtn')?.addEventListener('click', () => {
        openDisciplinePicker({ closable: true });
    });
    document.getElementById('disciplinePickerClose')?.addEventListener('click', closeDisciplinePicker);
    document.querySelector('#disciplinePicker .dp-backdrop')?.addEventListener('click', () => {
        // 僅在已有選定 discipline 時允許點背景關閉
        if (ACTIVE_DISCIPLINE) closeDisciplinePicker();
    });

    // 2) 判斷是否已有儲存的 discipline
    const saved = window.getActiveDiscipline();
    if (!saved) {
        // 首次進站：強制先讓使用者選一個領域，稍後再初始化其餘畫面
        openDisciplinePicker({ closable: false });
        return;
    }
    applyDiscipline(saved.id);

    // 3) 依 discipline 動態生成 conf-submenu + 主題按鈕
    renderDisciplineFilters();

    applyBuiltinModifications();
    loadPinnedTopics();
    loadCustomTopics();
    bindCategoryBtns();

    // 恢復上次的分類
    const savedCategory = localStorage.getItem(LAST_CATEGORY_KEY);
    if (savedCategory && savedCategory !== 'all') {
        currentCategory = savedCategory;
        // 找到對應的按鈕並設為 active
        const targetBtn = document.querySelector(`.category-btn[data-filter="${CSS.escape(savedCategory)}"]`);
        if (targetBtn) {
            document.querySelectorAll('.category-btn').forEach(b => b.classList.remove('active'));
            targetBtn.classList.add('active');
        }
    }

    fetchPapers();

    // ── 分類標籤左右箭頭 ──（側邊欄模式下不啟用）
    const filterScroll = document.querySelector('.category-filters');
    const arrowLeft    = document.getElementById('filterArrowLeft');
    const arrowRight   = document.getElementById('filterArrowRight');
    const SCROLL_STEP  = 200;
    const inSidebar    = !!document.querySelector('.side-nav .category-filters');

    function updateFilterArrows() {
        if (!filterScroll || inSidebar) return;
        arrowLeft.classList.toggle('hidden-arrow', filterScroll.scrollLeft <= 0);
        arrowRight.classList.toggle('hidden-arrow',
            filterScroll.scrollLeft + filterScroll.clientWidth >= filterScroll.scrollWidth - 1);
    }

    if (!inSidebar && filterScroll && arrowLeft && arrowRight) {
        arrowLeft.addEventListener('click', () => {
            filterScroll.scrollBy({ left: -SCROLL_STEP, behavior: 'smooth' });
        });
        arrowRight.addEventListener('click', () => {
            filterScroll.scrollBy({ left: SCROLL_STEP, behavior: 'smooth' });
        });
        filterScroll.addEventListener('scroll', updateFilterArrows, { passive: true });
        // 動畫結束後初始化箭頭狀態
        setTimeout(updateFilterArrows, 900);
    }

    // ── 頂會嚴選 子選單 hover 定位 ──
    // 移到 body 避免 transform 祖先讓 position:fixed 失效
    const topConfWrapper = document.querySelector('.top-conf-wrapper');
    const confSubmenu = document.getElementById('confSubmenu');
    let confSubmenuTimer = null;
    if (confSubmenu) document.body.appendChild(confSubmenu);

    function openConfSubmenu() {
        clearTimeout(confSubmenuTimer);
        const rect = topConfWrapper.getBoundingClientRect();
        confSubmenu.style.top = (rect.bottom + 8) + 'px';
        confSubmenu.style.left = rect.left + 'px';
        confSubmenu.classList.add('open');
    }
    function closeConfSubmenu() {
        confSubmenuTimer = setTimeout(() => confSubmenu.classList.remove('open'), 120);
    }
    if (topConfWrapper && confSubmenu) {
        topConfWrapper.addEventListener('mouseenter', openConfSubmenu);
        topConfWrapper.addEventListener('mouseleave', closeConfSubmenu);
        confSubmenu.addEventListener('mouseenter', () => clearTimeout(confSubmenuTimer));
        confSubmenu.addEventListener('mouseleave', closeConfSubmenu);

        // conf-item 點擊委派（confSubmenu 已移至 body，在此統一綁定）
        confSubmenu.addEventListener('click', (e) => {
            const item = e.target.closest('.conf-item');
            if (!item) return;
            e.stopPropagation();
            closeConfSubmenu();
            _selectCategory(item.dataset.filter, item);
        });
    }

    // ── 排序下拉選單 hover 定位 ──
    const sortWrapper = document.getElementById('sortWrapper');
    const sortSubmenu = document.getElementById('sortSubmenu');
    const sortLabel   = document.getElementById('sortLabel');
    let sortTimer = null;
    if (sortSubmenu) document.body.appendChild(sortSubmenu);

    const SORT_LABELS = { signal: 'Signal 推薦', latest: '本日最新', hot_week: '本週熱門', hot_month: '本月熱門', citations: '引用最多' };

    // 初始化：反映 localStorage 儲存的 sort 選項
    (function _initSortFromStorage() {
        if (!sortSubmenu || !sortLabel) return;
        sortLabel.textContent = SORT_LABELS[currentSortValue] || '本日最新';
        sortSubmenu.querySelectorAll('.sort-item').forEach(i => {
            i.classList.toggle('active', i.dataset.value === currentSortValue);
        });
    })();

    function openSortSubmenu() {
        clearTimeout(sortTimer);
        const rect = sortWrapper.getBoundingClientRect();
        // 右對齊：選單右端貼齊 trigger 右端，用 CSS right 定位
        sortSubmenu.style.top   = (rect.bottom + 8) + 'px';
        sortSubmenu.style.left  = 'auto';
        sortSubmenu.style.right = (window.innerWidth - rect.right) + 'px';
        sortSubmenu.classList.add('open');
    }
    function closeSortSubmenu() {
        sortTimer = setTimeout(() => sortSubmenu.classList.remove('open'), 120);
    }
    if (sortWrapper && sortSubmenu) {
        sortWrapper.addEventListener('mouseenter', openSortSubmenu);
        sortWrapper.addEventListener('mouseleave', closeSortSubmenu);
        sortSubmenu.addEventListener('mouseenter', () => clearTimeout(sortTimer));
        sortSubmenu.addEventListener('mouseleave', closeSortSubmenu);

        sortSubmenu.querySelectorAll('.sort-item').forEach(item => {
            item.addEventListener('click', () => {
                const val = item.dataset.value;
                currentSortValue = val;
                try { localStorage.setItem('visionary_sort_v2', val); } catch (e) {}
                sortLabel.textContent = SORT_LABELS[val] || val;
                sortSubmenu.querySelectorAll('.sort-item').forEach(i => i.classList.remove('active'));
                item.classList.add('active');
                closeSortSubmenu();
                filterPapers();
            });
        });
    }

    document.getElementById('ctxUnpin').addEventListener('click', (e) => {
        e.stopPropagation();
        const btn = ctxTarget;
        hideCtxMenu();
        if (btn) {
            const label = getLabelText(btn);
            deletePinnedBtn(btn);
            showToast(`已取消釘選「${label}」`);
        }
    });
    document.getElementById('ctxEdit').addEventListener('click', (e) => {
        e.stopPropagation();
        const btn = ctxTarget;
        hideCtxMenu();
        if (btn) editBtnLabel(btn);
    });
    document.getElementById('ctxDelete').addEventListener('click', (e) => {
        e.stopPropagation();
        const btn = ctxTarget;
        hideCtxMenu();
        if (btn) deleteCategoryBtn(btn);
    });
    document.addEventListener('click', hideCtxMenu);
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') hideCtxMenu(); });

    // ── 釘選搜尋按鈕 ─────────────────────────────────────────────
    const pinSearchBtn = document.getElementById('pinSearchBtn');
    searchInput.addEventListener('input', () => {
        const hasText = searchInput.value.trim().length > 0;
        pinSearchBtn.classList.toggle('visible', hasText);
        searchInput.classList.toggle('has-text', hasText);
    });
    pinSearchBtn.addEventListener('click', () => {
        const query = searchInput.value.trim();
        if (query) addPinnedBtn(query);
    });

    document.getElementById('addTopicBtn').addEventListener('click', () => {
        const input = document.getElementById('customTopicInput');
        addTopicBtn(input.value);
        input.value = '';
        input.focus();
    });

    document.getElementById('customTopicInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            addTopicBtn(e.target.value);
            e.target.value = '';
        }
    });

    // ── 空狀態「清除搜尋」按鈕 ────────────────────────────────
    const clearSearchBtn = document.getElementById('clearSearchBtn');
    if (clearSearchBtn) {
        clearSearchBtn.addEventListener('click', () => {
            searchInput.value = '';
            currentCategory = 'all';
            document.querySelectorAll('.category-btn').forEach(b => b.classList.remove('active'));
            const allBtn = document.querySelector('.category-btn[data-filter="all"]');
            if (allBtn) allBtn.classList.add('active');
            filterPapers();
        });
    }


    // ── 鍵盤快捷鍵 ────────────────────────────────────────────
    let focusedCardIdx = -1;   // 目前聚焦的卡片索引（-1 = 無）
    const kbdHint = document.getElementById('kbdHint');
    let kbdHintTimer = null;

    function getVisibleCards() {
        return Array.from(papersGrid.querySelectorAll('.paper-card'));
    }

    function highlightCard(idx) {
        const cards = getVisibleCards();
        if (cards.length === 0) return;
        idx = Math.max(0, Math.min(idx, cards.length - 1));
        focusedCardIdx = idx;
        cards.forEach((c, i) => c.style.outline = i === idx ? '2px solid rgba(168,85,247,0.7)' : '');
        cards[idx].scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    function clearHighlight() {
        getVisibleCards().forEach(c => c.style.outline = '');
        focusedCardIdx = -1;
    }

    function showKbdHint() {
        kbdHint.classList.add('visible');
        clearTimeout(kbdHintTimer);
        kbdHintTimer = setTimeout(() => kbdHint.classList.remove('visible'), 4000);
    }

    document.addEventListener('keydown', (e) => {
        // 若正在輸入文字，不攔截
        const tag = document.activeElement.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

        const cards = getVisibleCards();

        switch (e.key) {
            case 'j':
            case 'J':
                e.preventDefault();
                if (focusedCardIdx < 0) {
                    // 若在最後一頁的最後一張，換頁
                    if (currentPage < Math.ceil(currentFilteredPapers.length / PAPERS_PER_PAGE)) {
                        goToPage(currentPage + 1);
                        setTimeout(() => highlightCard(0), 300);
                    } else {
                        highlightCard(0);
                    }
                } else {
                    if (focusedCardIdx < cards.length - 1) {
                        highlightCard(focusedCardIdx + 1);
                    } else if (currentPage < Math.ceil(currentFilteredPapers.length / PAPERS_PER_PAGE)) {
                        goToPage(currentPage + 1);
                        setTimeout(() => highlightCard(0), 300);
                    }
                }
                break;

            case 'k':
            case 'K':
                e.preventDefault();
                if (focusedCardIdx <= 0) {
                    if (currentPage > 1) {
                        goToPage(currentPage - 1);
                        setTimeout(() => { const cs = getVisibleCards(); highlightCard(cs.length - 1); }, 300);
                    } else {
                        highlightCard(0);
                    }
                } else {
                    highlightCard(focusedCardIdx - 1);
                }
                break;

            case 'f':
            case 'F':
                if (focusedCardIdx >= 0 && cards[focusedCardIdx]) {
                    e.preventDefault();
                    const starBtnKbd = cards[focusedCardIdx].querySelector('.star-btn');
                    if (starBtnKbd) starBtnKbd.click();
                }
                break;

            case 'r':
            case 'R':
                if (focusedCardIdx >= 0 && cards[focusedCardIdx]) {
                    e.preventDefault();
                    const readBtnKbd = cards[focusedCardIdx].querySelector('.read-btn');
                    if (readBtnKbd) readBtnKbd.click();
                }
                break;

            case 'n':
            case 'N':
                if (focusedCardIdx >= 0 && cards[focusedCardIdx]) {
                    e.preventDefault();
                    const noteBtnKbd = cards[focusedCardIdx].querySelector('.note-btn');
                    if (noteBtnKbd) noteBtnKbd.click();
                }
                break;

            case '?':
                e.preventDefault();
                if (kbdHint.classList.contains('visible')) {
                    kbdHint.classList.remove('visible');
                } else {
                    showKbdHint();
                }
                break;

            case 'Escape':
                clearHighlight();
                break;
        }
    });

    // 捲動時清除聚焦 + 更新回到頂部按鈕（RAF 節流，合併兩個 scroll 監聽）
    let _scrollRaf = null;
    window.addEventListener('scroll', () => {
        if (_scrollRaf) return;
        _scrollRaf = requestAnimationFrame(() => {
            _scrollRaf = null;
            if (focusedCardIdx >= 0) {
                getVisibleCards().forEach(c => c.style.outline = '');
                focusedCardIdx = -1;
            }
            backToTopBtn?.classList.toggle('visible', window.scrollY > 400);
        });
    }, { passive: true });

    // ── 每頁筆數 ──────────────────────────────────────────────────
    const perPageSelect = document.getElementById('perPageSelect');
    if (perPageSelect) {
        perPageSelect.value = String(PAPERS_PER_PAGE);
        perPageSelect.addEventListener('change', () => {
            PAPERS_PER_PAGE = parseInt(perPageSelect.value, 10);
            localStorage.setItem('visionary_per_page', String(PAPERS_PER_PAGE));
            currentPage = 1;
            renderPapers(currentFilteredPapers, lastCustomTitle);
        });
    }
});

// ── BibTeX 匯出 ──────────────────────────────────────────────
function exportFavoritesBibtex() {
    const favPapers = allPapers.filter(p => favorites.has(p.url));
    if (favPapers.length === 0) {
        showToast('收藏夾是空的，無法匯出');
        return;
    }
    const entries = favPapers.map(p => {
        const arxivId = p.url.match(/abs\/(\d{4}\.\d+)/)?.[1] || p.url;
        const firstAuthor = p.authors[0]?.split(' ').pop() || 'Unknown';
        const year = p.published?.substring(0, 4) || '2024';
        const key = `${firstAuthor}${year}_${arxivId.replace('.', '')}`;
        const authorsStr = p.authors.join(' and ');
        const title = p.title.replace(/[{}]/g, '');
        const primary = ACTIVE_DISCIPLINE?.arxivCat || 'cs.CV';
        return `@article{${key},\n  title={${title}},\n  author={${authorsStr}},\n  year={${year}},\n  eprint={${arxivId}},\n  archivePrefix={arXiv},\n  primaryClass={${primary}},\n  url={${p.url}}\n}`;
    });
    const blob = new Blob([entries.join('\n\n')], { type: 'text/plain;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `visionary_favorites_${new Date().toISOString().slice(0,10)}.bib`;
    a.click();
    URL.revokeObjectURL(a.href);
    showToast(`已匯出 ${favPapers.length} 篇論文的 BibTeX`);
}

// ── BibTeX 匯出按鈕（動態插入到收藏夾篩選按鈕後方）──────────────
const bibBtn = document.createElement('button');
bibBtn.id = 'exportBibBtn';
bibBtn.className = 'bib-export-btn hidden';
bibBtn.title = '匯出收藏夾為 BibTeX';
bibBtn.innerHTML = '📄 匯出 .bib';
const favBtn = document.querySelector('.category-btn[data-filter="favorites"]');
if (favBtn) favBtn.after(bibBtn);
bibBtn.addEventListener('click', exportFavoritesBibtex);

// 監聽分類切換：只在收藏夾模式顯示匯出按鈕
document.querySelector('.category-filters')?.addEventListener('click', () => {
    setTimeout(() => {
        const isFav = currentCategory === 'favorites';
        bibBtn.classList.toggle('hidden', !isFav);
    }, 50);
});

// ── 閱讀統計面板（快取 DOM refs，僅在資料變動時更新）────────────
const _statsEls = {};
let _statsSnapshot = '';

function updateStats() {
    if (!_statsEls.read) {
        _statsEls.read  = document.getElementById('statRead');
        _statsEls.fav   = document.getElementById('statFav');
        _statsEls.notes = document.getElementById('statNotes');
        _statsEls.total = document.getElementById('statTotal');
    }
    if (!_statsEls.read) return;

    const snapshot = `${readSet.size}|${favorites.size}|${Object.keys(notesMap).length}|${allPapers.length}`;
    if (snapshot === _statsSnapshot) return;
    _statsSnapshot = snapshot;

    _statsEls.read.textContent  = `📖 已讀 ${readSet.size}`;
    _statsEls.fav.textContent   = `⭐ 收藏 ${favorites.size}`;
    _statsEls.notes.textContent = `📝 筆記 ${Object.keys(notesMap).length}`;
    _statsEls.total.textContent = `📚 本週 ${allPapers.length} 篇`;
}

setTimeout(updateStats, 300);
setInterval(updateStats, 2000);

// ── 主題切換 ──────────────────────────────────────────────────
const THEME_KEY = 'visionary_theme';
const themeToggleBtn = document.getElementById('themeToggleBtn');
function applyTheme(mode) {
    if (mode === 'light') {
        document.body.classList.add('light-mode');
        if (themeToggleBtn) { themeToggleBtn.textContent = '☀️'; themeToggleBtn.title = '切換深色模式'; }
    } else {
        document.body.classList.remove('light-mode');
        if (themeToggleBtn) { themeToggleBtn.textContent = '🌙'; themeToggleBtn.title = '切換淺色模式'; }
    }
}
applyTheme(localStorage.getItem(THEME_KEY) || 'dark');
themeToggleBtn?.addEventListener('click', () => {
    const next = document.body.classList.contains('light-mode') ? 'dark' : 'light';
    localStorage.setItem(THEME_KEY, next);
    applyTheme(next);
});

// ── 回到頂部 ──────────────────────────────────────────────────
const backToTopBtn = document.getElementById('backToTopBtn');
backToTopBtn?.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));

// ── Service Worker 註冊 ───────────────────────────────────────
if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === 'localhost' || location.hostname === '127.0.0.1')) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js').catch(() => {});
    });
}

// ── 匯出/匯入 所有個人資料（離線備份 + 跨瀏覽器搬家）──────────
// 優先用 auth.js 提供的 key 清單；否則 fallback 掃描本地 localStorage。
const _SYNC_FALLBACK_PREFIXES = [
    'visionary_favorites', 'visionary_read_v1', 'visionary_notes_v1',
    'visionary_pinned_topics', 'visionary_custom_topics',
    'visionary_deleted_builtins', 'visionary_renamed_builtins',
    'visionary_paper_tags_v1', 'visionary_discipline', 'visionary_last_category',
];
function _syncKeys() {
    if (window.visionaryAuth?.getSyncKeys) return window.visionaryAuth.getSyncKeys();
    const out = [];
    for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (!k) continue;
        if (_SYNC_FALLBACK_PREFIXES.some(p => k === p || k.startsWith(p + ':'))) out.push(k);
    }
    return out;
}

function exportAllData() {
    const out = { _kind: 'visionary-backup', _v: 1, exportedAt: new Date().toISOString(), data: {} };
    for (const k of _syncKeys()) {
        const v = localStorage.getItem(k);
        if (v != null) {
            try { out.data[k] = JSON.parse(v); } catch (e) { out.data[k] = v; }
        }
    }
    const blob = new Blob([JSON.stringify(out, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `visionary_backup_${new Date().toISOString().slice(0,10)}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
    showToast('已匯出個人資料');
}

function _mergeImport(remote, local) {
    const merged = {};
    const keys = new Set([...Object.keys(remote || {}), ...Object.keys(local || {})]);
    for (const k of keys) {
        const r = remote?.[k], l = local?.[k];
        if (Array.isArray(r) || Array.isArray(l)) {
            merged[k] = [...new Set([...(Array.isArray(r) ? r : []), ...(Array.isArray(l) ? l : [])])];
        } else if ((r && typeof r === 'object') || (l && typeof l === 'object')) {
            merged[k] = { ...(r || {}), ...(l || {}) };
        } else {
            merged[k] = l ?? r;
        }
    }
    return merged;
}

async function importAllData(file) {
    const text = await file.text();
    let obj;
    try { obj = JSON.parse(text); }
    catch (e) { showToast('檔案不是合法 JSON'); return; }
    if (!obj || obj._kind !== 'visionary-backup' || !obj.data) {
        showToast('非本站備份檔');
        return;
    }
    const confirm = window.confirm('將匯入備份並與目前資料合併（去重），確定繼續嗎？');
    if (!confirm) return;

    const localBundle = {};
    for (const k of _syncKeys()) {
        const v = localStorage.getItem(k);
        if (v != null) {
            try { localBundle[k] = JSON.parse(v); } catch (e) { localBundle[k] = v; }
        }
    }
    const merged = _mergeImport(obj.data, localBundle);
    for (const k of _syncKeys()) {
        if (merged[k] !== undefined) {
            localStorage.setItem(k, JSON.stringify(merged[k]));
        }
    }
    if (window.visionaryAuth?.isLoggedIn?.()) {
        try { await window.visionaryAuth.pushNow?.(); } catch (e) {}
    }
    showToast('匯入完成，即將重整');
    setTimeout(() => location.reload(), 800);
}

document.getElementById('exportDataBtn')?.addEventListener('click', exportAllData);
document.getElementById('importDataBtn')?.addEventListener('click', () => {
    document.getElementById('importFileInput')?.click();
});
document.getElementById('importFileInput')?.addEventListener('change', (e) => {
    const f = e.target.files?.[0];
    if (f) importAllData(f);
    e.target.value = '';
});

// ── 保活 ping（避開 Render 免費層 15 分鐘休眠）──────────────
if (location.protocol === 'https:') {
    setInterval(() => { fetch('/api/health', { cache: 'no-store' }).catch(() => {}); }, 10 * 60 * 1000);
}

// ── 鍵盤快捷鍵說明按鈕 ────────────────────────────────────────
document.getElementById('kbdHintBtn')?.addEventListener('click', () => {
    document.getElementById('kbdHint')?.classList.toggle('visible');
});
