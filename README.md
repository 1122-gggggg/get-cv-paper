# get-cv-paper (Scholarly)

> 每日追蹤 arXiv + OpenReview + Hugging Face Daily 論文，橫跨 50+ 個學科領域，並整合引用數據與 GitHub 程式碼開源訊號。

🔗 **線上展示 (Demo)**：[https://get-cv-paper.onrender.com](https://get-cv-paper.onrender.com)

---

## 快速開始 (Quick Start)

### 系統需求
- **Python**: 3.12+
- **Node.js**: 20+ (用於靜態資產壓縮與前端測試)

### 安裝依賴
```bash
# 方式 1: 使用 uv (推薦)
uv sync

# 方式 2: 使用 pip 與 npm
pip install -r requirements.txt
pip install -r requirements-dev.txt   # 開發與測試依賴
npm ci
```

### 環境變數設定 (Environment Variables)
所有變數皆為**選填 (Optional)**，系統具備完整的預設值與容錯機制：

| 變數名稱 | 預設值 | 說明 |
| :--- | :--- | :--- |
| `CACHE_DIR` | `.cache` | 本地快取與 SQLite 儲存目錄 |
| `GITHUB_TOKEN` | *空* | GitHub Personal Access Token (提升 API 配額至 5,000 req/hr) |
| `METRICS_KEY` | *空* | 保護 `/api/metrics` 與 `/metrics` 端點的 Bearer Token |
| `SENTRY_DSN` | *空* | Sentry 錯誤追蹤 DSN |
| `BETTERSTACK_TOKEN` | *空* | BetterStack / Logtail 日誌外送 Token |
| `OAI_HARVEST_ENABLED` | `1` | 是否啟用 arXiv OAI-PMH 背景收割 (`1` 為啟用，`0` 為停用) |
| `OAI_HARVEST_SETS` | `cs` | OAI-PMH 收割學科集合 (逗號分隔，如 `cs,stat`) |
| `HF_TOKEN` | *空* | Hugging Face API Token (用於語意搜尋模型調用) |

### 本地啟動服務
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```
啟動後於瀏覽器開啟 [http://127.0.0.1:8000](http://127.0.0.1:8000)。

---

## 使用說明 (Usage)

- **切換研究領域**：點擊側邊欄「切換研究領域」，支援 Computer Vision (`cv`)、NLP (`nlp`)、Machine Learning (`ml`)、AI (`ai`) 等 50+ 學門與多領域合併檢視。
- **時間範圍 (Time Range)**：
  - `day`（24 小時內）、`week`（近 7 天）、`month`（近 30 天）、`quarter`（近 90 天）。
- **排序維度 (Sorting)**：
  - 🔥 `hot`（熱與新）：結合新鮮度衰減與社群熱度的綜合評分。
  - ⚡ `latest`（最新）：依發布時間降冪排列。
  - 🔥 `popularity`（熱門度）：綜合熱門權重（HF upvotes × 3 + Citations × 2 + Stars + Views）。
  - 📊 `citations`（引用度）：Semantic Scholar / OpenAlex 總引用次數。
  - 💎 `value`（價值分數）：結合引用、開源星數與頂會評審之複合評分。
  - 🚀 `velocity`（引用速度）：論文發布後的新增引用增長速率。
  - 🤗 `hf`（HF 熱度）：Hugging Face Daily Papers 社群 Upvotes 數。
  - 🔥 `hot3m`（近三月熱門）：近 90 天內高引用論文。
- **搜尋模式 (Search)**：
  - **字面搜尋**：即時匹配標題、摘要與作者名稱。
  - **🧠 語意搜尋**：基於向量 Embedding 進行語意關聯性召回，支援跨學科搜尋。
- **精確篩選列 (Metrics Filter Bar)**：
  - 可針對「引用次數 (Citations)」、「觀看次數 (Views)」、「GitHub 星數 (Stars)」、「HF Upvotes」設定數值區間（Min / Max），並支援勾選「有程式碼 (Has Code)」。
  - 篩選由後端即時計算，狀態會自動雙向同步至 URL Query 參數，便於直接複製分享連結。

---

## API 速查 (API Reference)

### 論文查詢與串流端點
- `GET /api/papers`：單一領域論文列表。
- `GET /api/feed`：多領域合併論文串流（跨學科去重）。

#### Query 參數列表

| 參數 | 類型 | 適用端點 | 預設值 | 說明 |
| :--- | :--- | :--- | :--- | :--- |
| `discipline` | string | `/api/papers` | `cv` | 學科代碼 (如 `nlp`, `ml`, `robotics`) |
| `fields` | string | `/api/feed` | *無* | 逗號分隔多學科代碼 (最多 8 個) |
| `days` | int | 兩者皆可 | `7` | 回溯天數 (1 ~ 90) |
| `max_results` | int | 兩者皆可 | `1000` / `300` | 回傳最大論文筆數 |
| `sort` | string | 兩者皆可 | `latest` | 排序 (`latest`, `citations`, `hf`, `stars`, `views`, `popularity`, `reviews`) |
| `q` | string | 兩者皆可 | *空* | 關鍵字搜尋字串 |
| `topic` | string | `/api/papers` | *空* | 子主題過濾關鍵字 |
| `min_citations` / `max_citations` | int | 兩者皆可 | `null` | 引用次數過濾區間 |
| `min_views` / `max_views` | int | 兩者皆可 | `null` | 點閱次數過濾區間 |
| `min_stars` / `max_stars` | int | 兩者皆可 | `null` | GitHub Stars 過濾區間 |
| `min_hf` / `max_hf` | int | 兩者皆可 | `null` | Hugging Face Upvotes 過濾區間 |
| `has_code` | bool | 兩者皆可 | `false` | 是否僅保留含 GitHub 程式碼連結的論文 |

#### 快取與條件請求 (Caching & ETag)
- 端點回應支援 `ETag` / `If-None-Match` 機制，快取未變更時回傳 `304 Not Modified`。
- 預設附帶 `Cache-Control: public, max-age=60, stale-while-revalidate=60`，底層採用 Single-Flight 機制，高並發請求下僅會觸發單一上游資料建置。

---

## 部署說明 (Deployment)

### 1. Render Blueprint (自動化部署)
專案內建 `render.yaml`，可在 Render 後台透過 **New + Blueprint** 連接 GitHub 倉庫，實現免費用量自動部署，並自帶 `/api/health` 健康檢查探針。

### 2. Docker 本機驗證
```bash
# 建置 Docker 映像檔
docker build -t scholarly .

# 啟動容器
docker run -d -p 8000:8000 --name scholarly scholarly

# 驗證健康狀態
curl http://127.0.0.1:8000/api/health
# 回傳: {"ok":true,"t":1725148800}
```

---

## 開發與測試 (Development & Testing)

```bash
# Python 程式碼檢查與型別標註檢驗
ruff check .
mypy . --ignore-missing-imports

# Python 單元測試與覆蓋率驗證
pytest -q --cov --cov-fail-under=55

# 前端程式碼風格檢查與測試
npm run lint
npm test
```

---

## 授權與貢獻 (License & Contribution)

- **License**: MIT License
- **貢獻指南**: 歡迎提交 Issue 反饋問題或發起 Pull Request 共同改進！
