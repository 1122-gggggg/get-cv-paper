let allPapers = [];
let currentCategory = 'all';

// ── 收藏夾系統 ─────────────────────────────────────────────────
const FAVORITES_KEY = 'visionary_favorites';
let favorites = new Set(JSON.parse(localStorage.getItem(FAVORITES_KEY) || '[]'));

function saveFavorites() {
    localStorage.setItem(FAVORITES_KEY, JSON.stringify([...favorites]));
}

function toggleFavorite(url, starEl) {
    if (favorites.has(url)) {
        favorites.delete(url);
        starEl.classList.remove('starred');
        starEl.title = '加入收藏';
    } else {
        favorites.add(url);
        starEl.classList.add('starred');
        starEl.title = '取消收藏';
    }
    saveFavorites();
    // 若目前在收藏夾視圖，移除後立即重新渲染
    if (currentCategory === 'favorites') filterPapers();
}

// ── 中文摘要翻譯系統 ──────────────────────────────────────────
const ZH_CACHE_KEY = 'zh_summary_v1';
let zhCache = {};
try { zhCache = JSON.parse(localStorage.getItem(ZH_CACHE_KEY) || '{}'); } catch(e) {}

const translateQueue = [];
let translateBusy = false;

async function processTranslateQueue() {
    if (translateBusy || translateQueue.length === 0) return;
    translateBusy = true;
    const { text, cacheKey, el } = translateQueue.shift();

    try {
        const url = `https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-TW&dt=t&q=${encodeURIComponent(text)}`;
        const res = await fetch(url);
        const data = await res.json();
        const translated = data[0].map(item => item[0]).join('');
        zhCache[cacheKey] = translated;
        try { localStorage.setItem(ZH_CACHE_KEY, JSON.stringify(zhCache)); } catch(e) {}
        el.textContent = translated;
        el.closest('.zh-summary-block').classList.remove('loading');
    } catch(e) {
        el.textContent = '（翻譯暫時無法取得）';
    }

    translateBusy = false;
    setTimeout(processTranslateQueue, 150); // 150ms 間隔防止頻率限制
}

function queueTranslation(summary, cacheKey, textEl) {
    if (zhCache[cacheKey]) {
        textEl.textContent = zhCache[cacheKey];
        textEl.closest('.zh-summary-block').classList.remove('loading');
        return;
    }
    // 截取前 600 字元避免請求過長
    const text = summary.length > 600 ? summary.substring(0, 600) + '...' : summary;
    translateQueue.push({ text, cacheKey, el: textEl });
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
const refreshBtn = document.getElementById('refreshBtn');
const noResults = document.getElementById('noResults');
let categoryBtns = document.querySelectorAll('.category-btn');

async function fetchPapers() {
    // Show loader
    papersGrid.classList.add('hidden');
    noResults.classList.add('hidden');
    loader.classList.remove('hidden');

    try {
        // 一次拿1000篇(大約一週的量)，後端已有快取機制
        const res = await fetch('/api/papers?max_results=1000');
        if (!res.ok) throw new Error('Failed to fetch data');
        const data = await res.json();
        allPapers = data.papers;
        filterPapers(); // Auto filter after fetch
    } catch (e) {
        console.error(e);
        alert('獲取論文失敗，請稍後再試。 Error: ' + e.message);
        loader.classList.add('hidden');
    }
}

function renderPapers(papers) {
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

    // 加入一個橫跨整行的資訊標題
    let themeTitle = "這週的相關文章";
    if (currentCategory === "all") themeTitle = "本週所有最新論文";
    else if (currentCategory === "top_conf") themeTitle = "本週入選三大頂會與權威期刊的高手論文";
    else if (currentCategory === "favorites") themeTitle = "⭐ 我的收藏論文";
    else themeTitle = `本週關於與 "${document.querySelector('.category-btn.active').innerText}" 相關的文章`;

    const countHeader = document.createElement('div');
    countHeader.style.gridColumn = '1 / -1';
    countHeader.style.padding = '1rem 0';
    countHeader.style.borderBottom = '1px solid var(--card-border)';
    countHeader.style.marginBottom = '1rem';
    countHeader.innerHTML = `<h3 style="color:#a855f7; font-size:1.4rem;">📚 ${themeTitle}：共找到 ${papers.length} 篇</h3>`;
    papersGrid.appendChild(countHeader);

    papers.forEach((paper, index) => {
        const card = document.createElement('div');
        card.className = 'paper-card';
        card.style.animationDelay = `${(index % 20) * 0.03}s`;
        card.dataset.summary = paper.summary;
        card.dataset.cacheKey = paper.url;

        const isStarred = favorites.has(paper.url);
        card.innerHTML = `
            <button class="star-btn${isStarred ? ' starred' : ''}" title="${isStarred ? '取消收藏' : '加入收藏'}">
                <svg xmlns="http://www.w3.org/2005/svg" width="18" height="18" viewBox="0 0 24 24" fill="${isStarred ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg>
            </button>
            <div>
                <h2 class="paper-title">${paper.title}</h2>
                <p class="paper-authors">${paper.authors.join(', ')}</p>
                <p class="paper-summary">${paper.summary}</p>
                <div class="zh-summary-block loading">
                    <span class="zh-label">🀄 重點摘要（中文）</span>
                    <span class="zh-summary-text">載入中文摘要…</span>
                </div>
            </div>
            <div class="paper-footer">
                <span class="paper-date">${paper.published}</span>
                <a href="${paper.url}" target="_blank" class="paper-link">
                    閱讀論文
                    <svg xmlns="http://www.w3.org/2005/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="7" y1="17" x2="17" y2="7"></line><polyline points="7 7 17 7 17 17"></polyline></svg>
                </a>
            </div>
        `;

        const starBtn = card.querySelector('.star-btn');
        starBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const svg = starBtn.querySelector('svg');
            toggleFavorite(paper.url, starBtn);
            svg.setAttribute('fill', favorites.has(paper.url) ? 'currentColor' : 'none');
        });

        papersGrid.appendChild(card);
        translateObserver.observe(card);
    });
}

function getHotScore(paper) {
    let score = 0;
    const txt = (paper.title + " " + paper.summary).toLowerCase();
    // 透過頂會、SOTA、流行關鍵字與團隊大小(作者數量)來推估熱門度
    const hotKeywords = ['cvpr', 'iccv', 'eccv', 'transformer', 'diffusion', '3d generation', 'gaussian', 'splatting', 'feature match', 'sota', 'state-of-the-art', 'benchmark', 'dataset'];
    hotKeywords.forEach(kw => { if (txt.includes(kw)) score += 15; });
    score += paper.authors.length * 2; 
    score += paper.title.length % 7; // 增加一點偽隨機性讓榜單看起來更動態
    return score;
}

function filterPapers() {
    const query = searchInput.value.toLowerCase().trim();
    const sortValue = document.getElementById('sortFilter').value;
    
    let filtered = allPapers.filter(paper => {
        // 文字搜尋框
        const matchesQuery = !query || 
            paper.title.toLowerCase().includes(query) || 
            paper.authors.some(author => author.toLowerCase().includes(query)) ||
            paper.summary.toLowerCase().includes(query);
            
        // 類別按鈕搜尋
        let matchesCategory = true;
        if (currentCategory === 'favorites') {
            matchesCategory = favorites.has(paper.url);
        } else if (currentCategory === 'top_conf') {
            const topConfs = ['cvpr', 'iccv', 'eccv', 'neurips', 'iclr', 'siggraph', 'tpami', 'siggraph asia', 'aaai', 'ijcai'];
            matchesCategory = topConfs.some(conf => 
                paper.title.toLowerCase().includes(conf) || 
                paper.summary.toLowerCase().includes(conf)
            );
        } else if (currentCategory !== 'all') {
            const cat = currentCategory.toLowerCase();
            matchesCategory = paper.title.toLowerCase().includes(cat) || 
                              paper.summary.toLowerCase().includes(cat);
        }
        
        return matchesQuery && matchesCategory;
    });

    // 根據排序選項處理
    if (sortValue === 'hot_week' || sortValue === 'hot_month') {
        filtered.sort((a, b) => getHotScore(b) - getHotScore(a));
    } else {
        // Default (latest) is what arXiv returns
    }
    
    renderPapers(filtered);
}

// Event Listeners
refreshBtn.addEventListener('click', fetchPapers);
searchInput.addEventListener('input', filterPapers);
document.getElementById('sortFilter').addEventListener('change', filterPapers);

function bindCategoryBtns() {
    categoryBtns = document.querySelectorAll('.category-btn');
    categoryBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            categoryBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentCategory = btn.dataset.filter;
            filterPapers();
        });
    });
}

// 自訂主題功能
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

function removeCustomTopic(btn, label) {
    if (currentCategory === label) {
        currentCategory = 'all';
        document.querySelector('.category-btn[data-filter="all"]').classList.add('active');
        filterPapers();
    }
    btn.remove();
    saveCustomTopics();
    bindCategoryBtns();
    showToast(`已移除「${label}」`);
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

    // 避免重複
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

    const labelSpan = document.createElement('span');
    labelSpan.textContent = label;

    const removeBtn = document.createElement('span');
    removeBtn.className = 'remove-topic';
    removeBtn.textContent = '×';
    removeBtn.title = '移除此主題';
    removeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        removeCustomTopic(btn, label);
    });

    // 右鍵刪除
    btn.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        removeCustomTopic(btn, label);
    });

    btn.appendChild(labelSpan);
    btn.appendChild(removeBtn);
    filtersDiv.insertBefore(btn, wrapper);

    if (save) saveCustomTopics();
    bindCategoryBtns();
}

// Initial Load
document.addEventListener('DOMContentLoaded', () => {
    loadCustomTopics();
    bindCategoryBtns();
    fetchPapers();

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
});
