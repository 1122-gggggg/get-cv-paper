let allPapers = [];
let currentCategory = 'all';

const papersGrid = document.getElementById('papersGrid');
const loader = document.getElementById('loader');
const searchInput = document.getElementById('searchInput');
const refreshBtn = document.getElementById('refreshBtn');
const noResults = document.getElementById('noResults');
const categoryBtns = document.querySelectorAll('.category-btn');

async function fetchPapers() {
    // Show loader
    papersGrid.classList.add('hidden');
    noResults.classList.add('hidden');
    loader.classList.remove('hidden');

    try {
        // 取得多一點論文才能在前端分類篩選
        const res = await fetch('/api/papers?max_results=80');
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

    papers.forEach((paper, index) => {
        const card = document.createElement('div');
        card.className = 'paper-card';
        // Remove animation delay so it doesn't staggered slow down on quick filter changes
        card.style.animationDelay = `${(index % 20) * 0.03}s`; 
        
        card.innerHTML = `
            <div>
                <h2 class="paper-title">${paper.title}</h2>
                <p class="paper-authors">${paper.authors.join(', ')}</p>
                <p class="paper-summary">${paper.summary}</p>
            </div>
            <div class="paper-footer">
                <span class="paper-date">${paper.published}</span>
                <a href="${paper.url}" target="_blank" class="paper-link">
                    閱讀論文
                    <svg xmlns="http://www.w3.org/2005/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="7" y1="17" x2="17" y2="7"></line><polyline points="7 7 17 7 17 17"></polyline></svg>
                </a>
            </div>
        `;
        papersGrid.appendChild(card);
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
        if (currentCategory === 'top_conf') {
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

// 綁定所有分類按鈕事件
categoryBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        // 移除其他 active
        categoryBtns.forEach(b => b.classList.remove('active'));
        // 標記目前的按鈕為 active
        btn.classList.add('active');
        // 更新當前分類
        currentCategory = btn.dataset.filter;
        // 觸發篩選
        filterPapers();
    });
});

// Initial Load
document.addEventListener('DOMContentLoaded', fetchPapers);
