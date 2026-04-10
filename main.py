from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.gzip import GZIPMiddleware
from pydantic import BaseModel
import xml.etree.ElementTree as ET
from datetime import datetime
from fastapi.responses import FileResponse
import os
import logging
from dotenv import load_dotenv
from huggingface_hub import InferenceClient

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
app.add_middleware(GZIPMiddleware, minimum_size=1000)

# 確保 static 目錄存在
os.makedirs("static", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")

import time
from typing import Dict, Any
from datetime import datetime, timedelta

import re

# 分開快取：7 天與 30 天各自獨立
caches: Dict[str, Any] = {
    "7":  {"timestamp": 0, "papers": []},
    "30": {"timestamp": 0, "papers": []},
}
CACHE_TTL = 3600  # 1 小時

@app.get("/api/papers")
def get_papers(max_results: int = 1000, days: int = 7):
    import urllib.request

    cache_key = "30" if days >= 30 else "7"
    cache = caches[cache_key]

    # 30 天模式需要更多結果（cs.CV 約 150 篇/天）
    if days >= 30 and max_results < 5000:
        max_results = 5000

    if time.time() - cache["timestamp"] < CACHE_TTL and len(cache["papers"]) > 0:
        return {"papers": cache["papers"]}

    url = (f'http://export.arxiv.org/api/query?search_query=cat:cs.CV'
           f'&sortBy=submittedDate&sortOrder=descending&max_results={max_results}')
    try:
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 DesktopDashboard/1.0'}
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            xml_data = response.read()
    except Exception as e:
        logger.error(f"arXiv API failed: {e}")
        if cache["papers"]:
            return {"papers": cache["papers"]}
        raise HTTPException(status_code=500, detail=str(e))

    root = ET.fromstring(xml_data)
    ns = {'atom': 'http://www.w3.org/2005/Atom', 'arxiv': 'http://arxiv.org/schemas/atom'}

    papers = []
    cutoff = datetime.now() - timedelta(days=days)

    for entry in root.findall('atom:entry', ns):
        title = entry.find('atom:title', ns).text.strip().replace('\n', ' ')
        title = re.sub(r'\(arXiv:.*?\)', '', title).strip()

        summary = entry.find('atom:summary', ns).text.strip().replace('\n', ' ')
        url_link = entry.find('atom:id', ns).text

        raw_published = entry.find('atom:published', ns).text
        try:
            pub_date = datetime.strptime(raw_published, '%Y-%m-%dT%H:%M:%SZ')
            if pub_date < cutoff:
                continue
            published_str = pub_date.strftime('%Y-%m-%d %H:%M')
        except ValueError:
            published_str = raw_published

        authors = [author.find('atom:name', ns).text for author in entry.findall('atom:author', ns)]

        papers.append({
            'title': title,
            'summary': summary,
            'url': url_link,
            'published': published_str,
            'authors': authors
        })

    cache["papers"] = papers
    cache["timestamp"] = time.time()

    return {"papers": papers}

@app.get("/api/search")
def search_papers(q: str, max_results: int = 50):
    import urllib.request
    import urllib.parse
    import xml.etree.ElementTree as ET
    import re

    if not q.strip():
        return {"papers": []}

    encoded_q = urllib.parse.quote(q.strip())
    url = f'http://export.arxiv.org/api/query?search_query=all:{encoded_q}&sortBy=relevance&sortOrder=descending&max_results={max_results}'
    try:
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 DesktopDashboard/1.0'}
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            xml_data = response.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    root = ET.fromstring(xml_data)
    ns = {'atom': 'http://www.w3.org/2005/Atom'}

    papers = []
    for entry in root.findall('atom:entry', ns):
        title_el = entry.find('atom:title', ns)
        summary_el = entry.find('atom:summary', ns)
        id_el = entry.find('atom:id', ns)
        published_el = entry.find('atom:published', ns)
        if title_el is None or id_el is None:
            continue

        title = re.sub(r'\(arXiv:.*?\)', '', title_el.text.strip().replace('\n', ' ')).strip()
        summary = summary_el.text.strip().replace('\n', ' ') if summary_el is not None else ''
        url_link = id_el.text
        authors = [a.find('atom:name', ns).text for a in entry.findall('atom:author', ns) if a.find('atom:name', ns) is not None]

        published_str = ''
        if published_el is not None:
            try:
                published_str = datetime.strptime(published_el.text, '%Y-%m-%dT%H:%M:%SZ').strftime('%Y-%m-%d %H:%M')
            except ValueError:
                published_str = published_el.text

        papers.append({'title': title, 'summary': summary, 'url': url_link, 'published': published_str, 'authors': authors})

    return {"papers": papers}

@app.get("/")
def read_root():
    return FileResponse("static/index.html")


# ── HuggingFace Gemma 4 中文摘要 ─────────────────────────────────
_hf_client: InferenceClient | None = None
_summary_cache: dict[str, str] = {}

HF_TOKEN    = os.environ.get("HF_TOKEN", "")
HF_MODEL    = "google/gemma-4-31B-it"
HF_PROVIDER = os.environ.get("HF_PROVIDER", None)  # e.g. "fireworks-ai", "together", "nebius"

SUMMARIZE_PROMPT = (
    "你是一位電腦視覺研究助理。請根據以下論文摘要，用繁體中文輸出結構化重點分析。"
    "嚴格按照以下格式輸出，每個項目用一到兩句話，不要多餘說明：\n\n"
    "🔍 核心問題：\n"
    "⚙️ 提出方法：\n"
    "🏆 主要貢獻：\n"
    "📊 實驗結果：\n\n"
    "論文摘要：\n"
)

class SummarizeRequest(BaseModel):
    arxiv_id: str
    abstract: str

@app.post("/api/summarize")
def summarize(req: SummarizeRequest):
    global _hf_client

    if not HF_TOKEN:
        raise HTTPException(status_code=503, detail="HF_TOKEN not set")

    if req.arxiv_id in _summary_cache:
        return {"summary": _summary_cache[req.arxiv_id]}

    if _hf_client is None:
        _hf_client = InferenceClient(token=HF_TOKEN, provider=HF_PROVIDER)

    try:
        text = req.abstract[:2000]
        resp = _hf_client.chat.completions.create(
            model=HF_MODEL,
            messages=[{"role": "user", "content": SUMMARIZE_PROMPT + text}],
            max_tokens=300,
            temperature=0.3,
        )
        summary = resp.choices[0].message.content.strip()
        _summary_cache[req.arxiv_id] = summary
        return {"summary": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
