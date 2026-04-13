let allPapers = [];      // 7 天
let monthPapers = [];    // 30 天（懶加載）
let currentCategory = 'all';
let currentSortValue = 'latest';
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

// ── SVG 圖示常數（避免重複字串、加速 parse）─────────────────────
const ICONS = {
    unread:     `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle></svg>`,
    read:       `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>`,
    noteEmpty:  `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>`,
    noteFilled: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>`,
};

// ── 頂會關鍵字（hoisted，避免每次 filter 重建 array）────────────
const TOP_CONF_KEYWORDS = ['cvpr', 'iccv', 'eccv', 'neurips', 'iclr', 'icml', 'tpami', 'wacv', 'ijcv', 'ijcai'];

// ── 收藏夾系統 ─────────────────────────────────────────────────
const FAVORITES_KEY = 'visionary_favorites';
let favorites = new Set(JSON.parse(localStorage.getItem(FAVORITES_KEY) || '[]'));

// ── 釘選主題系統 ────────────────────────────────────────────────
const PINNED_TOPICS_KEY = 'visionary_pinned_topics';

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
    if (readSet.has(url)) {
        readSet.delete(url);
        card.classList.remove('is-read');
        readBtn.innerHTML = ICONS.unread + ' 未讀';
        readBtn.classList.remove('is-read');
        showToast('已標記為未讀');
    } else {
        readSet.add(url);
        card.classList.add('is-read');
        readBtn.innerHTML = ICONS.read + ' 已讀';
        readBtn.classList.add('is-read');
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
    if (text) {
        notesMap[url] = text;
        noteBtn.classList.add('has-note');
        noteBtn.innerHTML = ICONS.noteFilled + ' 筆記';
        showToast('筆記已儲存');
    } else {
        delete notesMap[url];
        noteBtn.classList.remove('has-note');
        noteBtn.innerHTML = ICONS.noteEmpty + ' 筆記';
        showToast('筆記已清除');
    }
    saveNotes();
    card.querySelector('.note-panel').classList.remove('open');
}


function saveFavorites() {
    localStorage.setItem(FAVORITES_KEY, JSON.stringify([...favorites]));
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

// ── 中文摘要系統（Gemma 4 31B）──────────────────────────────────
const ZH_CACHE_KEY = 'zh_summary_v3';
let zhCache = {};
try { zhCache = JSON.parse(localStorage.getItem(ZH_CACHE_KEY) || '{}'); } catch (e) { }

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
        body: JSON.stringify({ arxiv_id: arxivId || 'unknown', abstract }),
    });
    if (!res.ok) throw new Error('groq error ' + res.status);
    const data = await res.json();
    return data.summary;
}

async function fetchSummaryFallback(text) {
    const url = `https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-TW&dt=t&q=${encodeURIComponent(text)}`;
    const res = await fetch(url);
    const data = await res.json();
    return data[0].map(item => item[0]).join('');
}

async function processTranslateQueue() {
    if (translateBusy || translateQueue.length === 0) return;
    translateBusy = true;
    const { text, cacheKey, arxivId, el } = translateQueue.shift();

    try {
        const summary = await fetchSummaryFromGroq(text, arxivId);
        zhCache[cacheKey] = summary;
        scheduleSave(ZH_CACHE_KEY, () => zhCache);
        el.innerHTML = escapeHtml(summary).replace(/\n/g, '<br>');
        el.closest('.zh-summary-block').classList.remove('loading');
    } catch (e) {
        // fallback：Google Translate
        try {
            const short = text.length > 600 ? text.substring(0, 600) + '...' : text;
            const translated = await fetchSummaryFallback(short);
            zhCache[cacheKey] = translated;
            scheduleSave(ZH_CACHE_KEY, () => zhCache);
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
    if (zhCache[cacheKey]) {
        textEl.textContent = zhCache[cacheKey];
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
const LOADER_MESSAGES = [
    '正在自動為您抓取最新論文...',
    '連接 arXiv 資料庫中...',
    '整理本週 CV 論文，請稍候...',
    '快好了，正在處理論文資料...',
];

let loaderMsgInterval = null;

function startLoaderMessages() {
    const loaderP = loader.querySelector('p');
    if (!loaderP) return;
    let idx = 0;
    loaderP.textContent = LOADER_MESSAGES[0];
    loaderMsgInterval = setInterval(() => {
        idx = (idx + 1) % LOADER_MESSAGES.length;
        loaderP.textContent = LOADER_MESSAGES[idx];
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
        const res = await fetch('/api/papers?max_results=1000');
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

// ── 會議/期刊出處偵測 ──────────────────────────────────────────
const VENUE_PATTERNS = [
    { re: /\bCVPR\b/i, label: 'CVPR', color: '#3b82f6' },
    { re: /\bICCV\b/i, label: 'ICCV', color: '#6366f1' },
    { re: /\bECCV\b/i, label: 'ECCV', color: '#8b5cf6' },
    { re: /\bWACV\b/i, label: 'WACV', color: '#7c3aed' },
    { re: /\bNeurIPS\b/i, label: 'NeurIPS', color: '#059669' },
    { re: /\bICML\b/i, label: 'ICML', color: '#10b981' },
    { re: /\bICLR\b/i, label: 'ICLR', color: '#0d9488' },
    { re: /\bSIGGRAPH Asia\b/i, label: 'SIGGRAPH Asia', color: '#f59e0b' },
    { re: /\bSIGGRAPH\b/i, label: 'SIGGRAPH', color: '#d97706' },
    { re: /\bAAAI\b/i, label: 'AAAI', color: '#dc2626' },
    { re: /\bIJCAI\b/i, label: 'IJCAI', color: '#b91c1c' },
    { re: /\bACM MM\b/i, label: 'ACM MM', color: '#0891b2' },
    { re: /\bTPAMI\b/i, label: 'TPAMI', color: '#1d4ed8' },
    { re: /\bIJCV\b/i, label: 'IJCV', color: '#2563eb' },
    { re: /\bBMVC\b/i, label: 'BMVC', color: '#7c3aed' },
    { re: /\bACL\b/i, label: 'ACL', color: '#c2410c' },
    { re: /\bEMNLP\b/i, label: 'EMNLP', color: '#ea580c' },
];

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
            const svg = starBtn.querySelector('svg');
            toggleFavorite(url, starBtn);
            if (svg) svg.setAttribute('fill', favorites.has(url) ? 'currentColor' : 'none');
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

        const toggleBtn = e.target.closest('.summary-toggle-btn');
        if (toggleBtn && card.contains(toggleBtn)) {
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

function renderPapers(papers, customTitle) {
    _bindPapersGridDelegation();
    currentFilteredPapers = papers;
    lastCustomTitle = customTitle ?? null;
    papersGrid.innerHTML = '';

    if (papers.length === 0) {
        noResults.classList.remove('hidden');
        papersGrid.classList.add('hidden');
        loader.classList.add('hidden');
        return;
    }

    noResults.classList.add('hidden');
    papersGrid.classList.remove('hidden');
    loader.classList.add('hidden');

    const totalPages = Math.ceil(papers.length / PAPERS_PER_PAGE);
    // 確保 currentPage 在合法範圍
    if (currentPage > totalPages) currentPage = totalPages;

    // 標題
    let themeTitle;
    if (customTitle) {
        themeTitle = customTitle;
    } else if (currentCategory === "all") {
        themeTitle = "本週所有最新論文";
    } else if (currentCategory === "top_conf") {
        themeTitle = "本週入選三大頂會與權威期刊的高手論文";
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
    countHeader.innerHTML = `<span class="count-theme">${themeTitle}</span><span class="count-meta">共 ${papers.length} 篇　第 ${currentPage} / ${totalPages} 頁</span>`;
    papersGrid.appendChild(countHeader);

    // 當頁論文
    const start = (currentPage - 1) * PAPERS_PER_PAGE;
    const pagePapers = papers.slice(start, start + PAPERS_PER_PAGE);

    const frag = document.createDocumentFragment();
    pagePapers.forEach((paper, index) => {
        const card = document.createElement('div');
        card.className = 'paper-card';
        card.style.animationDelay = `${(index % 20) * 0.03}s`;
        card.dataset.summary = paper.summary;
        card.dataset.cacheKey = paper.url;
        card.dataset.url = paper.url;

        const isStarred = favorites.has(paper.url);
        const isRead = readSet.has(paper.url);
        const hasNote = !!notesMap[paper.url];
        const citCount = getCitationCount(paper.url);
        const inflCount = getInfluentialCitations(paper.url);
        const refCount  = getRefCount(paper.url);
        const citBadge  = citCount >= 0
            ? `<span class="citation-badge">📈 ${citCount} 引用</span>`
            : '';
        const inflBadge = inflCount > 0
            ? `<span class="influential-badge" title="高影響引用：被後續研究大量採用">💡 ${inflCount} 高影響</span>`
            : '';
        const refBadge  = refCount > 100
            ? `<span class="survey-badge" title="引用文獻數 ${refCount}，可能為綜述論文">📚 綜述</span>`
            : '';

        if (isRead) card.classList.add('is-read');

        const readIconHTML = isRead ? ICONS.read + ' 已讀' : ICONS.unread + ' 未讀';
        const noteIconHTML = hasNote ? ICONS.noteFilled + ' 筆記' : ICONS.noteEmpty + ' 筆記';

        // 偵測 GitHub 連結（修正 regex，不吞結尾標點）
        const pwcData = getPwcData(paper.url);
        const githubMatch = paper.summary.match(/https?:\/\/github\.com\/[\w\-]+\/[\w\-](?:[\w\-.]*[\w\-])?/i);
        const githubUrl = pwcData?.github_url || (githubMatch ? githubMatch[0] : null);
        const pwcStars  = pwcData?.stars || 0;
        const starsText = pwcStars > 0
            ? ` ⭐${pwcStars >= 1000 ? (pwcStars / 1000).toFixed(1) + 'k' : pwcStars}`
            : '';
        const githubBtnHTML = githubUrl
            ? `<a href="${escapeHtml(githubUrl)}" target="_blank" rel="noopener noreferrer" class="github-link-btn" title="查看程式碼">
                <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/></svg>
                Code${escapeHtml(starsText)}
               </a>`
            : '';

        const venue = detectVenue(paper);
        const venueBadge = venue
            ? `<span class="venue-badge" style="--venue-color:${escapeHtml(venue.color)}">${escapeHtml(venue.label)}</span>`
            : '';

        const safeTitle   = escapeHtml(paper.title);
        const safeSummary = escapeHtml(paper.summary);
        const safeUrl     = escapeHtml(paper.url);
        const safePublished = escapeHtml(paper.published);
        const authorsHTML = paper.authors.map(a =>
            `<button class="author-btn" data-author="${escapeHtml(a)}">${escapeHtml(a)}</button>`
        ).join('<span class="author-sep">, </span>');

        card.innerHTML = `
            <div class="read-ribbon"></div>
            <button class="star-btn${isStarred ? ' starred' : ''}" title="${isStarred ? '取消收藏' : '加入收藏'}">
                <svg xmlns="http://www.w3.org/2005/svg" width="18" height="18" viewBox="0 0 24 24" fill="${isStarred ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg>
            </button>
            <button class="read-btn${isRead ? ' is-read' : ''}" title="切換已讀狀態">${readIconHTML}</button>
            <div>
                ${venueBadge}
                <h2 class="paper-title"><a href="${safeUrl}" target="_blank" rel="noopener noreferrer" class="paper-title-link">${safeTitle}</a></h2>
                <p class="paper-authors">${authorsHTML}</p>
                <div class="summary-collapse-wrapper">
                    <p class="paper-summary collapsed">${safeSummary}</p>
                    <button class="summary-toggle-btn">展開原文摘要 ▾</button>
                </div>
                <div class="zh-summary-block loading">
                    <span class="zh-label">🤖 AI 重點分析（Gemma）</span>
                    <span class="zh-summary-text">分析中…</span>
                </div>
                <div class="note-panel">
                    <textarea class="note-textarea" placeholder="在此輸入個人筆記…（支援任意文字）"></textarea>
                    <div class="note-actions">
                        <button class="note-cancel-btn">取消</button>
                        <button class="note-save-btn">儲存筆記</button>
                    </div>
                </div>
            </div>
            <div class="paper-footer">
                <span class="paper-date">${safePublished}</span>
                ${citBadge}
                ${inflBadge}
                ${refBadge}
                ${githubBtnHTML}
                <button class="note-btn${hasNote ? ' has-note' : ''}" title="個人筆記">${noteIconHTML}</button>
                <a href="${safeUrl}" target="_blank" rel="noopener noreferrer" class="paper-link">
                    閱讀論文
                    <svg xmlns="http://www.w3.org/2005/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="7" y1="17" x2="17" y2="7"></line><polyline points="7 7 17 7 17 17"></polyline></svg>
                </a>
            </div>
        `;

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
let s2Cache = {};
try { s2Cache = JSON.parse(localStorage.getItem(S2_CACHE_KEY) || '{}'); } catch (e) { }

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
            scheduleSave(S2_CACHE_KEY, () => s2Cache);
        }
    } catch (e) { /* ignore */ }
    finish();
}

// ── Papers with Code ──────────────────────────────────────────
const PWC_CACHE_KEY = 'pwc_cache_v1';
const PWC_TTL = 24 * 3600 * 1000; // 24 小時
let pwcCache = {};
try { pwcCache = JSON.parse(localStorage.getItem(PWC_CACHE_KEY) || '{}'); } catch(e) {}

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
        scheduleSave(PWC_CACHE_KEY, () => pwcCache);
        return true;
    } catch (e) {
        return false;
    }
}

function applyFilter(pool, query) {
    const cat = currentCategory === 'all' || currentCategory === 'favorites' || currentCategory === 'top_conf' || CONF_FILTERS.has(currentCategory)
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
        const res = await fetch('/api/papers?days=30');
        if (!res.ok) throw new Error();
        monthPapers = indexPapers((await res.json()).papers);
    } catch (e) {
        monthPapers = allPapers; // fallback
    } finally {
        loader.classList.add('hidden');
        papersGrid.classList.remove('hidden');
    }
}

async function filterPapers() {
    currentPage = 1;
    const query = searchInput.value.toLowerCase().trim();
    const sortValue = currentSortValue;

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
    }

    renderPapers(filtered, titleSuffix ? (sortValue === 'citations' ? `引用最多 ${titleSuffix}` : `熱門論文 ${titleSuffix}`) : null);
}

async function searchAllPapers(query) {
    currentPage = 1;
    papersGrid.classList.add('hidden');
    noResults.classList.add('hidden');
    loader.classList.remove('hidden');
    try {
        const res = await fetch(`/api/search?q=${encodeURIComponent(query)}&max_results=50`);
        if (!res.ok) throw new Error('Search failed');
        const data = await res.json();
        renderPapers(indexPapers(data.papers), `全網搜尋「${escapeHtml(query)}」`);
    } catch (e) {
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

// ── 搜尋推薦詞 ───────────────────────────────────────────────
const SEARCH_SUGGESTIONS = [
    'NeRF', 'Gaussian Splatting', 'Depth Estimation', 'Segmentation',
    'Object Detection', 'SLAM', 'Feature Matching', 'Diffusion Model',
    'Transformer', 'Vision-Language', 'Pose Estimation', '3D Reconstruction',
    'Super Resolution', 'Video Understanding', 'Optical Flow',
    'Semantic Segmentation', 'Point Cloud', 'Medical Imaging',
    'Self-Supervised', 'Multimodal', 'CVPR 2024', 'NeurIPS 2024',
];

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
const DELETED_BUILTIN_KEY = 'visionary_deleted_builtins';
const RENAMED_BUILTIN_KEY = 'visionary_renamed_builtins';

function loadDeletedBuiltins() {
    try { return new Set(JSON.parse(localStorage.getItem(DELETED_BUILTIN_KEY) || '[]')); } catch (e) { return new Set(); }
}
function saveDeletedBuiltins(s) { localStorage.setItem(DELETED_BUILTIN_KEY, JSON.stringify([...s])); }
function loadRenamedBuiltins() {
    try { return JSON.parse(localStorage.getItem(RENAMED_BUILTIN_KEY) || '{}'); } catch (e) { return {}; }
}
function saveRenamedBuiltins(map) { localStorage.setItem(RENAMED_BUILTIN_KEY, JSON.stringify(map)); }

// 特殊 filter：只改顯示名，不改 data-filter（篩選邏輯依賴它）
const CONF_FILTERS = new Map([
    ['conf_cvpr', 'cvpr'],
    ['conf_iccv', 'iccv'],
    ['conf_eccv', 'eccv'],
    ['conf_neurips', 'neurips'],
    ['conf_iclr', 'iclr'],
    ['conf_icml', 'icml'],
    ['conf_tpami', 'tpami'],
    ['conf_wacv', 'wacv'],
]);
const SPECIAL_FILTERS = new Set(['all', 'favorites', 'top_conf', ...CONF_FILTERS.keys()]);

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
    localStorage.setItem('visionary_last_category', filter);
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
const CUSTOM_TOPICS_KEY = 'visionary_custom_topics';

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
    applyBuiltinModifications();
    loadPinnedTopics();
    loadCustomTopics();
    bindCategoryBtns();

    // 恢復上次的分類
    const savedCategory = localStorage.getItem('visionary_last_category');
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

    // ── 分類標籤左右箭頭 ──
    const filterScroll = document.querySelector('.category-filters');
    const arrowLeft    = document.getElementById('filterArrowLeft');
    const arrowRight   = document.getElementById('filterArrowRight');
    const SCROLL_STEP  = 200;

    function updateFilterArrows() {
        if (!filterScroll) return;
        arrowLeft.classList.toggle('hidden-arrow', filterScroll.scrollLeft <= 0);
        arrowRight.classList.toggle('hidden-arrow',
            filterScroll.scrollLeft + filterScroll.clientWidth >= filterScroll.scrollWidth - 1);
    }

    if (filterScroll && arrowLeft && arrowRight) {
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

    const SORT_LABELS = { latest: '本日最新', hot_week: '本週熱門', hot_month: '本月熱門', citations: '引用最多' };

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
        return `@article{${key},\n  title={${title}},\n  author={${authorsStr}},\n  year={${year}},\n  eprint={${arxivId}},\n  archivePrefix={arXiv},\n  primaryClass={cs.CV},\n  url={${p.url}}\n}`;
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

// ── 鍵盤快捷鍵說明按鈕 ────────────────────────────────────────
document.getElementById('kbdHintBtn')?.addEventListener('click', () => {
    document.getElementById('kbdHint')?.classList.toggle('visible');
});
