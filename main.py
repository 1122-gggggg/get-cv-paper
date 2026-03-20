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

import time
from typing import Dict, Any
from datetime import datetime, timedelta

cache: Dict[str, Any] = {"timestamp": 0, "papers": []}
CACHE_TTL = 3600 # Cache for 1 hour to prevent 429 Too Many Requests

@app.get("/api/papers")
def get_papers(max_results: int = 1000):
    global cache
    import urllib.request
    import xml.etree.ElementTree as ET

    # Return cached data if valid
    if time.time() - cache["timestamp"] < CACHE_TTL and len(cache["papers"]) > 0:
        return {"papers": cache["papers"]}

    # Fetch 1000 papers which usually covers the entire week in cs.CV
    url = f'http://export.arxiv.org/api/query?search_query=cat:cs.CV&sortBy=submittedDate&sortOrder=descending&max_results={max_results}'
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 DesktopDashboard/1.0'}
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            xml_data = response.read()
    except Exception as e:
        if cache["papers"]: return {"papers": cache["papers"]}
        raise HTTPException(status_code=500, detail=str(e))

    root = ET.fromstring(xml_data)
    ns = {'atom': 'http://www.w3.org/2005/Atom', 'arxiv': 'http://arxiv.org/schemas/atom'}
    
    papers = []
    one_week_ago = datetime.now() - timedelta(days=7)

    for entry in root.findall('atom:entry', ns):
        title = entry.find('atom:title', ns).text.strip().replace('\n', ' ')
        
        # Clean up (arXiv:...) from titles
        import re
        title = re.sub(r'\(arXiv:.*?\)', '', title).strip()
        
        summary = entry.find('atom:summary', ns).text.strip().replace('\n', ' ')
        url_link = entry.find('atom:id', ns).text
        
        raw_published = entry.find('atom:published', ns).text
        try:
            pub_date = datetime.strptime(raw_published, '%Y-%m-%dT%H:%M:%SZ')
            # 確保只保留一週內的論文
            if pub_date < one_week_ago:
                continue
            published_str = pub_date.strftime('%Y-%m-%d %H:%M')
        except:
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

@app.get("/")
def read_root():
    return FileResponse("static/index.html")
