from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from fastapi.responses import FileResponse
import os

app = FastAPI()

# 確保 static 目錄存在
os.makedirs("static", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/api/papers")
def get_papers(max_results: int = 30):
    import feedparser
    import re
    from datetime import datetime
    
    url = 'https://export.arxiv.org/rss/cs.CV'
    try:
        feed = feedparser.parse(url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
    papers = []
    # If feed is empty or failed
    if not feed.entries:
        raise HTTPException(status_code=500, detail="Failed to fetch RSS feed or feed is empty.")

    for i, entry in enumerate(feed.entries):
        if i >= max_results:
            break
            
        # 標題通常會有 "(arXiv:xxxx.xxxxx [cs.CV])"，我們稍微清理一下
        title = entry.get('title', 'Unknown Title')
        title = re.sub(r'\(arXiv:.*?\)', '', title).strip()
        
        link = entry.get('link', '')
        
        # RSS 摘要會被 <p> 包裝
        raw_desc = entry.get('description', '')
        summary = re.sub(r'<[^>]+>', '', raw_desc).strip()
        
        # 作者也可能被 <a> 包裝
        raw_creator = entry.get('creator', entry.get('author', 'Unknown Author'))
        clean_authors_str = re.sub(r'<[^>]+>', '', raw_creator).strip()
        authors = [a.strip() for a in clean_authors_str.split(',') if a.strip()]
        
        # 日期 (RSS 通常沒有各篇的時間，只共用 feed 更新時間，所以用當天代替)
        published_str = datetime.now().strftime('%Y-%m-%d %H:%M')
        
        papers.append({
            'title': title,
            'summary': summary,
            'url': link,
            'published': published_str,
            'authors': authors
        })
        
    return {"papers": papers}

@app.get("/")
def read_root():
    return FileResponse("static/index.html")
