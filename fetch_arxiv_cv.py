import urllib.request
import xml.etree.ElementTree as ET

def fetch_latest_cv_papers(max_results=10):
    """
    從 arXiv API 抓取最新的 Computer Vision (cs.CV) 論文
    """
    url = f'http://export.arxiv.org/api/query?search_query=cat:cs.CV&sortBy=submittedDate&sortOrder=descending&max_results={max_results}'
    
    print(f"正在從 arXiv 取得最新 {max_results} 篇電腦視覺 (cs.CV) 論文...\n")
    try:
        response = urllib.request.urlopen(url)
        xml_data = response.read()
    except Exception as e:
        print(f"HTTP 請求失敗: {e}")
        return []

    root = ET.fromstring(xml_data)
    
    # arXiv XML 使用 namespace
    ns = {'atom': 'http://www.w3.org/2005/Atom', 'arxiv': 'http://arxiv.org/schemas/atom'}
    
    papers = []
    for entry in root.findall('atom:entry', ns):
        title = entry.find('atom:title', ns).text.strip().replace('\n', ' ')
        summary = entry.find('atom:summary', ns).text.strip().replace('\n', ' ')
        url = entry.find('atom:id', ns).text
        published = entry.find('atom:published', ns).text
        
        authors = [author.find('atom:name', ns).text for author in entry.findall('atom:author', ns)]
        
        papers.append({
            'title': title,
            'summary': summary,
            'url': url,
            'published': published,
            'authors': authors
        })
        
    return papers

if __name__ == "__main__":
    papers = fetch_latest_cv_papers(5)
    
    print("="*60)
    print(" 最新電腦視覺 / 計算機視覺論文 (來自 arXiv)")
    print("="*60 + "\n")
    
    for i, paper in enumerate(papers, 1):
        print(f"[{i}] {paper['title']}")
        print(f"作者群 : {', '.join(paper['authors'])}")
        print(f"發布時間: {paper['published']}")
        print(f"論文連結: {paper['url']}")
        print(f"摘要縮影: {paper['summary'][:150]}...\n")
        print("-" * 60)
