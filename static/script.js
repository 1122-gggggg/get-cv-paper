let allPapers = [];      // 7 天
let lastDataAsOf = 0;    // 主題論文資料建構時間（毫秒），供新鮮度標記使用
let monthPapers = [];    // 30 天（懶加載）
let quarterPapers = [];  // 90 天（懶加載,用於近三月熱門）
let currentCategory = 'all';
const LEGACY_SORT_VALUE = localStorage.getItem('visionary_sort_v2') || '';
const SORT_MIGRATION = {
    latest: 'latest',
    hot_week: 'popularity',
    hot_month: 'popularity',
    citations: 'citations',
    signal: 'value',
};
const RANGE_MIGRATION = {
    latest: 'day',
    hot_week: 'week',
    hot_month: 'month',
    citations: 'week',
    signal: 'week',
};
const SORT_VALUES = new Set(['hot', 'latest', 'popularity', 'citations', 'value', 'velocity', 'hf', 'hot3m', 'personalized']);
const TIME_RANGE_VALUES = new Set(['day', 'week', 'month', 'quarter']);
let currentSortValue = localStorage.getItem('visionary_sort_v3') || SORT_MIGRATION[LEGACY_SORT_VALUE] || 'hot';
let currentTimeRange = localStorage.getItem('visionary_time_range_v1') || RANGE_MIGRATION[LEGACY_SORT_VALUE] || 'week';
if (!SORT_VALUES.has(currentSortValue)) currentSortValue = 'hot';
if (!TIME_RANGE_VALUES.has(currentTimeRange)) currentTimeRange = 'week';
const PAPERS_PER_PAGE = 9;
let currentPage = 1;
let currentFilteredPapers = [];
let lastCustomTitle = null;

const TIME_RANGE_META = {
    day:     { label: '本日', short: '今日', en: 'Today', days: 1 },
    week:    { label: '本週', short: '本週', en: 'Week', days: 7 },
    month:   { label: '本月', short: '本月', en: 'Month', days: 30 },
    quarter: { label: '近三月', short: '三月', en: '3M', days: 90 },
};

const SORT_META = {
    hot:        { label: '熱與新', title: '熱門 × 最新' },
    latest:     { label: '最新', title: '最新論文' },
    popularity: { label: '熱門度', title: '熱門論文' },
    citations:  { label: '引用度', title: '引用最多' },
    value:      { label: '價值分數', title: '高價值論文' },
    velocity:   { label: '引用速度', title: '快速升溫' },
    hf:         { label: 'HF 熱度', title: '社群熱門' },
    hot3m:      { label: '近三月熱門', title: '近三月熱門排名' },
    personalized:{ label: '為你推薦', title: '依收藏質心個人化排序' },
};

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

function getTimeRangeMeta(range = currentTimeRange) {
    return TIME_RANGE_META[range] || TIME_RANGE_META.week;
}

function getSortMeta(value = currentSortValue) {
    return SORT_META[value] || SORT_META.latest;
}

function paperTimestamp(paper) {
    const ts = Date.parse(paper?.published || '');
    return Number.isFinite(ts) ? ts : 0;
}

// 相對時間：毫秒時間戳 → 「剛剛 / X 分鐘前 / X 小時前 / X 天前 …」
function relativeTime(ms) {
    if (!Number.isFinite(ms) || ms <= 0) return '';
    const diff = Date.now() - ms;
    if (diff < 60000) return '剛剛';
    const min = Math.floor(diff / 60000);
    if (min < 60) return `${min} 分鐘前`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr} 小時前`;
    const day = Math.floor(hr / 24);
    if (day < 30) return `${day} 天前`;
    const mo = Math.floor(day / 30);
    if (mo < 12) return `${mo} 個月前`;
    return `${Math.floor(mo / 12)} 年前`;
}

// 絕對日期（卡片日期 tooltip 用）
function absoluteDate(ms) {
    if (!Number.isFinite(ms) || ms <= 0) return '';
    const d = new Date(ms);
    const p = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

const NEW_PAPER_WINDOW_MS = 24 * 3600 * 1000;  // 近 24h 視為「新」

// ── #5 引用 / 複製 / 分享 / 匯出 BibTeX ───────────────────────────
function _paperArxivId(paper) {
    const ext = paper.external_ids || {};
    if (ext.arxiv) {
        const m = String(ext.arxiv).match(/(\d{4}\.\d{4,6})/);
        if (m) return m[1];
    }
    const m2 = (paper.url || '').match(/arxiv\.org\/(?:abs|pdf)\/(\d{4}\.\d{4,6})/i);
    return m2 ? m2[1] : null;
}

function _paperYear(paper) {
    const ts = paperTimestamp(paper);
    if (ts > 0) return new Date(ts).getFullYear();
    const m = String(paper.published || '').match(/(\d{4})/);
    return m ? Number(m[1]) : null;
}

function _bibtexKey(paper, year) {
    const clean = (s) => String(s || '').replace(/[^A-Za-z0-9]/g, '');
    const surname = ((paper.authors && paper.authors[0]) || '').trim().split(/\s+/).pop() || '';
    const titleWord = (paper.title || '').split(/\s+/).find(w => w.length > 3) || '';
    const key = clean(surname) + (year || '') + clean(titleWord).slice(0, 12);
    return key || ('paper' + (year || _paperArxivId(paper) || ''));
}

function _bibField(name, value) {
    if (!value) return '';
    return `  ${name} = {${String(value).replace(/[{}]/g, '')}},\n`;
}

function toBibtex(paper) {
    const year = _paperYear(paper);
    const key = _bibtexKey(paper, year);
    const authors = (paper.authors || []).join(' and ');
    const ext = paper.external_ids || {};
    const arxivId = _paperArxivId(paper);
    const doi = ext.doi ? String(ext.doi).replace(/^https?:\/\/(dx\.)?doi\.org\//i, '') : '';
    const entryType = (arxivId || !doi) ? 'misc' : 'article';
    let out = `@${entryType}{${key},\n`;
    out += _bibField('title', paper.title);
    out += _bibField('author', authors);
    if (year) out += `  year = {${year}},\n`;
    if (arxivId) {
        out += `  eprint = {${arxivId}},\n`;
        out += `  archivePrefix = {arXiv},\n`;
        out += _bibField('primaryClass', paper.primary_cat);
    }
    out += _bibField('doi', doi);
    out += _bibField('url', paper.url);
    out += '}\n';
    return out;
}

async function copyText(text) {
    try {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(text);
            return true;
        }
    } catch (e) { /* fall through to legacy path */ }
    try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        const ok = document.execCommand('copy');
        ta.remove();
        return ok;
    } catch (e) {
        return false;
    }
}

function downloadText(filename, text, mime = 'text/plain') {
    const blob = new Blob([text], { type: `${mime};charset=utf-8` });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

// 卡片動作浮層（引用 / 複製連結 / 分享）──共用單一元素，依需求重新定位
let _actionMenuEl = null;
let _actionMenuPaper = null;

function _ensureActionMenu() {
    if (_actionMenuEl) return _actionMenuEl;
    const menu = document.createElement('div');
    menu.id = 'cardActionMenu';
    menu.className = 'card-action-menu hidden';
    menu.setAttribute('role', 'menu');
    menu.innerHTML = `
        <button data-act="bibtex" role="menuitem">📋 複製 BibTeX 引用</button>
        <button data-act="link" role="menuitem">🔗 複製論文連結</button>
        <button data-act="share" role="menuitem" hidden>📤 分享</button>`;
    menu.addEventListener('click', (e) => {
        const btn = e.target.closest('button[data-act]');
        if (!btn || !_actionMenuPaper) return;
        e.stopPropagation();
        runCardAction(btn.dataset.act, _actionMenuPaper);
        hideActionMenu();
    });
    document.body.appendChild(menu);
    _actionMenuEl = menu;
    return menu;
}

async function runCardAction(act, paper) {
    if (act === 'bibtex') {
        const ok = await copyText(toBibtex(paper));
        showToast(ok ? '已複製 BibTeX 引用' : '複製失敗，請手動選取');
    } else if (act === 'link') {
        const ok = await copyText(paper.url || '');
        showToast(ok ? '已複製論文連結' : '複製失敗');
    } else if (act === 'share') {
        try {
            await navigator.share({ title: paper.title || '論文', url: paper.url || '' });
        } catch (e) { /* 使用者取消分享 */ }
    }
}

function openCardActionMenu(paper, anchorBtn) {
    const menu = _ensureActionMenu();
    _actionMenuPaper = paper;
    const shareBtn = menu.querySelector('button[data-act="share"]');
    if (shareBtn) shareBtn.hidden = !navigator.share;
    menu.classList.remove('hidden');
    const r = anchorBtn.getBoundingClientRect();
    const mw = menu.offsetWidth || 200;
    let left = r.left;
    if (left + mw > window.innerWidth - 8) left = window.innerWidth - mw - 8;
    menu.style.left = `${Math.max(8, left)}px`;
    menu.style.top = `${r.bottom + 6}px`;
}

function hideActionMenu() {
    if (_actionMenuEl) _actionMenuEl.classList.add('hidden');
    _actionMenuPaper = null;
}

document.addEventListener('click', (e) => {
    if (_actionMenuEl && !_actionMenuEl.classList.contains('hidden')) {
        if (!e.target.closest('#cardActionMenu') && !e.target.closest('.cite-btn')) {
            hideActionMenu();
        }
    }
}, true);

function exportFavoritesBibtex() {
    const papers = _favoritesPool();
    if (!papers.length) {
        showToast('收藏夾是空的');
        return;
    }
    const body = papers.map(toBibtex).join('\n');
    downloadText('favorites.bib', `% ${papers.length} papers — 論文追蹤系統匯出\n\n${body}`, 'application/x-bibtex');
    showToast(`已匯出 ${papers.length} 篇收藏為 BibTeX`);
}

function startOfTodayMs() {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
}

function rangeStartMs(range = currentTimeRange) {
    if (range === 'day') return startOfTodayMs();
    const days = getTimeRangeMeta(range).days;
    return Date.now() - days * 24 * 60 * 60 * 1000;
}

function isPaperInCurrentTimeRange(paper, range = currentTimeRange) {
    const ts = paperTimestamp(paper);
    if (!ts) return true;
    return ts >= rangeStartMs(range);
}

function applyTimeRange(pool, range = currentTimeRange) {
    return (pool || []).filter(p => isPaperInCurrentTimeRange(p, range));
}

function compareNewest(a, b) {
    return paperTimestamp(b) - paperTimestamp(a);
}

function getPopularityScore(paper) {
    const citations = Math.max(0, getCitationCount(paper.url, paper));
    const influential = Math.max(0, getInfluentialCitations(paper.url));
    const hfUpvotes = Math.max(0, paper.hf_upvotes || 0);
    const velocity = Math.max(0, getCitationSpeed(paper));
    const localViews = getPaperClicks(paper.url);
    return (
        _logScale(hfUpvotes, 200) * 36 +
        _logScale(velocity, 50) * 24 +
        _logScale(citations, 500) * 22 +
        _logScale(influential, 80) * 12 +
        _logScale(localViews, 12) * 6
    );
}

function getValueScore(paper) {
    return computeSignal(paper).score || 0;
}

// ── Hot & New：新鮮度為主、社群/速度為輔 ─────────────────────────
// 與 popularity/value 不同：那兩個都是滯後訊號(引用要時間累積),對「剛出爐」論文盲視。
// 這裡讓 recency 主導(指數衰減,~半衰期 7 天),再用 HF buzz / 引用速度 / 有無 code 當加速器。
function getHotScore(paper) {
    const days = daysSincePublication(paper) || 30;
    const recency = Math.exp(-days / 10);                          // 0..1
    const hf = _logScale(Math.max(0, paper.hf_upvotes || 0), 200); // 社群熱度
    const vel = _logScale(Math.max(0, getCitationSpeed(paper)), 50);
    const cit = _logScale(Math.max(0, getCitationCount(paper.url, paper)), 500);
    const code = paper.github_url ? 1 : 0;
    return recency * 55 + hf * 22 + vel * 13 + cit * 7 + code * 3;
}

async function prepareMetricData(papers, sortValue = currentSortValue) {
    if (!papers?.length) return;
    if (['hot', 'popularity', 'citations', 'value', 'velocity'].includes(sortValue)) {
        await fetchCitationCounts(papers);
    }
    if (sortValue === 'value') {
        await fetchPwcData(papers);
    }
}

function sortPapersByMetric(papers, sortValue = currentSortValue) {
    const sorted = [...papers];
    const tie = (a, b) => compareNewest(a, b);
    if (sortValue === 'hot') {
        sorted.sort((a, b) => (getHotScore(b) - getHotScore(a)) || tie(a, b));
    } else if (sortValue === 'popularity') {
        sorted.sort((a, b) => (getPopularityScore(b) - getPopularityScore(a)) || tie(a, b));
    } else if (sortValue === 'citations' || sortValue === 'hot3m') {
        // hot3m = 90 天 pool 已在 papersForCurrentTimeRange 限縮,這裡只負責按引用排序
        sorted.sort((a, b) => (Math.max(0, getCitationCount(b.url, b)) - Math.max(0, getCitationCount(a.url, a))) || tie(a, b));
    } else if (sortValue === 'value') {
        sorted.sort((a, b) => (getValueScore(b) - getValueScore(a)) || tie(a, b));
    } else if (sortValue === 'velocity') {
        sorted.sort((a, b) => (getCitationSpeed(b) - getCitationSpeed(a)) || tie(a, b));
    } else if (sortValue === 'hf') {
        sorted.sort((a, b) => ((b.hf_upvotes || 0) - (a.hf_upvotes || 0)) || tie(a, b));
    } else {
        sorted.sort(tie);
    }
    return sorted;
}

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
    DELETED_BUILTIN_KEY  = _scopedKey('visionary_deleted_builtins', d.id);
    RENAMED_BUILTIN_KEY  = _scopedKey('visionary_renamed_builtins', d.id);
    LAST_CATEGORY_KEY    = _scopedKey('visionary_last_category', d.id);

    // 建構 CONF_FILTERS：data-filter="conf_<key>"
    CONF_FILTERS = new Map(d.confs.map(c => [`conf_${c.key.replace(/\s+/g, '_')}`, c.key.toLowerCase()]));
    SPECIAL_FILTERS = new Set(['all', 'favorites', 'top_conf', 'hf_daily', 'emerging', 'popular', 'reviews', 'my_fields', ...CONF_FILTERS.keys()]);

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

// 在 DOM 裡動態產生 conf-submenu 與兩層折疊式主題群組
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
    if (!filtersDiv) return;

    filtersDiv.querySelectorAll('.topic-group-wrapper, .category-btn[data-discipline-topic="true"]').forEach(el => el.remove());

    const groups = (typeof window.getTopicGroups === 'function') ? window.getTopicGroups(d) : [];
    if (groups.length === 0) return;

    const expandedKey = _scopedKey('visionary_topic_groups_open', d.id);
    let openSet;
    try {
        openSet = new Set(JSON.parse(localStorage.getItem(expandedKey) || '[]'));
    } catch (e) { openSet = new Set(); }
    if (openSet.size === 0 && groups.length > 0) {
        openSet.add(groups[0].name);
    }

    const persistOpen = () => {
        try { localStorage.setItem(expandedKey, JSON.stringify([...openSet])); } catch (e) {}
    };

    for (const g of groups) {
        const wrapper = document.createElement('div');
        wrapper.className = 'topic-group-wrapper';

        const header = document.createElement('button');
        header.type = 'button';
        header.className = 'category-btn topic-group-btn';
        header.dataset.groupName = g.name;
        const headLabel = document.createElement('span');
        headLabel.className = 'label-span topic-group-label';
        headLabel.innerHTML = `${g.icon ? `<span class="topic-group-icon">${g.icon}</span>` : ''}${escapeHtml(g.name)}${g.nameEn ? ` <em class="topic-group-en">${escapeHtml(g.nameEn)}</em>` : ''}`;
        header.appendChild(headLabel);
        const chevron = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        chevron.setAttribute('class', 'chevron-icon');
        chevron.setAttribute('width', '12');
        chevron.setAttribute('height', '12');
        chevron.setAttribute('viewBox', '0 0 24 24');
        chevron.setAttribute('fill', 'none');
        chevron.setAttribute('stroke', 'currentColor');
        chevron.setAttribute('stroke-width', '2.5');
        chevron.innerHTML = '<polyline points="6 9 12 15 18 9"/>';
        header.appendChild(chevron);

        const submenu = document.createElement('div');
        submenu.className = 'topic-submenu';
        for (const topic of g.topics) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'topic-item';
            btn.dataset.filter = topic.toLowerCase();
            btn.dataset.disciplineTopic = 'true';
            btn.title = topic;
            btn.textContent = topic;
            submenu.appendChild(btn);
        }

        if (openSet.has(g.name)) wrapper.classList.add('open');

        header.addEventListener('click', (e) => {
            e.stopPropagation();
            const isOpen = wrapper.classList.toggle('open');
            if (isOpen) openSet.add(g.name); else openSet.delete(g.name);
            persistOpen();
        });

        wrapper.appendChild(header);
        wrapper.appendChild(submenu);
        filtersDiv.appendChild(wrapper);
    }

    // 第 5 群:動態子題(fire-and-forget,不阻塞首屏)
    loadDynamicSubtopics(d.id, filtersDiv, openSet, persistOpen).catch(() => {});
}

// 動態子題:從 /api/subtopics 拉聚類結果並渲染為第 5 個 group
const _SUBTOPIC_INFLIGHT = new Map(); // discipline -> Promise
async function loadDynamicSubtopics(disciplineId, filtersDiv, openSet, persistOpen) {
    if (!disciplineId || !filtersDiv) return;
    // 避免短時間重複 fetch(切回同 discipline 時)
    if (_SUBTOPIC_INFLIGHT.has(disciplineId)) {
        try { await _SUBTOPIC_INFLIGHT.get(disciplineId); } catch (e) {}
        return;
    }
    const p = (async () => {
        const resp = await fetch(`/api/subtopics?discipline=${encodeURIComponent(disciplineId)}&k=6`);
        if (!resp.ok) return null;
        return resp.json();
    })();
    _SUBTOPIC_INFLIGHT.set(disciplineId, p);
    let data;
    try {
        data = await p;
    } finally {
        _SUBTOPIC_INFLIGHT.delete(disciplineId);
    }
    // 中途切過 discipline 就放棄
    if (!ACTIVE_DISCIPLINE || ACTIVE_DISCIPLINE.id !== disciplineId) return;
    if (!data || !Array.isArray(data.clusters) || data.clusters.length === 0) return;

    // 避免重複插入(快取命中時 renderDisciplineFilters 重跑會先 remove)
    const existing = filtersDiv.querySelector('.topic-group-wrapper[data-dynamic="true"]');
    if (existing) existing.remove();

    const groupName = '動態子題';
    const groupNameEn = 'Trending';
    const wrapper = document.createElement('div');
    wrapper.className = 'topic-group-wrapper';
    wrapper.dataset.dynamic = 'true';

    const header = document.createElement('button');
    header.type = 'button';
    header.className = 'category-btn topic-group-btn';
    header.dataset.groupName = groupName;
    const headLabel = document.createElement('span');
    headLabel.className = 'label-span topic-group-label';
    headLabel.innerHTML = `<span class="topic-group-icon">🔥</span>${escapeHtml(groupName)} <em class="topic-group-en">${escapeHtml(groupNameEn)}</em>`;
    header.appendChild(headLabel);
    const chevron = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    chevron.setAttribute('class', 'chevron-icon');
    chevron.setAttribute('width', '12');
    chevron.setAttribute('height', '12');
    chevron.setAttribute('viewBox', '0 0 24 24');
    chevron.setAttribute('fill', 'none');
    chevron.setAttribute('stroke', 'currentColor');
    chevron.setAttribute('stroke-width', '2.5');
    chevron.innerHTML = '<polyline points="6 9 12 15 18 9"/>';
    header.appendChild(chevron);

    const submenu = document.createElement('div');
    submenu.className = 'topic-submenu';
    for (const c of data.clusters) {
        const label = (c.label || '').trim();
        if (!label) continue;
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'topic-item';
        btn.dataset.filter = label.toLowerCase();
        btn.dataset.disciplineTopic = 'true';
        btn.dataset.dynamic = 'true';
        // momentum = 該子題近 3 天論文佔比;≥0.4 視為上升中,標 ▲
        const mom = Number(c.momentum) || 0;
        const rising = mom >= 0.4;
        btn.title = `${label}（${c.count} 篇 · 近 3 天佔 ${Math.round(mom * 100)}%）`;
        btn.textContent = `${label} · ${c.count}${rising ? ' ▲' : ''}`;
        if (rising) btn.classList.add('topic-rising');
        submenu.appendChild(btn);
    }
    if (!submenu.children.length) return;

    if (openSet && openSet.has(groupName)) wrapper.classList.add('open');

    header.addEventListener('click', (e) => {
        e.stopPropagation();
        const isOpen = wrapper.classList.toggle('open');
        if (openSet) {
            if (isOpen) openSet.add(groupName); else openSet.delete(groupName);
        }
        if (persistOpen) persistOpen();
    });

    wrapper.appendChild(header);
    wrapper.appendChild(submenu);
    filtersDiv.appendChild(wrapper);
}

// ── 研究領域選擇器 UI ──────────────────────────────────────────
let _dpState = { filterCat: 'all', query: '' };

function _dpCardHTML(d, activeId, tracked) {
    const confsPreview = (d.confs || []).slice(0, 4).map(c => c.label).join(' · ');
    const topicsPreview = (d.topics || []).slice(0, 3).join(' · ');
    return `
        <button type="button" class="dp-track-star" data-track-id="${d.id}" title="加入追蹤清單（跨領域 Bridge 權重）" aria-label="追蹤 ${d.name}">${tracked ? '★' : '☆'}</button>
        <div class="dp-card-head">
            <div class="dp-card-icon">${d.icon || '📘'}</div>
            <div class="dp-card-titles">
                <div class="dp-card-name">${d.name}</div>
                <div class="dp-card-name-en">${d.nameEn || ''}</div>
            </div>
        </div>
        <div class="dp-card-arxiv">arXiv · ${d.arxivCat || '—'}</div>
        ${confsPreview ? `<div class="dp-card-confs">🏆 ${confsPreview}</div>` : ''}
        ${topicsPreview ? `<div class="dp-card-topics">🏷️ ${topicsPreview}</div>` : ''}
    `;
}

function _dpMatches(d, query) {
    if (!query) return true;
    const q = query.toLowerCase().trim();
    if (!q) return true;
    const hay = [
        d.name, d.nameEn, d.brand, d.arxivCat, d.id,
        ...(d.topics || []),
        ...(d.confs || []).map(c => c.label || ''),
    ].join(' ').toLowerCase();
    return hay.includes(q);
}

function _dpBindCardEvents(card, id) {
    card.addEventListener('click', (e) => {
        const starBtn = e.target.closest('.dp-track-star');
        if (starBtn) {
            e.stopPropagation();
            const tid = starBtn.dataset.trackId;
            const next = new Set((window.getTracks && window.getTracks()) || []);
            if (next.has(tid)) next.delete(tid); else next.add(tid);
            window.setTracks && window.setTracks([...next]);
            starBtn.textContent = next.has(tid) ? '★' : '☆';
            card.classList.toggle('tracked', next.has(tid));
            return;
        }
        selectDiscipline(id);
    });
}

function renderDisciplineGrid() {
    const grid = document.getElementById('disciplineGrid');
    const emptyEl = document.getElementById('dpEmpty');
    if (!grid) return;
    grid.innerHTML = '';

    const activeId = ACTIVE_DISCIPLINE?.id;
    const tracks = new Set((window.getTracks && window.getTracks()) || []);
    const cats = window.DISCIPLINE_CATEGORIES || [];
    const { filterCat, query } = _dpState;
    let totalShown = 0;

    for (const cat of cats) {
        if (filterCat !== 'all' && filterCat !== cat.id) continue;
        const members = (cat.ids || [])
            .map(id => window.DISCIPLINES[id])
            .filter(d => d && _dpMatches(d, query));
        if (members.length === 0) continue;

        const section = document.createElement('section');
        section.className = 'dp-section';
        section.dataset.catId = cat.id;

        const header = document.createElement('div');
        header.className = 'dp-section-head';
        header.innerHTML = `
            <span class="dp-section-icon" aria-hidden="true">${cat.icon}</span>
            <span class="dp-section-title">${cat.name}</span>
            <span class="dp-section-en">${cat.nameEn}</span>
            <span class="dp-section-count">${members.length}</span>
        `;
        section.appendChild(header);

        const grid2 = document.createElement('div');
        grid2.className = 'dp-grid';
        for (const d of members) {
            const card = document.createElement('button');
            card.type = 'button';
            card.className = 'dp-card' + (d.id === activeId ? ' active' : '') + (tracks.has(d.id) ? ' tracked' : '');
            card.dataset.disciplineId = d.id;
            card.innerHTML = _dpCardHTML(d, activeId, tracks.has(d.id));
            _dpBindCardEvents(card, d.id);
            grid2.appendChild(card);
            totalShown += 1;
        }
        section.appendChild(grid2);
        grid.appendChild(section);
    }

    if (emptyEl) emptyEl.classList.toggle('hidden', totalShown > 0);
}

function renderDpCategoryChips() {
    const bar = document.getElementById('dpCategoryChips');
    if (!bar) return;
    bar.innerHTML = '';
    const cats = window.DISCIPLINE_CATEGORIES || [];
    const total = cats.reduce((n, c) => n + (c.ids?.length || 0), 0);

    const mk = (id, label, count) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'dp-chip' + (_dpState.filterCat === id ? ' active' : '');
        btn.dataset.catId = id;
        btn.innerHTML = `<span>${label}</span><span class="dp-chip-count">${count}</span>`;
        btn.addEventListener('click', () => {
            _dpState.filterCat = id;
            renderDpCategoryChips();
            renderDisciplineGrid();
        });
        bar.appendChild(btn);
    };

    mk('all', '全部', total);
    for (const c of cats) mk(c.id, `${c.icon} ${c.name}`, c.ids.length);
}

function openDisciplinePicker({ closable = true } = {}) {
    const picker = document.getElementById('disciplinePicker');
    const closeBtn = document.getElementById('disciplinePickerClose');
    if (!picker) return;

    _dpState.filterCat = 'all';
    _dpState.query = '';
    const searchInput = document.getElementById('dpSearchInput');
    if (searchInput) searchInput.value = '';

    renderDpCategoryChips();
    renderDisciplineGrid();

    if (!picker.dataset.bound) {
        searchInput?.addEventListener('input', () => {
            _dpState.query = searchInput.value;
            renderDisciplineGrid();
        });
        picker.dataset.bound = '1';
    }

    if (closeBtn) closeBtn.hidden = !closable;
    picker.classList.remove('hidden');
    setTimeout(() => searchInput?.focus(), 60);
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
    // #11 切換領域時同步 URL 的 d,並清掉與舊領域綁定的 cat(主題/會議換領域即失效),避免 reload 後被舊參數覆蓋
    try {
        const p = new URLSearchParams(window.location.search);
        p.set('d', id);
        p.delete('cat');
        const qs = p.toString();
        window.history.replaceState(null, '', window.location.pathname + (qs ? '?' + qs : '') + window.location.hash);
    } catch (e) {}
    // 切換領域 → reload 使整個 UI／localStorage 狀態重新初始化
    location.reload();
}

// ── 相似論文 modal ─────────────────────────────────────────────
function _extractArxivId(paper) {
    const ext = paper.external_ids || {};
    if (ext.arxiv) {
        const m = String(ext.arxiv).match(/(\d{4}\.\d{4,6})/);
        if (m) return m[1];
    }
    const url = paper.url || '';
    const m2 = url.match(/arxiv\.org\/(?:abs|pdf)\/(\d{4}\.\d{4,6})/i);
    return m2 ? m2[1] : null;
}

async function openSimilarModal(paper) {
    const modal = document.getElementById('similarModal');
    if (!modal) return;
    const seedEl = document.getElementById('similarSeed');
    const bodyEl = document.getElementById('similarBody');
    if (seedEl) seedEl.innerHTML = `<div class="similar-seed-title">${escapeHtml(paper.title)}</div>`;
    if (bodyEl) bodyEl.innerHTML = '<div class="similar-loading">載入中…</div>';
    modal.classList.remove('hidden');

    const arxivId = _extractArxivId(paper);
    if (!arxivId) {
        if (bodyEl) bodyEl.innerHTML = '<div class="similar-empty">此論文無 arXiv ID，無法推薦相似論文。</div>';
        return;
    }
    try {
        const r = await fetch(`/api/recommendations?arxiv_id=${encodeURIComponent(arxivId)}&limit=10`);
        if (!r.ok) throw new Error('rec failed');
        const data = await r.json();
        const papers = data.papers || [];
        if (!papers.length) {
            if (bodyEl) bodyEl.innerHTML = '<div class="similar-empty">尚無相似論文資料（Semantic Scholar 可能還沒索引這篇）。</div>';
            return;
        }
        if (bodyEl) {
            bodyEl.innerHTML = papers.map(p => {
                const title = escapeHtml(p.title || '');
                const url = escapeHtml(p.url || '#');
                const authors = (p.authors || []).slice(0, 4).join(', ');
                const venue = p.venue ? `<span class="sim-venue">${escapeHtml(p.venue)}</span>` : '';
                const yr = p.year ? `<span class="sim-year">${escapeHtml(String(p.year))}</span>` : '';
                const cit = p.citation_count ? `<span class="sim-cit">📊 ${escapeHtml(String(p.citation_count))}</span>` : '';
                return `<a class="sim-item" href="${url}" target="_blank" rel="noopener noreferrer">
                    <div class="sim-title">${title}</div>
                    <div class="sim-meta">${escapeHtml(authors)} ${venue} ${yr} ${cit}</div>
                </a>`;
            }).join('');
        }
    } catch (e) {
        if (bodyEl) bodyEl.innerHTML = `<div class="similar-empty">載入失敗：${escapeHtml(e.message || 'unknown')}</div>`;
    }
}

function closeSimilarModal() {
    document.getElementById('similarModal')?.classList.add('hidden');
}

// ── 最近搜尋（每個 discipline 各自 5 筆） ───────────────────────
const _RECENT_SEARCHES_MAX = 5;
function _recentSearchesKey() {
    return _scopedKey('visionary_recent_searches', ACTIVE_DISCIPLINE?.id || '');
}
function loadRecentSearches() {
    try { return JSON.parse(localStorage.getItem(_recentSearchesKey()) || '[]'); }
    catch (e) { return []; }
}
function saveRecentSearches(arr) {
    try { localStorage.setItem(_recentSearchesKey(), JSON.stringify(arr.slice(0, _RECENT_SEARCHES_MAX))); }
    catch (e) {}
}
function pushRecentSearch(q) {
    q = (q || '').trim();
    if (!q || q.length > 80) return;
    const cur = loadRecentSearches().filter(x => x !== q);
    cur.unshift(q);
    saveRecentSearches(cur);
    renderRecentSearches();
}
function clearRecentSearches() {
    saveRecentSearches([]);
    renderRecentSearches();
}
function renderRecentSearches() {
    const bar = document.getElementById('recentSearchesBar');
    if (!bar) return;
    const items = loadRecentSearches();
    if (!items.length) { bar.classList.add('hidden'); bar.innerHTML = ''; return; }
    bar.classList.remove('hidden');
    bar.innerHTML = `<span class="rs-label">最近：</span>` + items.map(q =>
        `<button class="rs-chip" data-q="${escapeHtml(q)}">${escapeHtml(q)}</button>`
    ).join('') + `<button class="rs-clear" title="清除最近搜尋">×</button>`;
}

// ── 統一熱度指數（Heat Index） ──────────────────────────────────
// 結合 value score / velocity / hf_upvotes / citation_count,輸出 0-100。
function computeHeatIndex(paper) {
    const v = Number(paper.signal_score || paper.value_score || 0); // 0-100
    const vel = Number(paper.citation_velocity || 0);                // 引用/月,小數
    const hf = Number(paper.hf_upvotes || 0);                        // 0+
    const cit = Number(paper.citation_count || 0);
    // 各維度先壓到 0-1
    const vN = Math.max(0, Math.min(1, v / 100));
    const velN = Math.max(0, Math.min(1, Math.log1p(vel * 12) / Math.log(50)));
    const hfN = Math.max(0, Math.min(1, Math.log1p(hf) / Math.log(200)));
    const citN = Math.max(0, Math.min(1, Math.log1p(cit) / Math.log(500)));
    // 加權
    const score = 0.45 * vN + 0.25 * velN + 0.18 * hfN + 0.12 * citN;
    return Math.round(score * 100);
}
function heatIndexTier(h) {
    if (h >= 70) return { cls: 'heat-hot', label: '🔥 高熱', tier: 'hot' };
    if (h >= 45) return { cls: 'heat-warm', label: '☀️ 中熱', tier: 'warm' };
    if (h >= 20) return { cls: 'heat-cool', label: '🌤 低熱', tier: 'cool' };
    return { cls: 'heat-cold', label: '🌙 冷', tier: 'cold' };
}

// ── OpenReview 評審分數色階 ────────────────────────────────────
function orRatingTier(rating) {
    const r = Number(rating);
    if (!isFinite(r) || r <= 0) return null;
    if (r >= 6) return { cls: 'or-green', label: `OR ${r.toFixed(1)}` };
    if (r >= 5) return { cls: 'or-yellow', label: `OR ${r.toFixed(1)}` };
    return { cls: 'or-red', label: `OR ${r.toFixed(1)}` };
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

    const btn = document.createElement('button');
    btn.className = 'category-btn pinned-topic-btn';
    btn.dataset.filter = label;
    btn.dataset.pinned = 'true';
    btn.title = label;

    const pin = document.createElement('span');
    pin.className = 'pin-icon';
    pin.textContent = '📌';

    const labelSpan = document.createElement('span');
    labelSpan.className = 'label-span';
    labelSpan.textContent = label;

    btn.appendChild(pin);
    btn.appendChild(labelSpan);
    filtersDiv.appendChild(btn);

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

// ── 自訂訂閱系統(#17) ───────────────────────────────────────────
// 直接組合 arXiv 查詢(cat/keyword/author/id),跨領域共用,單一 localStorage key。
const CUSTOM_FEEDS_KEY = 'visionary_custom_feeds_v1';

function loadCustomFeeds() {
    try {
        const arr = JSON.parse(localStorage.getItem(CUSTOM_FEEDS_KEY) || '[]');
        return Array.isArray(arr) ? arr : [];
    } catch (e) { return []; }
}
function saveCustomFeeds(feeds) {
    localStorage.setItem(CUSTOM_FEEDS_KEY, JSON.stringify(feeds));
}
function getCustomFeed(id) {
    return loadCustomFeeds().find(f => f.id === id) || null;
}
function _csvToList(raw) {
    return (raw || '').split(',').map(s => s.trim()).filter(Boolean).slice(0, 12);
}
function _customFeedQuery(feed, extra) {
    const p = new URLSearchParams();
    if (feed.cats?.length)     p.set('cats', feed.cats.join(','));
    if (feed.keywords?.length) p.set('keywords', feed.keywords.join(','));
    if (feed.authors?.length)  p.set('authors', feed.authors.join(','));
    if (feed.ids?.length)      p.set('ids', feed.ids.join(','));
    Object.entries(extra || {}).forEach(([k, v]) => p.set(k, String(v)));
    return p.toString();
}
function _customFeedSummary(feed) {
    const parts = [];
    if (feed.cats?.length)     parts.push(`分類 ${feed.cats.join('/')}`);
    if (feed.keywords?.length) parts.push(`「${feed.keywords.join('／')}」`);
    if (feed.authors?.length)  parts.push(`作者 ${feed.authors.join('、')}`);
    if (feed.ids?.length)      parts.push(`${feed.ids.length} 篇指定 ID`);
    return parts.join(' · ');
}

function renderCustomFeedBtns() {
    const filtersDiv = document.querySelector('.category-filters');
    if (!filtersDiv) return;
    filtersDiv.querySelectorAll('.custom-feed-btn').forEach(el => el.remove());
    const addBtn = document.getElementById('addCustomFeedBtn');
    for (const feed of loadCustomFeeds()) {
        const btn = document.createElement('button');
        btn.className = 'category-btn custom-feed-btn';
        btn.dataset.filter = feed.id;
        btn.dataset.customFeed = 'true';
        btn.title = _customFeedSummary(feed) || feed.name;

        const icon = document.createElement('span');
        icon.className = 'pin-icon';
        icon.textContent = '🛰️';
        const label = document.createElement('span');
        label.className = 'label-span';
        label.textContent = feed.name;
        btn.appendChild(icon);
        btn.appendChild(label);

        if (addBtn) filtersDiv.insertBefore(btn, addBtn);
        else filtersDiv.appendChild(btn);
    }
}

function deleteCustomFeed(id) {
    saveCustomFeeds(loadCustomFeeds().filter(f => f.id !== id));
    if (currentCategory === id) {
        currentCategory = 'all';
        const allBtn = document.querySelector('.category-btn[data-filter="all"]');
        if (allBtn) {
            document.querySelectorAll('.category-btn').forEach(b => b.classList.remove('active'));
            allBtn.classList.add('active');
        }
        filterPapers();
    }
    renderCustomFeedBtns();
}

let _cfEditId = null;
function openCustomFeedModal(editId) {
    const modal = document.getElementById('customFeedModal');
    if (!modal) return;
    _cfEditId = editId || null;
    const feed = editId ? getCustomFeed(editId) : null;
    document.getElementById('cfTitle').textContent = feed ? '編輯自訂訂閱' : '建立自訂訂閱';
    document.getElementById('cfName').value     = feed?.name || '';
    document.getElementById('cfCats').value     = (feed?.cats || []).join(', ');
    document.getElementById('cfKeywords').value = (feed?.keywords || []).join(', ');
    document.getElementById('cfAuthors').value  = (feed?.authors || []).join(', ');
    document.getElementById('cfIds').value      = (feed?.ids || []).join(', ');
    document.getElementById('cfDelete').hidden  = !feed;
    modal.classList.remove('hidden');
    setTimeout(() => document.getElementById('cfName').focus(), 30);
}
function closeCustomFeedModal() {
    document.getElementById('customFeedModal')?.classList.add('hidden');
    _cfEditId = null;
}
function _submitCustomFeed(e) {
    if (e) e.preventDefault();
    const name = document.getElementById('cfName').value.trim();
    const cats = _csvToList(document.getElementById('cfCats').value);
    const keywords = _csvToList(document.getElementById('cfKeywords').value);
    const authors = _csvToList(document.getElementById('cfAuthors').value);
    const ids = _csvToList(document.getElementById('cfIds').value)
        .map(s => (s.match(/\d{4}\.\d{4,6}/) || [s])[0]);
    if (!name) { showToast('請輸入訂閱名稱'); return; }
    if (!(cats.length || keywords.length || authors.length || ids.length)) {
        showToast('至少填一個條件:分類 / 關鍵字 / 作者 / ID');
        return;
    }
    const feeds = loadCustomFeeds();
    if (_cfEditId) {
        const f = feeds.find(x => x.id === _cfEditId);
        if (f) Object.assign(f, { name, cats, keywords, authors, ids });
    } else {
        _cfEditId = `custom_${Date.now().toString(36)}`;
        feeds.push({ id: _cfEditId, name, cats, keywords, authors, ids });
    }
    saveCustomFeeds(feeds);
    renderCustomFeedBtns();
    const targetId = _cfEditId;
    closeCustomFeedModal();
    const btn = document.querySelector(`.custom-feed-btn[data-filter="${CSS.escape(targetId)}"]`);
    if (btn) _selectCategory(targetId, btn);
}

// ── 已讀系統 ───────────────────────────────────────────────────
const READ_KEY = 'visionary_read_v1';
let readSet = new Set(JSON.parse(localStorage.getItem(READ_KEY) || '[]'));

// #6 上次造訪時間：先讀舊值（本次 session 比對基準），再寫入「現在」供下次比對
const LAST_VISIT_KEY = 'visionary_last_visit_v1';
const PREV_VISIT_MS = Number(localStorage.getItem(LAST_VISIT_KEY) || 0);
try { localStorage.setItem(LAST_VISIT_KEY, String(Date.now())); } catch (_) {}

function newSinceVisitCount() {
    if (!PREV_VISIT_MS || !Array.isArray(allPapers)) return 0;
    return allPapers.reduce((n, p) => n + (paperTimestamp(p) > PREV_VISIT_MS ? 1 : 0), 0);
}

async function showNewSinceVisit() {
    if (!PREV_VISIT_MS) { showToast('這是你的第一次造訪，下次回來就能看到新增論文'); return; }
    const pool = Array.isArray(allPapers) ? allPapers : [];
    let fresh = pool.filter(p => paperTimestamp(p) > PREV_VISIT_MS);
    if (!fresh.length) { showToast('自上次造訪後沒有新論文'); return; }
    fresh = indexPapers(fresh);
    await prepareMetricData(fresh, 'latest');
    fresh = sortPapersByMetric(fresh, 'latest');
    currentPage = 1;
    renderPapers(fresh, `🆕 自上次造訪新增（${fresh.length} 篇）`);
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

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

const PAPER_CLICKS_KEY = 'visionary_paper_clicks_v1';
let paperClicks = {};
try { paperClicks = JSON.parse(localStorage.getItem(PAPER_CLICKS_KEY) || '{}'); } catch (e) { paperClicks = {}; }

function getPaperClicks(url) {
    return Math.max(0, Number(paperClicks[url] || 0));
}

function savePaperClicks() {
    localStorage.setItem(PAPER_CLICKS_KEY, JSON.stringify(paperClicks));
}

function recordPaperClick(url) {
    if (!url) return;
    paperClicks[url] = getPaperClicks(url) + 1;
    savePaperClicks();
}

// 匿名開啟遙測:每篇每個 session 只送一次,累計到 /api/popular 全站熱門排行。
const _viewedThisSession = new Set();
function sendViewBeacon(url, paper) {
    if (!url || _viewedThisSession.has(url)) return;
    _viewedThisSession.add(url);
    const payload = {
        url,
        arxiv_id: getArxivId(url) || '',
        title: (paper && paper.title) || '',
    };
    try {
        const blob = new Blob([JSON.stringify(payload)], { type: 'application/json' });
        if (navigator.sendBeacon && navigator.sendBeacon('/api/view', blob)) return;
    } catch (e) { /* fall through to fetch */ }
    fetch('/api/view', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        keepalive: true,
    }).catch(() => {});
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
    _favAuthorSet = null;  // invalidate similar-fav cache
    // 若目前在收藏夾視圖，移除後立即重新渲染
    if (currentCategory === 'favorites') filterPapers();
}

// ── 摘要：原文直接呈現，不再透過 AI 翻譯 ────────────────────
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

const PAPERS_SWR_MAX_AGE = 24 * 60 * 60 * 1000; // 24h：本機只做秒開，新鮮度由後端 SWR 保證

// ── IndexedDB papers cache（取代 localStorage：容量大、async、跨 tab）─────
const _IDB_DB = 'visionary';
const _IDB_STORE = 'papers';
let _idbPromise = null;
function _openIDB() {
    if (_idbPromise) return _idbPromise;
    _idbPromise = new Promise((resolve) => {
        if (!('indexedDB' in self)) { resolve(null); return; }
        const req = indexedDB.open(_IDB_DB, 1);
        req.onupgradeneeded = () => {
            const db = req.result;
            if (!db.objectStoreNames.contains(_IDB_STORE)) {
                db.createObjectStore(_IDB_STORE);
            }
        };
        req.onsuccess = () => resolve(req.result);
        req.onerror   = () => resolve(null);
    });
    return _idbPromise;
}
async function idbGet(key) {
    const db = await _openIDB();
    if (!db) return null;
    return new Promise((resolve) => {
        try {
            const tx = db.transaction(_IDB_STORE, 'readonly');
            const r = tx.objectStore(_IDB_STORE).get(key);
            r.onsuccess = () => resolve(r.result || null);
            r.onerror   = () => resolve(null);
        } catch (_) { resolve(null); }
    });
}
async function idbSet(key, value) {
    const db = await _openIDB();
    if (!db) return;
    return new Promise((resolve) => {
        try {
            const tx = db.transaction(_IDB_STORE, 'readwrite');
            tx.objectStore(_IDB_STORE).put(value, key);
            tx.oncomplete = () => resolve();
            tx.onerror    = () => resolve();
        } catch (_) { resolve(); }
    });
}
async function _readPapersIDB(disc) {
    try {
        const v = await idbGet(`papers:${disc}`);
        if (!v?.papers) return null;
        if (Date.now() - (v.t || 0) > PAPERS_SWR_MAX_AGE) return null;
        return v.papers;
    } catch (_) { return null; }
}
async function _writePapersIDB(disc, papers) {
    try { await idbSet(`papers:${disc}`, { t: Date.now(), papers }); } catch (_) {}
}

// SW 背景刷新完成後通知前端 → 本函式重抓並渲染（同 disc 去重）
let _papersInflight = null;

async function _fetchAndApply(disc) {
    const url = `/api/papers?max_results=50&discipline=${encodeURIComponent(disc)}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error('Failed to fetch data');
    const data = await res.json();
    if ((ACTIVE_DISCIPLINE?.id || 'cv') !== disc) return; // 切過 disc 後丟掉舊回應
    lastDataAsOf = Number.isFinite(data.as_of) ? data.as_of * 1000 : Date.now();
    allPapers = indexPapers(data.papers);
    await filterPapers();
    scheduleBadgeUpdate();
    _writePapersIDB(disc, data.papers);
    hideLiveRefreshPill();  // 已套用最新資料 → 收起提示
}

// ── #15 即時推播：SSE 連線，伺服器收割到新論文時提示更新 ──────────
let _sse = null;
let _liveRefreshDisc = null;
function initLiveStream() {
    if (_sse || typeof EventSource === 'undefined') return;
    try {
        _sse = new EventSource('/api/stream');
        _sse.onmessage = (e) => {
            try { handleLiveEvent(JSON.parse(e.data)); } catch (_) { /* 非 JSON 心跳忽略 */ }
        };
        // 連線中斷時 EventSource 內建自動重連，不需手動處理
        _sse.onerror = () => {};
    } catch (_) { _sse = null; }
}

function handleLiveEvent(ev) {
    if (!ev || ev.type !== 'papers') return;
    const disc = ACTIVE_DISCIPLINE?.id || 'cv';
    if (Array.isArray(ev.disciplines) && !ev.disciplines.includes(disc)) return;
    const atMs = Number.isFinite(ev.at) ? ev.at * 1000 : Date.now();
    if (atMs <= lastDataAsOf + 2000) return;  // 自己剛抓的資料，不重複提示
    showLiveRefreshPill(disc);
}

function showLiveRefreshPill(disc) {
    let pill = document.getElementById('liveRefreshPill');
    if (!pill) {
        pill = document.createElement('button');
        pill.id = 'liveRefreshPill';
        pill.className = 'live-refresh-pill';
        pill.type = 'button';
        pill.setAttribute('aria-live', 'polite');
        pill.addEventListener('click', async () => {
            const target = _liveRefreshDisc || (ACTIVE_DISCIPLINE?.id || 'cv');
            hideLiveRefreshPill();
            try { await _fetchAndApply(target); } catch (_) {}
        });
        document.body.appendChild(pill);
    }
    _liveRefreshDisc = disc;
    pill.innerHTML = '<span class="live-dot"></span>有新論文，點擊更新';
    pill.classList.add('show');
}

function hideLiveRefreshPill() {
    document.getElementById('liveRefreshPill')?.classList.remove('show');
}

function _readSSRPapers(disc) {
    try {
        const el = document.getElementById('ssr-papers');
        if (!el || el.dataset.disc !== disc) return null;
        const raw = el.dataset.json;
        if (!raw) return null;
        const arr = JSON.parse(raw);
        // 用完就移除節點,避免後續切 discipline 時誤用
        el.remove();
        return Array.isArray(arr) && arr.length ? arr : null;
    } catch (_) { return null; }
}

async function fetchPapers() {
    papersGrid.classList.add('hidden');
    noResults.classList.add('hidden');
    loader.classList.remove('hidden');
    hideLiveRefreshPill();  // 換領域/重載時收起舊的新論文提示
    startLoaderMessages();

    const disc = ACTIVE_DISCIPLINE?.id || 'cv';

    // L0:SSR(server 注入首 12 篇)— 第一次造訪、無 IDB cache 時瞬間有畫面
    let usedCache = false;
    const ssrPapers = _readSSRPapers(disc);
    if (ssrPapers) {
        allPapers = indexPapers(ssrPapers);
        usedCache = true;
        await filterPapers();
        scheduleBadgeUpdate();
    }

    // L1:IndexedDB(本機 24h)— 若 SSR 命中已渲染,IDB 結果只在更新時覆蓋
    try {
        const cachedPapers = await _readPapersIDB(disc);
        if (cachedPapers?.length && cachedPapers.length > (ssrPapers?.length || 0)) {
            allPapers = indexPapers(cachedPapers);
            usedCache = true;
            await filterPapers();
            scheduleBadgeUpdate();
        }
    } catch (e) { /* IDB 壞了沒關係 */ }

    // L2：fetch（SW 對 /api/papers 走 SWR，會立刻回 cache + 背景刷新後 postMessage）
    try {
        await _fetchAndApply(disc);
    } catch (e) {
        if (!usedCache) {
            console.error(e);
            alert('獲取論文失敗，請稍後再試。 Error: ' + e.message);
            loader.classList.add('hidden');
        }
    } finally {
        stopLoaderMessages();
    }
}

function _onSWApiUpdated(payload) {
    if (payload?.path !== '/api/papers') return;
    const disc = ACTIVE_DISCIPLINE?.id || 'cv';
    if (_papersInflight) return;
    _papersInflight = (async () => {
        try { await _fetchAndApply(disc); }
        catch (_) {}
        finally { _papersInflight = null; }
    })();
}
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.addEventListener('message', (e) => {
        if (e.data?.type === 'api-updated') _onSWApiUpdated(e.data);
    });
}

// 首屏渲染後在 idle 階段補引用數 + 在原地更新 badge（避免重 render 整個網格）
function scheduleBadgeUpdate() {
    const work = async () => {
        if (!currentFilteredPapers?.length) return;
        // 只抓當前已渲染卡片對應的 paper（最多 currentFilteredPapers.length，但只更新可見卡片）
        const visibleCards = papersGrid.querySelectorAll('.paper-card');
        const urlSet = new Set(Array.from(visibleCards, c => c.dataset.url));
        const target = currentFilteredPapers.filter(p => urlSet.has(p.url));
        if (!target.length) return;
        await fetchCitationCounts(target);
        const byUrl = new Map(currentFilteredPapers.map(p => [p.url, p]));
        for (const card of visibleCards) {
            const p = byUrl.get(card.dataset.url);
            if (p) updateCardBadgesInPlace(card, p);
        }
    };
    if ('requestIdleCallback' in window) {
        window.requestIdleCallback(() => work(), { timeout: 1500 });
    } else {
        setTimeout(work, 50);
    }
}

// 收藏夾作者 lastname 集合 (lazy + invalidate on favorite change)
let _favAuthorSet = null;
let _favAuthorSetVersion = -1;
function _lastName(name) {
    if (!name) return '';
    const parts = name.trim().split(/\s+/);
    return (parts[parts.length - 1] || '').toLowerCase();
}
function _getFavAuthorSet() {
    if (_favAuthorSetVersion === favorites.size && _favAuthorSet) return _favAuthorSet;
    const s = new Set();
    const pool = _favoritesPool();
    for (const p of pool) {
        for (const a of (p.authors || [])) {
            const ln = _lastName(a);
            if (ln && ln.length >= 3) s.add(ln);
        }
    }
    _favAuthorSet = s;
    _favAuthorSetVersion = favorites.size;
    return s;
}

// 共用 badge 渲染：buildCard 與 idle 補強都呼叫這個，避免重複規則漂移
function populateBadgeSlot(badgeSlot, paper) {
    if (!badgeSlot) return;
    badgeSlot.innerHTML = '';
    const citCount = getCitationCount(paper.url, paper);
    const inflCount = getInfluentialCitations(paper.url);
    const refCount = getRefCount(paper.url);
    const speed = getCitationSpeed(paper);
    const localViews = getPaperClicks(paper.url);
    const items = [];
    // 爆發指數:僅 /api/emerging 回傳的論文帶 emergence 物件,放最前面突顯
    const em = paper.emergence;
    if (em && typeof em === 'object') {
        const parts = [];
        if (em.cit_delta > 0) parts.push(`+${em.cit_delta} 引用`);
        if (em.hf_delta > 0)  parts.push(`+${em.hf_delta} upvote`);
        const detail = parts.length ? parts.join(' · ') : `分數 ${em.emergence}`;
        items.push(['emerge-badge', `🚀 爆發 ${detail}`, '近期引用／社群熱度爆發指數（citation + HF velocity z-score 融合）']);
    }
    if (citCount >= 0)         items.push(['citation-badge', `📈 ${citCount} 引用`, null]);
    if (inflCount > 0)         items.push(['influential-badge', `💡 ${inflCount} 高影響`, '高影響引用：被後續研究大量採用']);
    if (refCount > 100)        items.push(['survey-badge', '📚 綜述', `引用文獻數 ${refCount}，可能為綜述論文`]);
    if (speed >= 2)            items.push(['speed-badge', `🚀 ${speed >= 10 ? speed.toFixed(0) : speed.toFixed(1)}/月`, '引用速度：每月新增的引用數']);
    if (paper.hf_upvotes >= 5) items.push(['hf-badge', `🤗 ${paper.hf_upvotes}`, 'HuggingFace Daily Papers 社群 upvote 數']);
    if (localViews > 0)        items.push(['view-badge', `👁 ${localViews} 點閱`, '本機點閱次數（此瀏覽器/登入同步資料）']);
    // OpenReview 評審分數色階（綠 6+ / 黃 5 / 紅 ≤4）
    const orTier = orRatingTier(paper.or_rating || paper.review_avg);
    if (orTier) {
        const cnt = paper.review_count ? ` ·${paper.review_count}` : '';
        const tip = paper.review_count
            ? `OpenReview 評審平均分數（${paper.review_count} 篇評審）`
            : 'OpenReview 評審平均分數';
        items.push([`or-badge ${orTier.cls}`, `${orTier.label}${cnt}`, tip]);
    }
    // 熱度指數（綜合 value/velocity/hf/citations）
    const heat = computeHeatIndex({
        signal_score: getValueScore(paper),
        citation_velocity: speed,
        hf_upvotes: paper.hf_upvotes,
        citation_count: citCount >= 0 ? citCount : 0,
    });
    if (heat >= 20) {
        const t = heatIndexTier(heat);
        items.push([`heat-badge ${t.cls}`, `${t.label} ${heat}`, '統合熱度指數（價值+速度+HF+引用）']);
    }
    // similar-to-favorite: 跟已收藏論文共享至少 1 位作者 lastname,且本身未收藏
    if (favorites.size > 0 && !favorites.has(paper.url)) {
        const favSet = _getFavAuthorSet();
        if (favSet.size > 0) {
            for (const a of (paper.authors || [])) {
                if (favSet.has(_lastName(a))) {
                    items.push(['similar-fav-badge', '🔗 已收藏作者', '與你收藏的某篇論文有共同作者']);
                    break;
                }
            }
        }
    }
    for (const [cls, txt, title] of items) {
        const s = document.createElement('span');
        s.className = cls;
        s.textContent = txt;
        if (title) s.title = title;
        badgeSlot.appendChild(s);
    }
}

// 在原地更新 venue / citation badge，不重 render 整個網格
function updateCardBadgesInPlace(card, paper) {
    const existingVenue = card.querySelector('.venue-badge');
    const venue = detectVenue(paper);
    if (venue && existingVenue) {
        existingVenue.style.setProperty('--venue-color', venue.color);
        existingVenue.setAttribute('data-venue', venue.label);
        existingVenue.textContent = venue.label;
    }
    populateBadgeSlot(card.querySelector('.badge-slot'), paper);
    renderSignalBlock(card, paper);
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

        const paperNavLink = e.target.closest('.paper-title-link, .paper-link');
        if (paperNavLink && card.contains(paperNavLink)) {
            recordPaperClick(url);
            const paper = currentFilteredPapers.find(p => p.url === url);
            sendViewBeacon(url, paper);
            if (paper) updateCardBadgesInPlace(card, paper);
            return;
        }

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

        const similarBtn = e.target.closest('.similar-btn');
        if (similarBtn && card.contains(similarBtn)) {
            e.stopPropagation();
            const paper = currentFilteredPapers.find(p => p.url === url);
            if (paper) openSimilarModal(paper);
            return;
        }

        const noteBtn = e.target.closest('.note-btn');
        if (noteBtn && card.contains(noteBtn)) {
            e.stopPropagation();
            openNotePanel(url, card);
            return;
        }

        const citeBtn = e.target.closest('.cite-btn');
        if (citeBtn && card.contains(citeBtn)) {
            e.stopPropagation();
            const paper = currentFilteredPapers.find(p => p.url === url);
            if (paper) openCardActionMenu(paper, citeBtn);
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
        span.setAttribute('data-venue', venue.label);
        span.textContent = venue.label;
        venueSlot.replaceWith(span);
    } else {
        venueSlot?.remove();
    }

    // Signal 6 軸分數
    renderSignalBlock(card, paper);

    // Bridge（跨領域）標記：命中 >=2 個大學研究所主修的關鍵字集
    renderBridgeBadge(card, paper);

    // Title / link
    const titleLink = card.querySelector('.paper-title-link');
    titleLink.href = paper.url;
    titleLink.textContent = paper.title;

    // 我的領域(#14):合併 feed 標出論文來自哪個追蹤領域
    if (currentCategory === 'my_fields' && (paper.field_name || (Array.isArray(paper.fields) && paper.fields.length))) {
        const titleEl = card.querySelector('.paper-title');
        if (titleEl) {
            const ids = Array.isArray(paper.fields) && paper.fields.length ? paper.fields : null;
            const names = ids
                ? ids.map(id => window.DISCIPLINES?.[id]?.name || id)
                : [paper.field_name];
            const badge = document.createElement('span');
            badge.className = 'field-badge';
            badge.textContent = '🗂️ ' + names.join(' · ');
            titleEl.parentNode.insertBefore(badge, titleEl);
        }
    }

    // 來源 tooltip (hover 卡片時顯示來自哪些上游)
    const _srcArr = Array.isArray(paper.source) ? paper.source : (paper.source ? [paper.source] : ['arxiv']);
    const _srcLabel = {
        arxiv: 'arXiv', hf_daily: 'HuggingFace Daily', openalex: 'OpenAlex',
        crossref: 'Crossref', pubmed: 'PubMed', biorxiv: 'bioRxiv',
        medrxiv: 'medRxiv', dblp: 'DBLP', chemrxiv: 'ChemRxiv'
    };
    card.title = `來源:${_srcArr.map(s => _srcLabel[s] || s).join(' · ')}`;

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

    // Footer：相對時間 + 絕對時間 tooltip + NEW 標記（近 24h）
    const dateEl = card.querySelector('.paper-date');
    const pubMs = paperTimestamp(paper);
    if (pubMs > 0) {
        dateEl.textContent = relativeTime(pubMs) || paper.published;
        dateEl.title = absoluteDate(pubMs);
        if (Date.now() - pubMs <= NEW_PAPER_WINDOW_MS) {
            card.classList.add('is-new');
            const flag = document.createElement('span');
            flag.className = 'new-flag';
            flag.textContent = 'NEW';
            dateEl.insertAdjacentElement('beforebegin', flag);
        }
    } else {
        dateEl.textContent = paper.published;
    }

    // Badges（引用、高影響、綜述、引用速度、h5、HF）
    populateBadgeSlot(card.querySelector('.badge-slot'), paper);

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

    const countHeader = document.getElementById('countHeader');
    const themeEl = countHeader?.querySelector('.count-theme');
    const metaEl = countHeader?.querySelector('.count-meta');

    const favExportBtnTop = document.getElementById('favExportBtn');
    if (favExportBtnTop) favExportBtnTop.classList.toggle('hidden', currentCategory !== 'favorites' || papers.length === 0);

    if (papers.length === 0) {
        noResults.classList.remove('hidden');
        papersGrid.classList.add('hidden');
        loader.classList.add('hidden');
        // 空結果時仍保留排序/時間範圍 UI,使用者可調整條件再試
        if (themeEl) themeEl.textContent = '';
        if (metaEl) metaEl.textContent = '';
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
    const rangeLabel = getTimeRangeMeta().label;
    if (customTitle) {
        themeTitle = customTitle;
    } else if (currentCategory === "all") {
        themeTitle = `${rangeLabel}所有最新論文`;
    } else if (currentCategory === "top_conf") {
        themeTitle = `${rangeLabel}入選 ${ACTIVE_DISCIPLINE?.name || ''} 頂尖會議／期刊的論文`;
    } else if (CONF_FILTERS.has(currentCategory)) {
        const confName = document.querySelector(`.category-btn[data-filter="${currentCategory}"]`)?.innerText || currentCategory;
        themeTitle = `${rangeLabel}提及 ${confName} 的論文`;
    } else if (currentCategory === "favorites") {
        themeTitle = "⭐ 我的收藏論文";
    } else {
        const activeLabel = document.querySelector('.category-btn.active .label-span')?.textContent.trim()
            || document.querySelector('.category-btn.active')?.textContent.trim() || currentCategory;
        themeTitle = `${rangeLabel}關於「${activeLabel}」的論文`;
    }

    if (themeEl) themeEl.textContent = themeTitle;
    if (metaEl) {
        let metaText = `共 ${papers.length} 篇　第 ${currentPage} / ${totalPages} 頁`;
        if (!customTitle && lastDataAsOf > 0) {
            metaText += `　· 資料更新於 ${relativeTime(lastDataAsOf)}`;
        }
        metaEl.textContent = metaText;
    }

    const start = (currentPage - 1) * PAPERS_PER_PAGE;
    const pagePapers = papers.slice(start, start + PAPERS_PER_PAGE);

    const frag = document.createDocumentFragment();
    pagePapers.forEach((paper, index) => {
        const card = buildCard(paper, index);
        frag.appendChild(card);
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

function getCitationCount(url, paper = null) {
    const id = getArxivId(url);
    if (id && s2Cache[id] !== undefined) return s2Cache[id].count;
    // backend payload fallback: OpenAlex/Crossref/S2 已在 merge 階段帶 citation_count,
    // 但前端 s2Cache 只認 arXiv id。非 arXiv 來源(或尚未 fetch S2)時改讀後端值。
    if (paper && Number.isFinite(paper.citation_count) && paper.citation_count >= 0) {
        return paper.citation_count;
    }
    return -1;
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
    const cit = getCitationCount(paper.url, paper);
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

// ── 論文價值分數（Value）──────────────────────────────────────
// 每個軸歸一化到 0..1，由 static/value-metrics.js 做加權。
function _norm01(x) { return Math.max(0, Math.min(1, x)); }
function _logScale(v, cap) {
    // log(1+v) / log(1+cap) → 對數平滑，v>=cap 視為 1
    if (v <= 0) return 0;
    return _norm01(Math.log1p(v) / Math.log1p(cap));
}

const SIGNAL_AXIS_ORDER = ['citation', 'influence', 'attention', 'code', 'velocity', 'venue', 'local'];
const SIGNAL_AXIS_LABEL = {
    citation:  '引',
    influence: '影',
    attention: '熱',
    code:      '碼',
    velocity:  '速',
    venue:     '會',
    local:     '閱',
};
const SIGNAL_AXIS_TITLE = {
    citation:  '引用數（Semantic Scholar）',
    influence: '高影響引用',
    attention: '社群熱度（HuggingFace upvote）',
    code:      '開源釋出 + GitHub star',
    velocity:  '引用速度（每月新增）',
    venue:     'Venue h5 近似權重',
    local:     '本機點閱次數',
};

function renderBridgeBadge(card, paper) {
    if (typeof window.detectBridgeDisciplines !== 'function') return;
    const activeId = ACTIVE_DISCIPLINE?.id;
    const hits = window.detectBridgeDisciplines(paper).filter(id => id !== activeId);
    if (hits.length < 1) return;           // 需至少 1 個「非當前領域」方向 → 才算 bridge
    const totalSpan = (activeId ? 1 : 0) + hits.length;
    if (totalSpan < 2) return;

    const slot = card.querySelector('.venue-badge-slot');
    const titleEl = card.querySelector('.paper-title');
    // 小徽章：🌉 + 其他領域 icon（最多 3 個）
    const badge = document.createElement('span');
    badge.className = 'bridge-badge';
    const others = hits.slice(0, 3).map(id => window.DISCIPLINES[id]);
    const label = others.map(d => `${d.icon}${d.name}`).join(' · ');
    badge.title = `跨領域（Bridge）：本文同時涵蓋 ${others.map(d => d.name).join('、')} 的關鍵字`;
    badge.innerHTML = `🌉 Bridge <span class="bridge-others">${escapeHtml(label)}</span>`;
    if (slot) slot.insertAdjacentElement('afterend', badge);
    else if (titleEl) titleEl.parentNode.insertBefore(badge, titleEl);
}

function renderSignalBlock(card, paper) {
    const block = card.querySelector('.signal-block');
    if (!block) return;
    const { score, axes, label, tier, reasons } = computeSignal(paper);
    block.hidden = false;
    block.querySelector('.signal-score-num').textContent = score;
    const tierEl = block.querySelector('.value-tier');
    if (tierEl) {
        tierEl.textContent = label || '觀望';
        tierEl.dataset.tier = tier || 'watch';
    }
    const axesEl = block.querySelector('.signal-axes');
    if (!axesEl) return;
    axesEl.textContent = '';
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

    const reasonsEl = block.querySelector('.value-reasons');
    if (reasonsEl) {
        reasonsEl.textContent = '';
        const list = reasons?.length ? reasons : ['等待引用與熱度資料'];
        for (const reason of list.slice(0, 4)) {
            const chip = document.createElement('span');
            chip.className = 'value-reason';
            chip.textContent = reason;
            reasonsEl.appendChild(chip);
        }
    }
}

function computeSignal(paper) {
    const cit = Math.max(0, getCitationCount(paper.url, paper));
    const influential = Math.max(0, getInfluentialCitations(paper.url));
    const pwc = getPwcData(paper.url) || {};
    const hasCode = !!pwc.github_url || /https?:\/\/github\.com\//i.test(paper.summary || '');
    const stars = pwc.stars || 0;
    const metricInput = {
        citations: cit,
        influential,
        refs: Math.max(0, getRefCount(paper.url)),
        hfUpvotes: Math.max(0, paper.hf_upvotes || 0),
        hasCode,
        stars,
        citationSpeed: getCitationSpeed(paper),
        venueH5: getVenueH5(paper),
        localViews: getPaperClicks(paper.url),
    };
    if (window.ValueMetrics?.computeValueMetrics) {
        return window.ValueMetrics.computeValueMetrics(metricInput);
    }
    return { score: 0, tier: 'watch', label: '觀望', axes: {}, reasons: [] };
}

async function fetchCitationCounts(papers) {
    const progressBar = document.getElementById('topProgressBar');
    if (progressBar) { progressBar.style.width = '0%'; progressBar.classList.add('active'); }

    const now = Date.now();
    const idTitleMap = {};
    for (const p of papers) {
        const id = getArxivId(p.url);
        if (id && p.title) idTitleMap[id] = p.title;
    }
    const ids = [...new Set(Object.keys(idTitleMap))];
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

    // 只在需要 DBLP venue fallback 時帶 titles (server 會自己判斷)
    const titles = {};
    for (const id of needed) if (idTitleMap[id]) titles[id] = idTitleMap[id];

    // GET 分批: 留足 URL 長度餘裕，titles 只帶短字串給 DBLP fallback
    const CHUNK = 60;
    try {
        for (let i = 0; i < needed.length; i += CHUNK) {
            const chunk = needed.slice(i, i + CHUNK);
            const chunkTitles = {};
            for (const id of chunk) if (titles[id]) chunkTitles[id] = titles[id].slice(0, 180);
            const params = new URLSearchParams({
                arxiv_ids: chunk.join(','),
                titles: JSON.stringify(chunkTitles),
            });
            const res = await fetch(`/api/citations?${params.toString()}`);
            if (!res.ok) continue;
            const data = await res.json();
            const t = Date.now();
            for (const [id, entry] of Object.entries(data.results || {})) {
                s2Cache[id] = { ...entry, at: t };
            }
        }
        purgeS2();
        scheduleSave(S2_CACHE_KEY, () => s2Cache);
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
        const CHUNK = 80;
        let touched = false;
        for (let i = 0; i < needed.length; i += CHUNK) {
            const chunk = needed.slice(i, i + CHUNK);
            const res = await fetch(`/api/pwc?arxiv_ids=${encodeURIComponent(chunk.join(','))}`);
            if (!res.ok) continue;
            const data = await res.json();
            const t = Date.now();
            for (const id of chunk) {
                const entry = data.results?.[id];
                if (entry) {
                    pwcCache[id] = { github_url: entry.github_url || null, stars: entry.stars || 0, at: t };
                } else {
                    pwcCache[id] = { at: t };  // 標記已探測避免重複呼叫
                }
                touched = true;
            }
        }
        if (!touched) return false;
        purgePwc();
        scheduleSave(PWC_CACHE_KEY, () => pwcCache);
        return true;
    } catch (e) {
        return false;
    }
}

function _matchCatTerm(term, tLc, sLc) {
    if (tLc.includes(term) || sLc.includes(term)) return true;
    if (!term.includes(' ')) return false;
    const toks = term.split(/\s+/).filter(t => t.length >= 2);
    if (toks.length < 2) return false;
    return toks.every(tok => tLc.includes(tok) || sLc.includes(tok));
}

function applyFilter(pool, query) {
    const cat = currentCategory === 'all' || currentCategory === 'favorites' || currentCategory === 'top_conf' || currentCategory === 'hf_daily' || currentCategory === 'emerging' || currentCategory === 'popular' || currentCategory === 'reviews' || currentCategory === 'my_fields' || currentCategory.startsWith('custom_') || CONF_FILTERS.has(currentCategory)
        ? null
        : currentCategory.toLowerCase();
    const confKey = CONF_FILTERS.get(currentCategory);
    const catTerms = cat
        ? [cat, ...(TOPIC_SYNONYMS[cat] || [])]
            .map(t => String(t).toLowerCase().trim())
            .filter(Boolean)
        : [];

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
            matchesCategory = catTerms.some(term => _matchCatTerm(term, tLc, sLc));
        }

        return matchesQuery && matchesCategory;
    });
}

function currentCategoryLabel() {
    if (currentCategory === 'all') return '所有論文';
    if (currentCategory === 'favorites') return '收藏論文';
    if (currentCategory === 'top_conf') return `${ACTIVE_DISCIPLINE?.name || ''} 頂尖會議／期刊`;
    if (currentCategory === 'hf_daily') return 'HuggingFace 每日精選';
    if (currentCategory === 'emerging') return '爆發中論文';
    if (currentCategory === 'popular') return '熱門論文';
    if (currentCategory === 'reviews') return '評審熱度';
    if (currentCategory === 'my_fields') return '我的領域';
    if (CONF_FILTERS.has(currentCategory)) {
        return document.querySelector(`.conf-item[data-filter="${currentCategory}"]`)?.textContent.trim()
            || CONF_FILTERS.get(currentCategory)?.toUpperCase()
            || currentCategory;
    }
    return document.querySelector('.category-btn.active .label-span')?.textContent.trim()
        || document.querySelector('.category-btn.active')?.textContent.trim()
        || currentCategory;
}

function buildMetricTitle() {
    const range = getTimeRangeMeta().label;
    const sort = getSortMeta();
    const subject = currentCategoryLabel();
    if (currentSortValue === 'latest') return null;
    return `${range}${sort.title} · ${subject}`;
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

async function ensureQuarterPapers() {
    if (quarterPapers.length > 0) return;
    loader.classList.remove('hidden');
    papersGrid.classList.add('hidden');
    try {
        const disc = ACTIVE_DISCIPLINE?.id || 'cv';
        const res = await fetch(`/api/papers?days=90&discipline=${encodeURIComponent(disc)}`);
        if (!res.ok) throw new Error();
        quarterPapers = indexPapers((await res.json()).papers);
    } catch (e) {
        quarterPapers = monthPapers.length ? monthPapers : allPapers;
    } finally {
        loader.classList.add('hidden');
        papersGrid.classList.remove('hidden');
    }
}

async function papersForCurrentTimeRange() {
    if (currentTimeRange === 'quarter') {
        await ensureQuarterPapers();
        return quarterPapers;
    }
    if (currentTimeRange === 'month') {
        await ensureMonthPapers();
        return monthPapers;
    }
    return allPapers;
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

// 爆發中:/api/emerging 依 discipline 回傳 citation+HF velocity 融合排序的論文。
// 後端已排序+附 emergence,前端只負責渲染。cache 依 discipline 失效。
let _emergingCache = null;        // { disc, papers, warming_up }
async function ensureEmerging() {
    const disc = ACTIVE_DISCIPLINE?.id || 'cv';
    if (_emergingCache && _emergingCache.disc === disc) return _emergingCache;
    const res = await fetch(`/api/emerging?discipline=${encodeURIComponent(disc)}&window=7&limit=40`);
    if (!res.ok) throw new Error('Emerging fetch failed');
    const data = await res.json();
    if ((ACTIVE_DISCIPLINE?.id || 'cv') !== disc) return _emergingCache || { disc, papers: [], warming_up: false };
    _emergingCache = { disc, papers: indexPapers(data.papers || []), warming_up: !!data.warming_up };
    return _emergingCache;
}

// 評審熱度:/api/reviews 跨四大會議聚合、依 review_avg 排序的已評審投稿。
// 與 discipline 無關（全領域會議），快取一份即可。
let _reviewsCache = null;
async function ensureReviews() {
    if (_reviewsCache) return _reviewsCache;
    const res = await fetch('/api/reviews');
    if (!res.ok) throw new Error('Reviews fetch failed');
    const data = await res.json();
    _reviewsCache = indexPapers(data.papers || []);
    return _reviewsCache;
}

// 熱門:/api/popular 全站匿名開啟次數排行(近 7 天)。內容隨點擊變動,每次開啟視圖即時抓取。
async function fetchPopular() {
    const res = await fetch('/api/popular?days=7&limit=40');
    if (!res.ok) throw new Error('Popular fetch failed');
    const data = await res.json();
    return indexPapers(data.papers || []);
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

// 收藏夾資料來源：union 所有已知論文池
// 修 bug：原本 pool=allPapers（7 天窗），若使用者從 HF Daily / 頂會 / 全網搜尋按下星星，
// 那篇論文不在 7 天窗，切到收藏夾會看到 0 篇。
function _favoritesPool() {
    const known = new Map();
    const sources = [allPapers, monthPapers, _hfDailyCache];
    for (const arr of sources) {
        if (!arr) continue;
        for (const p of arr) if (p && p.url) known.set(p.url, p);
    }
    const list = [];
    for (const url of favorites) {
        const p = known.get(url);
        if (p) list.push(p);
        // 完全沒收錄（例如從全網搜尋結果按下星星）→ 補 stub，至少能顯示連結與標題
        else list.push({
            url,
            title: (url.split('/abs/')[1] || url),
            summary: '',
            authors: [],
            published: '',
        });
    }
    return indexPapers(list);
}

async function filterPapers() {
    currentPage = 1;
    const query = searchInput.value.toLowerCase().trim();
    const sortValue = currentSortValue;

    // 收藏夾：使用所有已知來源 union，不受 7-day 視窗限制
    if (currentCategory === 'favorites') {
        let papers = _favoritesPool();
        if (query) {
            papers = papers.filter(p => {
                const tLc = p._titleLc ?? (p.title || '').toLowerCase();
                const sLc = p._summaryLc ?? (p.summary || '').toLowerCase();
                const aLc = p._authorsLc ?? (p.authors || []).join(' ').toLowerCase();
                return tLc.includes(query) || sLc.includes(query) || aLc.includes(query);
            });
        }
        papers = applyTimeRange(papers);
        await prepareMetricData(papers, sortValue);
        papers = sortPapersByMetric(papers, sortValue);
        const range = getTimeRangeMeta().label;
        const sortLabel = getSortMeta().label;
        renderPapers(papers, `⭐ 我的收藏（${range} · ${sortLabel} · ${papers.length} 篇）`);
        return;
    }

    // HF Daily：由後端拉 HuggingFace 每日精選
    if (currentCategory === 'hf_daily') {
        papersGrid.classList.add('hidden');
        noResults.classList.add('hidden');
        loader.classList.remove('hidden');
        try {
            let papers = await ensureHfDaily();
            if (query) papers = applyFilter(papers, query);
            papers = applyTimeRange(papers);
            await prepareMetricData(papers, sortValue);
            papers = sortValue === 'latest'
                ? sortPapersByMetric(papers, 'hf')
                : sortPapersByMetric(papers, sortValue);
            const disciplineTag = ACTIVE_DISCIPLINE ? `${ACTIVE_DISCIPLINE.icon} ${ACTIVE_DISCIPLINE.name}` : '';
            const allTotal = _hfDailyCache?.length || 0;
            const filteredTotal = papers.length;
            const rangeLabel = getTimeRangeMeta().label;
            const sortLabel = sortValue === 'latest' ? '依社群 upvote' : `依${getSortMeta().label}`;
            const suffix = disciplineTag && filteredTotal !== allTotal
                ? `（${rangeLabel} · ${disciplineTag} 相關 · ${sortLabel}）`
                : `（${rangeLabel} · ${sortLabel}）`;
            renderPapers(papers, `🤗 HuggingFace 每日精選${suffix}`);
        } catch (e) {
            loader.classList.add('hidden');
            alert('HF Daily 載入失敗：' + e.message);
        }
        return;
    }

    // 爆發中:後端 /api/emerging 已依 emergence 排序;預設不再前端重排(latest=保留後端爆發序)
    if (currentCategory === 'emerging') {
        papersGrid.classList.add('hidden');
        noResults.classList.add('hidden');
        loader.classList.remove('hidden');
        try {
            const res = await ensureEmerging();
            let papers = res.papers;
            if (query) papers = applyFilter(papers, query);
            if (!papers.length) {
                const why = res.warming_up
                    ? '🌱 資料累積中:爆發偵測需要至少兩天的每日快照,過幾天再回來看'
                    : '目前此領域沒有明顯爆發的論文,可切換排序或稍後再試';
                showToast(why);
                renderPapers([], `🚀 爆發中（${ACTIVE_DISCIPLINE?.name || ''}）`);
                return;
            }
            // 非 latest 才依使用者選的指標重排;latest 保留後端爆發序
            if (sortValue !== 'latest') {
                await prepareMetricData(papers, sortValue);
                papers = sortPapersByMetric(papers, sortValue);
            }
            const sortLabel = sortValue === 'latest' ? '依爆發指數' : `依${getSortMeta().label}`;
            renderPapers(papers, `🚀 爆發中（${ACTIVE_DISCIPLINE?.name || ''} · 近 7 天 · ${sortLabel} · ${papers.length} 篇）`);
        } catch (e) {
            loader.classList.add('hidden');
            alert('爆發中載入失敗：' + e.message);
        }
        return;
    }

    // 熱門:全站使用者近 7 天開啟最多的論文(/api/popular,匿名點擊熱度)
    if (currentCategory === 'popular') {
        papersGrid.classList.add('hidden');
        noResults.classList.add('hidden');
        loader.classList.remove('hidden');
        try {
            let papers = await fetchPopular();
            if (query) papers = applyFilter(papers, query);
            // 後端已依開啟次數排序;非 latest 才依使用者指標重排
            if (sortValue !== 'latest') {
                await prepareMetricData(papers, sortValue);
                papers = sortPapersByMetric(papers, sortValue);
            }
            if (!papers.length) {
                showToast('還沒有足夠的開啟紀錄,點開幾篇論文後熱門榜就會出現');
                renderPapers([], '🔥 熱門');
                return;
            }
            const sortLabel = sortValue === 'latest' ? '依開啟次數' : `依${getSortMeta().label}`;
            renderPapers(papers, `🔥 熱門（近 7 天 · ${sortLabel} · ${papers.length} 篇）`);
        } catch (e) {
            loader.classList.add('hidden');
            alert('熱門載入失敗：' + e.message);
        }
        return;
    }

    // 評審熱度:四大會議當前審查週期已評審投稿,後端依 review_avg 排序
    if (currentCategory === 'reviews') {
        papersGrid.classList.add('hidden');
        noResults.classList.add('hidden');
        loader.classList.remove('hidden');
        try {
            let papers = await ensureReviews();
            if (query) papers = applyFilter(papers, query);
            // 後端已依 review_avg 排序;非 latest 才依使用者指標重排
            if (sortValue !== 'latest') {
                await prepareMetricData(papers, sortValue);
                papers = sortPapersByMetric(papers, sortValue);
            }
            if (!papers.length) {
                showToast('目前四大會議審查週期尚無公開評分,審稿開放後會自動出現');
                renderPapers([], '📊 評審熱度');
                return;
            }
            const sortLabel = sortValue === 'latest' ? '依評審均分' : `依${getSortMeta().label}`;
            renderPapers(papers, `📊 評審熱度（ICLR/NeurIPS/ICML/COLM · ${sortLabel} · ${papers.length} 篇）`);
        } catch (e) {
            loader.classList.add('hidden');
            alert('評審熱度載入失敗：' + e.message);
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
            let papers = applyTimeRange(indexPapers(data.papers));
            await prepareMetricData(papers, sortValue);
            papers = sortPapersByMetric(papers, sortValue);
            renderPapers(papers, `${confName} 相關論文（${getTimeRangeMeta().label} · 依${getSortMeta().label}）`);
        } catch (e) {
            loader.classList.add('hidden');
            alert('搜尋失敗：' + e.message);
        }
        return;
    }

    // 自訂訂閱(#17):直接打 /api/custom,組合 arXiv cat/keyword/author/id 查詢
    if (currentCategory.startsWith('custom_')) {
        const feed = getCustomFeed(currentCategory);
        if (!feed) {
            renderPapers([], '🛰️ 自訂訂閱（找不到，請重建）');
            return;
        }
        papersGrid.classList.add('hidden');
        noResults.classList.add('hidden');
        loader.classList.remove('hidden');
        try {
            const days = getTimeRangeMeta().days || 30;
            const qs = _customFeedQuery(feed, { days, max_results: 100 });
            const res = await fetch(`/api/custom?${qs}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            let papers = indexPapers(Array.isArray(data.papers) ? data.papers : []);
            if (query) papers = applyFilter(papers, query);
            papers = applyTimeRange(papers);
            await prepareMetricData(papers, sortValue);
            papers = sortPapersByMetric(papers, sortValue);
            if (!papers.length) {
                showToast('此自訂訂閱目前沒有命中,試著放寬條件或拉長時間範圍');
            }
            renderPapers(papers, `🛰️ ${feed.name}（${getTimeRangeMeta().label} · 依${getSortMeta().label} · ${papers.length} 篇）`);
        } catch (e) {
            loader.classList.add('hidden');
            alert('自訂訂閱載入失敗：' + e.message);
        }
        return;
    }

    // 我的領域(#14):把追蹤清單(getTracks)合併成單一去重、排序的 feed
    if (currentCategory === 'my_fields') {
        const fields = (window.getTracks?.() || []);
        papersGrid.classList.add('hidden');
        noResults.classList.add('hidden');
        loader.classList.remove('hidden');
        if (!fields.length) {
            loader.classList.add('hidden');
            renderPapers([], '🗂️ 我的領域（尚未追蹤任何領域）');
            showToast('先在「切換研究領域」面板用 ☆ 星號追蹤幾個領域，這裡就會合併成單一動態');
            if (typeof openDisciplinePicker === 'function') openDisciplinePicker({ closable: true });
            return;
        }
        try {
            const days = getTimeRangeMeta().days || 7;
            const params = new URLSearchParams({ fields: fields.join(','), days: String(days), max_results: '300' });
            const res = await fetch(`/api/feed?${params}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            let papers = indexPapers(Array.isArray(data.papers) ? data.papers : []);
            if (query) papers = applyFilter(papers, query);
            papers = applyTimeRange(papers);
            await prepareMetricData(papers, sortValue);
            papers = sortPapersByMetric(papers, sortValue);
            if (!papers.length) showToast('追蹤的領域近期沒有新論文，試著拉長時間範圍或多追蹤幾個領域');
            const names = fields.map(id => window.DISCIPLINES?.[id]?.name || id).join('、');
            renderPapers(papers, `🗂️ 我的領域（${names} · ${getTimeRangeMeta().label} · 依${getSortMeta().label} · ${papers.length} 篇）`);
        } catch (e) {
            loader.classList.add('hidden');
            alert('我的領域載入失敗：' + e.message);
        }
        return;
    }

    const pool = await papersForCurrentTimeRange();
    let filtered = applyFilter(pool, query);
    filtered = applyTimeRange(filtered);

    if (sortValue === 'personalized') {
        const reranked = await applyPersonalizedRerank(filtered);
        if (reranked) {
            renderPapers(reranked, buildMetricTitle());
            return;
        }
        // 失敗或無收藏:fallback 到 latest
    }
    await prepareMetricData(filtered, sortValue === 'personalized' ? 'latest' : sortValue);
    filtered = sortPapersByMetric(filtered, sortValue === 'personalized' ? 'latest' : sortValue);
    renderPapers(filtered, buildMetricTitle());
}

// 個人化重排:取收藏的 arxiv id,呼叫 /api/personalized,失敗回 null 走 fallback
async function applyPersonalizedRerank(filtered) {
    const favIds = [];
    for (const url of favorites) {
        const m = url.match(/arxiv\.org\/(?:abs|pdf)\/(\d{4}\.\d{4,6})/i);
        if (m) favIds.push(m[1]);
    }
    if (favIds.length < 3) {
        alert('「為你推薦」需要至少 3 篇收藏的 arXiv 論文。');
        return null;
    }
    const disc = ACTIVE_DISCIPLINE?.id || '';
    try {
        const url = `/api/personalized?favorites=${encodeURIComponent(favIds.slice(0, 50).join(','))}&discipline=${encodeURIComponent(disc)}&top_k=60&blend=0.4`;
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const reranked = data.papers || [];
        if (!reranked.length) return null;
        // 與 filtered 取交集(保 filter / time-range),保 reranked 順序
        const allowedUrls = new Set(filtered.map(p => p.url));
        const out = reranked.filter(p => allowedUrls.has(p.url));
        // reranked 可能少於 filtered;補上未排到的 filtered 維持完整度
        const seen = new Set(out.map(p => p.url));
        for (const p of filtered) if (!seen.has(p.url)) out.push(p);
        return indexPapers(out);
    } catch (e) {
        console.warn('personalized rerank failed:', e);
        return null;
    }
}

async function filterByTag(tag) {
    if (!tag) return;
    const urls = new Set(Object.keys(paperTags).filter(u => (paperTags[u] || []).includes(tag)));
    let matched = applyTimeRange(allPapers).filter(p => urls.has(p.url));
    // 若 allPapers 沒收錄（可能是搜尋結果裡的論文），就組一個最小 stub
    if (matched.length === 0 && urls.size > 0) {
        for (const u of urls) {
            matched.push({ url: u, title: u.split('/abs/')[1] || u, summary: '', authors: [], published: '' });
        }
    }
    matched = indexPapers(matched);
    await prepareMetricData(matched, currentSortValue);
    renderPapers(sortPapersByMetric(matched, currentSortValue), `標籤 #${tag}（${getTimeRangeMeta().label}）`);
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
        let papers = applyTimeRange(indexPapers(data.papers || []));
        await prepareMetricData(papers, currentSortValue);
        papers = sortPapersByMetric(papers, currentSortValue);
        renderPapers(papers, `全網搜尋「${query}」（${getTimeRangeMeta().label} · 依${getSortMeta().label}）`);
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
        writeUrlState();  // #11 清空搜尋 → URL 去掉 q
        return;
    }
    if (window._SEMANTIC_ON) return; // semantic 模式只在 Enter 時觸發
    searchDebounceTimer = setTimeout(() => { searchAllPapers(query); writeUrlState(); }, 250);
}

async function semanticSearchPapers(query) {
    currentPage = 1;
    papersGrid.classList.add('hidden');
    noResults.classList.add('hidden');
    loader.classList.remove('hidden');
    const loaderText = document.getElementById('loaderText');
    if (loaderText) loaderText.textContent = '🧠 計算語意相似度中（首次搜尋會慢一些）…';

    if (_searchAbort) _searchAbort.abort();
    _searchAbort = new AbortController();
    const signal = _searchAbort.signal;

    const disc = window.getActiveDiscipline?.()?.id || 'cv';
    const cross = window._CROSS_DISC_ON ? '&cross=true' : '';
    const url = `/api/semantic-search?q=${encodeURIComponent(query)}&discipline=${encodeURIComponent(disc)}&days=180&top_k=40${cross}`;
    try {
        const res = await fetch(url, { signal });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        if (signal.aborted) return;
        let papers = indexPapers(data.papers || []);
        await prepareMetricData(papers, currentSortValue);
        // semantic 結果已照相似度排序；若使用者改 sort 則重排，否則保留原序
        if (currentSortValue && currentSortValue !== 'latest') {
            papers = sortPapersByMetric(papers, currentSortValue);
        }
        const scope = data.discipline === 'all' ? '跨領域' : (window.getActiveDiscipline?.()?.name || '');
        renderPapers(papers, `🧠 語意搜尋「${query}」（${scope} · ${data.pool_size || 0} 候選）`);
    } catch (e) {
        if (e.name === 'AbortError') return;
        loader.classList.add('hidden');
        if (loaderText) loaderText.textContent = '正在自動為您抓取最新論文...';
        showToast('語意搜尋失敗：' + e.message);
    }
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
    document.querySelectorAll('.category-btn, .topic-item').forEach(b => {
        if (b.classList.contains('topic-group-btn')) return;
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
            const target = document.querySelector(
                `.category-btn[data-filter="${CSS.escape(filter)}"], .topic-item[data-filter="${CSS.escape(filter)}"]`
            );
            if (target) {
                const groupWrapper = target.closest('.topic-group-wrapper');
                if (groupWrapper) groupWrapper.classList.add('open');
                target.click();
            }
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
    document.querySelectorAll('.category-btn, .topic-item').forEach(btn => {
        if (btn.classList.contains('topic-group-btn')) return;
        const orig = btn.dataset.filter;
        if (!orig) return;
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

    const renames = loadRenamedBuiltins();
    renames[origFilter] = { label: trimmed, filter: newFilter };
    saveRenamedBuiltins(renames);
    showToast(`已重新命名為「${trimmed}」`);
    filterPapers();
}

// ── 刪除標籤 ────────────────────────────────────────────────────
function deleteCategoryBtn(btn) {
    const label = getLabelText(btn);
    const origFilter = btn.dataset.originalFilter || btn.dataset.filter;

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

    const deleted = loadDeletedBuiltins();
    deleted.add(origFilter);
    saveDeletedBuiltins(deleted);
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

// #16 子主題伺服器端深抓:保留字與會議 filter 不觸發(它們走既有特殊邏輯)
const _RESERVED_CATEGORIES = new Set([
    'all', 'favorites', 'top_conf', 'hf_daily', 'emerging', 'popular', 'reviews',
]);
const _topicFeedFetched = new Set();   // `${disc}::${topic}` 已抓過/進行中,避免重複請求
let _topicFeedToken = 0;

function _isTopicFilter(filter) {
    if (!filter || _RESERVED_CATEGORIES.has(filter)) return false;
    if (filter.startsWith('custom_')) return false;   // 自訂訂閱走自己的 /api/custom 分支
    if (typeof CONF_FILTERS !== 'undefined' && CONF_FILTERS.has(filter)) return false;
    return true;
}

// 漸進增強:選子主題時除了即時 client 端篩選,另向 server 抓 topic 收窄的深度結果
// (arXiv 全文片語查詢),併入 allPapers 後重新篩選 — 不阻塞當前畫面。
async function _fetchTopicFeed(filter) {
    if (!_isTopicFilter(filter)) return;
    const disc = ACTIVE_DISCIPLINE?.id || 'cv';
    const key = `${disc}::${filter}`;
    if (_topicFeedFetched.has(key)) return;
    _topicFeedFetched.add(key);
    const token = ++_topicFeedToken;
    const days = getTimeRangeMeta().days || 7;
    const url = `/api/papers?max_results=100&days=${days}`
        + `&discipline=${encodeURIComponent(disc)}&topic=${encodeURIComponent(filter)}`;
    let data;
    try {
        const res = await fetch(url);
        if (!res.ok) { _topicFeedFetched.delete(key); return; }
        data = await res.json();
    } catch (_) {
        _topicFeedFetched.delete(key);   // 失敗可重試
        return;
    }
    if (token !== _topicFeedToken) return;                  // 已切到別的 topic
    if ((ACTIVE_DISCIPLINE?.id || 'cv') !== disc) return;   // 已切 discipline
    const incoming = Array.isArray(data?.papers) ? data.papers : [];
    if (!incoming.length) return;
    const seen = new Set(allPapers.map(p => p.url));
    const fresh = incoming.filter(p => p?.url && !seen.has(p.url));
    if (!fresh.length) return;
    allPapers = indexPapers(allPapers.concat(fresh));
    if (currentCategory === filter) await filterPapers();
}

function _selectCategory(filter, activeEl) {
    document.querySelectorAll('.category-btn, .topic-item').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.conf-item').forEach(b => b.classList.remove('active'));
    if (activeEl) activeEl.classList.add('active');
    currentCategory = filter;
    localStorage.setItem(LAST_CATEGORY_KEY, filter);
    // 按下 All 一律回到「都沒有篩選」的狀態:清空搜尋框
    if (filter === 'all') {
        const si = document.getElementById('searchInput');
        if (si && si.value) si.value = '';
    }
    syncTopConfActiveState();
    filterPapers();
    if (_isTopicFilter(filter)) _fetchTopicFeed(filter);
    writeUrlState();  // #11
}

function bindCategoryBtns() {
    const filtersDiv = document.querySelector('.category-filters');
    if (!filtersDiv || filtersDiv._delegated) return;
    filtersDiv._delegated = true;

    filtersDiv.addEventListener('click', (e) => {
        const topicItem = e.target.closest('.topic-item');
        if (topicItem) {
            _selectCategory(topicItem.dataset.filter, topicItem);
            return;
        }
        const btn = e.target.closest('.category-btn');
        if (!btn || btn.classList.contains('top-conf-btn') || btn.classList.contains('topic-group-btn')) return;
        if (btn.id === 'addCustomFeedBtn') { openCustomFeedModal(); return; }
        _selectCategory(btn.dataset.filter, btn);
    });

    filtersDiv.addEventListener('contextmenu', (e) => {
        const btn = e.target.closest('.category-btn, .topic-item');
        if (!btn || btn.classList.contains('topic-group-btn')) return;
        e.preventDefault();
        showCtxMenu(btn, e.pageX, e.pageY);
    });
}

let LAST_CATEGORY_KEY = 'visionary_last_category';

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

// ── #11 可分享 / 可書籤的 URL 狀態 ───────────────────────────────
const URL_STATE_DEFAULTS = { cat: 'all', sort: 'hot', range: 'week' };
let _restoringUrlState = false;

function readUrlState() {
    try {
        const p = new URLSearchParams(window.location.search);
        return { d: p.get('d'), cat: p.get('cat'), q: p.get('q'), sort: p.get('sort'), range: p.get('range') };
    } catch (e) {
        return {};
    }
}

function writeUrlState() {
    if (_restoringUrlState) return;
    try {
        const p = new URLSearchParams(window.location.search);
        const disc = window.getActiveDiscipline?.()?.id;
        const q = (document.getElementById('searchInput')?.value || '').trim();
        const set = (k, v, def) => { if (v && v !== def) p.set(k, v); else p.delete(k); };
        if (disc) p.set('d', disc); else p.delete('d');
        set('cat', currentCategory, URL_STATE_DEFAULTS.cat);
        set('sort', currentSortValue, URL_STATE_DEFAULTS.sort);
        set('range', currentTimeRange, URL_STATE_DEFAULTS.range);
        if (q) p.set('q', q); else p.delete('q');
        const qs = p.toString();
        window.history.replaceState(null, '', window.location.pathname + (qs ? '?' + qs : '') + window.location.hash);
    } catch (e) {}
}

function applyUrlStateLive(s) {
    _restoringUrlState = true;
    try {
        if (s.sort && SORT_VALUES.has(s.sort)) currentSortValue = s.sort;
        if (s.range && TIME_RANGE_VALUES.has(s.range)) currentTimeRange = s.range;
        const targetCat = s.cat || 'all';
        currentCategory = targetCat;
        try { localStorage.setItem(LAST_CATEGORY_KEY, targetCat); } catch (e) {}
        document.querySelectorAll('.category-btn, .topic-item, .conf-item').forEach(b => b.classList.remove('active'));
        const catBtn = document.querySelector(
            `.category-btn[data-filter="${CSS.escape(targetCat)}"], .topic-item[data-filter="${CSS.escape(targetCat)}"], .conf-item[data-filter="${CSS.escape(targetCat)}"]`
        );
        if (catBtn) catBtn.classList.add('active');
        const sortLabelEl = document.getElementById('sortLabel');
        if (sortLabelEl && typeof getSortMeta === 'function') sortLabelEl.textContent = getSortMeta(currentSortValue).label;
        document.querySelectorAll('#sortSubmenu .sort-item').forEach(i => i.classList.toggle('active', i.dataset.value === currentSortValue));
        document.querySelectorAll('#timeRangeWrapper .time-range-btn').forEach(b => b.classList.toggle('active', b.dataset.range === currentTimeRange));
        const si = document.getElementById('searchInput');
        if (si) { si.value = s.q || ''; si.classList.toggle('has-text', !!s.q); }
        if (typeof syncTopConfActiveState === 'function') syncTopConfActiveState();
        if (s.q) { if (window._SEMANTIC_ON) semanticSearchPapers(s.q); else searchAllPapers(s.q); }
        else filterPapers();
    } finally {
        _restoringUrlState = false;
    }
}

// Initial Load
document.addEventListener('DOMContentLoaded', () => {
    // #11 解析 URL 狀態(深連結/書籤)；d 需在 discipline gate 前先生效
    const _urlState = readUrlState();
    if (_urlState.d && window.DISCIPLINES?.[_urlState.d]) {
        window.setActiveDiscipline(_urlState.d);
    }

    // 0) 點左上角品牌 ICON 回到主頁(切回 All + 清空搜尋)
    const _brandHome = document.getElementById('brandHome');
    if (_brandHome) {
        const _goHome = () => {
            const allBtn = document.querySelector('.category-btn[data-filter="all"]');
            if (typeof _selectCategory === 'function' && allBtn) {
                _selectCategory('all', allBtn);
            } else {
                const si = document.getElementById('searchInput');
                if (si) si.value = '';
                currentCategory = 'all';
                if (typeof filterPapers === 'function') filterPapers();
            }
            window.scrollTo({ top: 0, behavior: 'smooth' });
        };
        _brandHome.addEventListener('click', _goHome);
        _brandHome.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); _goHome(); }
        });
    }

    // #5 匯出收藏為 BibTeX
    document.getElementById('favExportBtn')?.addEventListener('click', exportFavoritesBibtex);

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
    renderCustomFeedBtns();
    bindCategoryBtns();

    // 恢復上次的分類（URL cat 優先；找不到對應按鈕就 fallback 到 all,避免 stale filter 套用卻沒視覺回饋）
    const savedCategory = _urlState.cat || localStorage.getItem(LAST_CATEGORY_KEY);
    if (savedCategory && savedCategory !== 'all') {
        const isVirtual = savedCategory === 'favorites' || savedCategory === 'top_conf' || savedCategory === 'hf_daily' || savedCategory === 'emerging' || savedCategory === 'popular' || savedCategory === 'reviews' || CONF_FILTERS.has(savedCategory);
        const targetBtn = document.querySelector(
            `.category-btn[data-filter="${CSS.escape(savedCategory)}"], .topic-item[data-filter="${CSS.escape(savedCategory)}"], .conf-item[data-filter="${CSS.escape(savedCategory)}"]`
        );
        if (targetBtn || isVirtual) {
            currentCategory = savedCategory;
            if (targetBtn) {
                document.querySelectorAll('.category-btn, .topic-item, .conf-item').forEach(b => b.classList.remove('active'));
                targetBtn.classList.add('active');
                const groupWrapper = targetBtn.closest('.topic-group-wrapper');
                if (groupWrapper) groupWrapper.classList.add('open');
            }
        } else {
            // 該 category 已不存在 (主題被移除/換 discipline) → 重設為 all
            currentCategory = 'all';
            localStorage.setItem(LAST_CATEGORY_KEY, 'all');
            const allBtn = document.querySelector('.category-btn[data-filter="all"]');
            if (allBtn) allBtn.classList.add('active');
        }
    }

    // #11 套用 URL 的 sort / range（cat 已於上方處理；q 於資料載入後觸發搜尋）
    if (_urlState.sort && SORT_VALUES.has(_urlState.sort)) currentSortValue = _urlState.sort;
    if (_urlState.range && TIME_RANGE_VALUES.has(_urlState.range)) currentTimeRange = _urlState.range;

    fetchPapers().finally(() => {
        try {
            if (_urlState.q) {
                const si = document.getElementById('searchInput');
                if (si) { si.value = _urlState.q; si.classList.add('has-text'); }
                if (window._SEMANTIC_ON) semanticSearchPapers(_urlState.q);
                else searchAllPapers(_urlState.q);
            }
            writeUrlState();  // 正規化 URL（清掉預設值參數）
        } catch (e) {}
    });
    initLiveStream();  // #15 SSE 即時推播

    // #11 上/下一頁(back/forward)時重新套用 URL 狀態
    window.addEventListener('popstate', () => {
        const s = readUrlState();
        const curDisc = window.getActiveDiscipline?.()?.id;
        if (s.d && window.DISCIPLINES?.[s.d] && s.d !== curDisc) {
            window.setActiveDiscipline(s.d);
            location.reload();
            return;
        }
        applyUrlStateLive(s);
    });

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

        // 觸控/click 也能開啟（避免手機/平板無法叫出 conf submenu）
        const topConfBtn = topConfWrapper.querySelector('.top-conf-btn');
        if (topConfBtn) {
            topConfBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                if (confSubmenu.classList.contains('open')) {
                    confSubmenu.classList.remove('open');
                } else {
                    openConfSubmenu();
                }
            });
        }
        // 點外部關閉
        document.addEventListener('click', (e) => {
            if (!confSubmenu.classList.contains('open')) return;
            if (confSubmenu.contains(e.target)) return;
            if (topConfWrapper.contains(e.target)) return;
            confSubmenu.classList.remove('open');
        });

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
    const timeRangeWrapper = document.getElementById('timeRangeWrapper');
    const sortWrapper = document.getElementById('sortWrapper');
    const sortSubmenu = document.getElementById('sortSubmenu');
    const sortLabel   = document.getElementById('sortLabel');
    let sortTimer = null;
    if (sortSubmenu) document.body.appendChild(sortSubmenu);

    function updateTimeRangeUI() {
        const meta = getTimeRangeMeta();
        timeRangeWrapper?.querySelectorAll('.time-range-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.range === currentTimeRange);
        });
        const jp = document.querySelector('.jp-label');
        if (jp) jp.textContent = `${meta.short} · ${meta.en.toLowerCase()}`;
        const pageTitle = document.querySelector('.page-title');
        if (pageTitle) {
            pageTitle.textContent = '';
            pageTitle.append(`${meta.label}最新 `);
            const sub = document.createElement('span');
            sub.className = 'page-title-sub';
            sub.textContent = `${meta.en.toLowerCase()} papers`;
            pageTitle.appendChild(sub);
        }
    }

    if (timeRangeWrapper) {
        timeRangeWrapper.querySelectorAll('.time-range-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const next = btn.dataset.range;
                if (!TIME_RANGE_VALUES.has(next) || next === currentTimeRange) return;
                currentTimeRange = next;
                try { localStorage.setItem('visionary_time_range_v1', next); } catch (e) {}
                updateTimeRangeUI();
                await filterPapers();
                writeUrlState();  // #11
            });
        });
        updateTimeRangeUI();
    }

    // 初始化：反映 localStorage 儲存的 sort 選項
    (function _initSortFromStorage() {
        if (!sortSubmenu || !sortLabel) return;
        sortLabel.textContent = getSortMeta(currentSortValue).label;
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
                if (!SORT_VALUES.has(val)) return;
                currentSortValue = val;
                try { localStorage.setItem('visionary_sort_v3', val); } catch (e) {}
                // 近三月熱門:語意上就是 90 天窗 + 引用排序,自動切到 quarter
                if (val === 'hot3m' && currentTimeRange !== 'quarter') {
                    currentTimeRange = 'quarter';
                    try { localStorage.setItem('visionary_time_range_v1', 'quarter'); } catch (e) {}
                    updateTimeRangeUI();
                }
                sortLabel.textContent = getSortMeta(val).label;
                sortSubmenu.querySelectorAll('.sort-item').forEach(i => i.classList.remove('active'));
                item.classList.add('active');
                closeSortSubmenu();
                filterPapers();
                writeUrlState();  // #11
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
        if (!btn) return;
        if (btn.dataset.customFeed === 'true') { openCustomFeedModal(btn.dataset.filter); return; }
        editBtnLabel(btn);
    });
    document.getElementById('ctxDelete').addEventListener('click', (e) => {
        e.stopPropagation();
        const btn = ctxTarget;
        hideCtxMenu();
        if (!btn) return;
        if (btn.dataset.customFeed === 'true') {
            deleteCustomFeed(btn.dataset.filter);
            showToast('已刪除自訂訂閱');
            return;
        }
        deleteCategoryBtn(btn);
    });

    // ── 自訂訂閱 modal 綁定(#17) ──────────────────────────────
    document.getElementById('cfForm')?.addEventListener('submit', _submitCustomFeed);
    document.getElementById('cfClose')?.addEventListener('click', closeCustomFeedModal);
    document.querySelector('#customFeedModal .cf-backdrop')?.addEventListener('click', closeCustomFeedModal);
    document.getElementById('cfDelete')?.addEventListener('click', () => {
        if (_cfEditId) { deleteCustomFeed(_cfEditId); showToast('已刪除自訂訂閱'); }
        closeCustomFeedModal();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeCustomFeedModal();
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

    // ── 語意搜尋切換 ─────────────────────────────────────────────
    const semanticToggle = document.getElementById('semanticToggle');
    const crossDiscToggle = document.getElementById('crossDiscToggle');
    window._SEMANTIC_ON = false;
    window._CROSS_DISC_ON = false;
    try {
        window._SEMANTIC_ON = localStorage.getItem('visionary_semantic_on') === '1';
        window._CROSS_DISC_ON = localStorage.getItem('visionary_cross_disc_on') === '1';
    } catch (e) {}
    function syncSemanticUI() {
        semanticToggle.classList.toggle('active', window._SEMANTIC_ON);
        semanticToggle.setAttribute('aria-pressed', window._SEMANTIC_ON);
        crossDiscToggle.hidden = !window._SEMANTIC_ON;
        crossDiscToggle.classList.toggle('active', window._CROSS_DISC_ON);
        crossDiscToggle.setAttribute('aria-pressed', window._CROSS_DISC_ON);
        searchInput.placeholder = window._SEMANTIC_ON
            ? '描述你想找的研究（按 Enter 觸發語意搜尋）'
            : '搜尋標題、作者或關鍵字（Enter 搜全庫）';
    }
    semanticToggle.addEventListener('click', () => {
        window._SEMANTIC_ON = !window._SEMANTIC_ON;
        try { localStorage.setItem('visionary_semantic_on', window._SEMANTIC_ON ? '1' : '0'); } catch (e) {}
        syncSemanticUI();
        if (window._SEMANTIC_ON) searchInput.focus();
    });
    crossDiscToggle.addEventListener('click', () => {
        window._CROSS_DISC_ON = !window._CROSS_DISC_ON;
        try { localStorage.setItem('visionary_cross_disc_on', window._CROSS_DISC_ON ? '1' : '0'); } catch (e) {}
        syncSemanticUI();
    });
    syncSemanticUI();

    searchInput.addEventListener('keydown', (e) => {
        if (e.key !== 'Enter') return;
        const q = searchInput.value.trim();
        if (!q) return;
        e.preventDefault();
        pushRecentSearch(q);
        if (window._SEMANTIC_ON) {
            semanticSearchPapers(q);
        } else {
            searchAllPapers(q);
        }
        writeUrlState();  // #11
    });

    // ── 最近搜尋 chip bar ─────────────────────────────────────────
    renderRecentSearches();
    const recentBar = document.getElementById('recentSearchesBar');
    if (recentBar) {
        recentBar.addEventListener('click', (e) => {
            if (e.target.classList.contains('rs-clear')) {
                clearRecentSearches();
                return;
            }
            const chip = e.target.closest('.rs-chip');
            if (!chip) return;
            const q = chip.dataset.q;
            if (!q) return;
            searchInput.value = q;
            pushRecentSearch(q);
            if (window._SEMANTIC_ON) semanticSearchPapers(q);
            else searchAllPapers(q);
            writeUrlState();  // #11
        });
    }

    // ── 相似論文 modal 關閉 ───────────────────────────────────────
    document.getElementById('similarCloseBtn')?.addEventListener('click', closeSimilarModal);
    document.querySelector('#similarModal .similar-backdrop')?.addEventListener('click', closeSimilarModal);
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeSimilarModal();
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
            writeUrlState();  // #11
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
        const tag = document.activeElement.tagName;
        const inEditable = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
        // Escape:輸入框中按 Esc 先離開焦點(讓使用者能用 J/K)
        if (e.key === 'Escape' && inEditable) {
            document.activeElement.blur();
            return;
        }
        if (inEditable) return;

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
        _statsEls.fresh = document.getElementById('statNew');
        _statsEls.fresh?.addEventListener('click', showNewSinceVisit);
    }
    if (!_statsEls.read) return;

    const totalCount = Array.isArray(currentFilteredPapers) ? currentFilteredPapers.length : allPapers.length;
    const newCount = newSinceVisitCount();
    const snapshot = `${readSet.size}|${favorites.size}|${Object.keys(notesMap).length}|${totalCount}|${newCount}`;
    if (snapshot === _statsSnapshot) return;
    _statsSnapshot = snapshot;

    _statsEls.read.textContent  = `📖 已讀 ${readSet.size}`;
    _statsEls.fav.textContent   = `⭐ 收藏 ${favorites.size}`;
    _statsEls.notes.textContent = `📝 筆記 ${Object.keys(notesMap).length}`;
    _statsEls.total.textContent = `📚 ${getTimeRangeMeta().label} ${totalCount} 篇`;
    if (_statsEls.fresh) {
        _statsEls.fresh.textContent = `🆕 新增 ${newCount}`;
        _statsEls.fresh.classList.toggle('hidden', newCount === 0);
    }
}

setTimeout(updateStats, 300);
let _statsTimer = null;
function _startStatsTimer() {
    if (_statsTimer) return;
    _statsTimer = setInterval(updateStats, 2000);
}
function _stopStatsTimer() {
    if (_statsTimer) { clearInterval(_statsTimer); _statsTimer = null; }
}
if (!document.hidden) _startStatsTimer();
document.addEventListener('visibilitychange', () => {
    if (document.hidden) _stopStatsTimer();
    else { updateStats(); _startStatsTimer(); }
});

// ── 主題：固定淺色（移除黑夜模式）──
document.body.classList.add('light-mode');
try { localStorage.removeItem('visionary_theme'); } catch (_) {}

// ── 回到頂部 ──────────────────────────────────────────────────
const backToTopBtn = document.getElementById('backToTopBtn');
backToTopBtn?.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));

// ── Service Worker 註冊 ───────────────────────────────────────
if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === 'localhost' || location.hostname === '127.0.0.1')) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js').catch(() => {});
    });
}


// ── 鍵盤快捷鍵說明按鈕 ────────────────────────────────────────
document.getElementById('kbdHintBtn')?.addEventListener('click', () => {
    document.getElementById('kbdHint')?.classList.toggle('visible');
});

// ── #13 命令面板（Ctrl/Cmd-K）─────────────────────────────────────
(function initCommandPalette() {
    const palette = document.getElementById('cmdPalette');
    const input = document.getElementById('cmdInput');
    const resultsEl = document.getElementById('cmdResults');
    if (!palette || !input || !resultsEl) return;

    let _cmdItems = [];   // 目前渲染的可執行項目（依 DOM 順序）
    let _selIdx = 0;
    let _lastFocus = null;
    const GROUP_ORDER = ['動作', '領域', '分類', '排序', '時間'];

    function staticCommands() {
        const cmds = [];
        const push = (kind, icon, label, search, run) => cmds.push({ kind, icon, label, search, run });
        push('動作', '🔎', '聚焦搜尋框', '搜尋 search focus', () => { closePalette(); document.getElementById('searchInput')?.focus(); });
        push('動作', '🆕', '自上次造訪新增的論文', '新增 new since visit', () => { closePalette(); if (typeof showNewSinceVisit === 'function') showNewSinceVisit(); });
        push('動作', '⬇', '匯出收藏為 BibTeX', '匯出 export bibtex favorites', () => { closePalette(); if (typeof exportFavoritesBibtex === 'function') exportFavoritesBibtex(); });
        push('動作', '🔮', '切換語意搜尋', '語意 semantic toggle', () => { closePalette(); document.getElementById('semanticToggle')?.click(); });
        push('動作', '🔄', '切換研究領域…', '切換 領域 discipline switch', () => { closePalette(); if (typeof openDisciplinePicker === 'function') openDisciplinePicker({ closable: true }); });
        push('動作', '⬆', '回到頂部', '頂部 top scroll', () => { closePalette(); window.scrollTo({ top: 0, behavior: 'smooth' }); });

        const disc = window.DISCIPLINES || {};
        const cur = window.getActiveDiscipline?.()?.id;
        Object.keys(disc).forEach(id => {
            const d = disc[id];
            if (!d) return;
            push('領域', id === cur ? '📍' : '🧭', d.name + (d.nameEn ? `（${d.nameEn}）` : ''),
                [d.name, d.nameEn, d.brand, d.arxivCat, id].filter(Boolean).join(' '),
                () => { closePalette(); if (typeof selectDiscipline === 'function') selectDiscipline(id); });
        });

        document.querySelectorAll('.category-btn[data-filter], .topic-item[data-filter], .conf-item[data-filter]').forEach(btn => {
            if (btn.classList.contains('topic-group-btn') || btn.id === 'addCustomFeedBtn') return;
            const label = (typeof getLabelText === 'function' ? getLabelText(btn) : btn.textContent.trim());
            if (!label) return;
            push('分類', '📂', label, label + ' ' + (btn.dataset.filter || ''), () => { closePalette(); btn.click(); });
        });
        document.querySelectorAll('#sortSubmenu .sort-item[data-value]').forEach(item => {
            const v = item.dataset.value;
            const meta = (typeof getSortMeta === 'function') ? getSortMeta(v) : { label: v };
            push('排序', '↕', meta.label, `${meta.label} ${meta.title || ''} ${v} sort`, () => { closePalette(); item.click(); });
        });
        document.querySelectorAll('#timeRangeWrapper .time-range-btn[data-range]').forEach(btn => {
            const r = btn.dataset.range;
            const meta = (typeof getTimeRangeMeta === 'function') ? getTimeRangeMeta(r) : { label: r };
            push('時間', '🕑', meta.label, `${meta.label} ${meta.en || ''} ${r} time range`, () => { closePalette(); btn.click(); });
        });
        return cmds;
    }

    function fuzzyScore(hay, q) {
        hay = (hay || '').toLowerCase();
        const idx = hay.indexOf(q);
        if (idx >= 0) return 100 - Math.min(idx, 60);   // 子字串：越靠前分數越高
        let hi = 0, qi = 0, gaps = 0;                    // 子序列比對
        while (hi < hay.length && qi < q.length) {
            if (hay[hi] === q[qi]) qi++; else gaps++;
            hi++;
        }
        return qi === q.length ? 40 - Math.min(gaps, 39) : -1;
    }

    function webSearchCommand(q) {
        const semantic = !!window._SEMANTIC_ON;
        return {
            kind: '搜尋', icon: '🔎', label: `${semantic ? '語意' : '全網'}搜尋「${q}」`,
            run: () => {
                closePalette();
                const si = document.getElementById('searchInput');
                if (si) { si.value = q; si.classList.add('has-text'); }
                if (typeof pushRecentSearch === 'function') pushRecentSearch(q);
                if (semantic && typeof semanticSearchPapers === 'function') semanticSearchPapers(q);
                else if (typeof searchAllPapers === 'function') searchAllPapers(q);
                if (typeof writeUrlState === 'function') writeUrlState();
            },
        };
    }

    function appendItem(c) {
        const idx = _cmdItems.length;
        const li = document.createElement('li');
        li.className = 'cmd-item';
        li.setAttribute('role', 'option');
        li.innerHTML = `<span class="cmd-item-icon"></span><span class="cmd-item-label"></span>${c.kind ? '<span class="cmd-item-kind"></span>' : ''}`;
        li.querySelector('.cmd-item-icon').textContent = c.icon || '•';
        li.querySelector('.cmd-item-label').textContent = c.label;
        const kindEl = li.querySelector('.cmd-item-kind');
        if (kindEl) kindEl.textContent = c.kind;
        li.addEventListener('mousemove', () => { if (_selIdx !== idx) { _selIdx = idx; updateActive(); } });
        li.addEventListener('click', () => runIdx(idx));
        resultsEl.appendChild(li);
        _cmdItems.push(c);
    }

    function render(query) {
        const q = query.trim().toLowerCase();
        resultsEl.innerHTML = '';
        _cmdItems = [];
        const all = staticCommands();
        if (!q) {
            GROUP_ORDER.forEach(group => {
                const items = all.filter(c => c.kind === group);
                if (!items.length) return;
                const lbl = document.createElement('li');
                lbl.className = 'cmd-group-label';
                lbl.setAttribute('aria-hidden', 'true');
                lbl.textContent = group;
                resultsEl.appendChild(lbl);
                items.forEach(appendItem);
            });
        } else {
            appendItem(webSearchCommand(query.trim()));
            all.map(c => ({ c, s: fuzzyScore(c.search || c.label, q) }))
                .filter(x => x.s >= 0)
                .sort((a, b) => b.s - a.s)
                .slice(0, 12)
                .forEach(x => appendItem(x.c));
        }
        if (!_cmdItems.length) {
            const empty = document.createElement('li');
            empty.className = 'cmd-empty';
            empty.textContent = '沒有符合的指令';
            resultsEl.appendChild(empty);
        }
        _selIdx = 0;
        updateActive();
    }

    function updateActive() {
        resultsEl.querySelectorAll('.cmd-item').forEach((li, i) => {
            const on = i === _selIdx;
            li.classList.toggle('active', on);
            li.setAttribute('aria-selected', on ? 'true' : 'false');
            if (on) li.scrollIntoView({ block: 'nearest' });
        });
    }

    function runIdx(idx) {
        const c = _cmdItems[idx];
        if (c && typeof c.run === 'function') c.run();
    }

    function isOpen() { return !palette.classList.contains('hidden'); }
    function openPalette() {
        _lastFocus = document.activeElement;
        palette.classList.remove('hidden');
        input.value = '';
        render('');
        input.focus();
    }
    function closePalette() {
        if (!isOpen()) return;
        palette.classList.add('hidden');
        if (_lastFocus && typeof _lastFocus.focus === 'function') { try { _lastFocus.focus(); } catch (e) {} }
    }

    input.addEventListener('input', () => render(input.value));
    input.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowDown') { e.preventDefault(); e.stopPropagation(); if (_cmdItems.length) { _selIdx = (_selIdx + 1) % _cmdItems.length; updateActive(); } }
        else if (e.key === 'ArrowUp') { e.preventDefault(); e.stopPropagation(); if (_cmdItems.length) { _selIdx = (_selIdx - 1 + _cmdItems.length) % _cmdItems.length; updateActive(); } }
        else if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); runIdx(_selIdx); }
        else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closePalette(); }
    });
    palette.querySelector('.cmd-backdrop')?.addEventListener('click', closePalette);

    document.addEventListener('keydown', (e) => {
        if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
            e.preventDefault();
            e.stopPropagation();
            if (isOpen()) closePalette(); else openPalette();
        }
    }, true);   // capture：搶在卡片導覽等 keydown 前處理
})();
