"""arXiv / OpenAlex / Crossref / PubMed / bioRxiv 多源學科映射表 + 取用器。

每個 discipline 至少有 `cat`(arXiv 主分類)，並可選擇性提供:
- `cats`: arXiv 多分類列表(如 ml = [cs.LG, stat.ML]),以 OR 查詢擴大召回;省略則等同 [cat]
- `openalex_concept`: OpenAlex Concept ID (Cxxxxxxxx)
- `crossref_subject`: Crossref subject code (str, 4 digits)
- `pubmed_mesh`: PubMed MeSH 主題詞 (str)
- `biorxiv`: 是否打 bioRxiv/medRxiv (bool, 預設 False)
- `arxiv_native`: True 表 arXiv 真有此分類; False 表只是借用最近的 cat,
                  前端會顯示「arXiv 沒此學科專屬分類」的提示

Rule: arXiv 沒涵蓋的學科 (人文社科、商管、純醫學),
      `arxiv_native=False` 並標記主要靠哪個外部來源。
"""
from __future__ import annotations

# 預設 fallback
_FALLBACK_CY = "cs.CY"  # CS Computers & Society - 用於借用時的 last resort

DISCIPLINES: dict[str, dict] = {
    # ── CS 主領域 (arXiv native) ────────────────────────────────
    "cv":          {"cat": "cs.CV",   "name": "電腦視覺",        "role": "電腦視覺研究助理",   "arxiv_native": True},
    "nlp":         {"cat": "cs.CL",   "name": "自然語言處理",    "role": "自然語言處理研究助理","arxiv_native": True},
    "ml":          {"cat": "cs.LG",   "name": "機器學習",        "role": "機器學習研究助理",   "arxiv_native": True, "cats": ["cs.LG", "stat.ML"]},
    "ai":          {"cat": "cs.AI",   "name": "人工智慧",        "role": "人工智慧研究助理",   "arxiv_native": True, "cats": ["cs.AI", "cs.MA", "cs.NE"]},
    "robotics":    {"cat": "cs.RO",   "name": "機器人學",        "role": "機器人學研究助理",   "arxiv_native": True, "cats": ["cs.RO", "eess.SY"]},
    "graphics":    {"cat": "cs.GR",   "name": "電腦繪圖",        "role": "電腦繪圖研究助理",   "arxiv_native": True},
    "security":    {"cat": "cs.CR",   "name": "資訊安全",        "role": "資訊安全研究助理",   "arxiv_native": True},
    "systems":     {"cat": "cs.OS",   "name": "系統與架構",      "role": "系統研究助理",       "arxiv_native": True, "cats": ["cs.OS", "cs.AR", "cs.DC"]},
    "db":          {"cat": "cs.DB",   "name": "資料庫",          "role": "資料庫研究助理",     "arxiv_native": True},
    "hci":         {"cat": "cs.HC",   "name": "人機互動",        "role": "人機互動研究助理",   "arxiv_native": True},
    "ir":          {"cat": "cs.IR",   "name": "資訊檢索與推薦",  "role": "資訊檢索研究助理",   "arxiv_native": True},
    "softeng":     {"cat": "cs.SE",   "name": "軟體工程",        "role": "軟體工程研究助理",   "arxiv_native": True},
    "networks":    {"cat": "cs.NI",   "name": "網路工程",        "role": "網路研究助理",       "arxiv_native": True},
    "distsys":     {"cat": "cs.DC",   "name": "分散式系統",      "role": "分散式系統研究助理", "arxiv_native": True},
    "infotheory":  {"cat": "cs.IT",   "name": "資訊理論",        "role": "資訊理論研究助理",   "arxiv_native": True},
    "multimedia":  {"cat": "cs.MM",   "name": "多媒體",          "role": "多媒體研究助理",     "arxiv_native": True, "cats": ["cs.MM", "cs.SD"]},
    "proglang":    {"cat": "cs.PL",   "name": "程式語言",        "role": "程式語言研究助理",   "arxiv_native": True},
    "complexity":  {"cat": "cs.CC",   "name": "計算複雜度",      "role": "計算理論研究助理",   "arxiv_native": True},
    "logic":       {"cat": "cs.LO",   "name": "計算邏輯",        "role": "計算邏輯研究助理",   "arxiv_native": True},
    "gametheory":  {"cat": "cs.GT",   "name": "賽局論",          "role": "賽局論研究助理",     "arxiv_native": True},
    "datastruct":  {"cat": "cs.DS",   "name": "資料結構與演算法","role": "演算法研究助理",     "arxiv_native": True},
    "datasci":     {"cat": "stat.ML", "name": "資料科學",        "role": "資料科學研究助理",   "arxiv_native": True, "cats": ["stat.ML", "cs.LG", "stat.ME"]},
    "socialnet":   {"cat": "cs.SI",   "name": "社群網路分析",    "role": "社群網路研究助理",   "arxiv_native": True, "cats": ["cs.SI", "physics.soc-ph"]},
    "numerical":   {"cat": "cs.NA",   "name": "數值分析",        "role": "數值分析研究助理",   "arxiv_native": True},
    # 新增 CS 細分
    "fl":          {"cat": "cs.FL",   "name": "形式語言與自動機","role": "形式語言研究助理",   "arxiv_native": True},
    "multiagent":  {"cat": "cs.MA",   "name": "多 Agent 系統",   "role": "多 Agent 研究助理",   "arxiv_native": True},
    "symbolic":    {"cat": "cs.SC",   "name": "符號計算",        "role": "符號計算研究助理",   "arxiv_native": True},
    "performance": {"cat": "cs.PF",   "name": "效能分析",        "role": "效能分析研究助理",   "arxiv_native": True},
    "architecture_cs":{"cat": "cs.AR","name": "電腦架構",        "role": "電腦架構研究助理",   "arxiv_native": True},

    # ── 數學 (arXiv native) ─────────────────────────────────────
    "math":        {"cat": "math.OC", "name": "數學",            "role": "數學研究助理",       "arxiv_native": True},
    "probability": {"cat": "math.PR", "name": "機率論",          "role": "機率論研究助理",     "arxiv_native": True},
    "combinatorics":{"cat": "math.CO","name": "組合數學",        "role": "組合數學研究助理",   "arxiv_native": True},
    "numbertheory":{"cat": "math.NT", "name": "數論",            "role": "數論研究助理",       "arxiv_native": True},
    "algebra":     {"cat": "math.AG", "name": "代數幾何",        "role": "代數幾何研究助理",   "arxiv_native": True},
    "topology":    {"cat": "math.AT", "name": "拓樸學",          "role": "拓樸學研究助理",     "arxiv_native": True},
    "diffgeom":    {"cat": "math.DG", "name": "微分幾何",        "role": "微分幾何研究助理",   "arxiv_native": True},
    "analysis":    {"cat": "math.AP", "name": "分析與偏微方程",  "role": "數學分析研究助理",   "arxiv_native": True},

    # ── 統計 ─────────────────────────────────────────────────
    "stats":       {"cat": "stat.ML", "name": "統計學",          "role": "統計學研究助理",     "arxiv_native": True},

    # ── 物理 (arXiv native) ─────────────────────────────────────
    "physics":     {"cat": "cond-mat.stat-mech",   "name": "物理",         "role": "物理研究助理",       "arxiv_native": True},
    "astro":       {"cat": "astro-ph.GA",          "name": "天文物理",     "role": "天文物理研究助理",   "arxiv_native": True},
    "quantum":     {"cat": "quant-ph",             "name": "量子物理",     "role": "量子物理研究助理",   "arxiv_native": True},
    "particle":    {"cat": "hep-ph",               "name": "粒子物理",     "role": "粒子物理研究助理",   "arxiv_native": True},
    "hepth":       {"cat": "hep-th",               "name": "高能物理理論", "role": "高能理論研究助理",   "arxiv_native": True},
    "relativity":  {"cat": "gr-qc",                "name": "廣義相對論",   "role": "廣義相對論研究助理", "arxiv_native": True},
    "nucphys":     {"cat": "nucl-th",              "name": "核物理理論",   "role": "核物理研究助理",     "arxiv_native": True},
    "plasma":      {"cat": "physics.plasm-ph",     "name": "電漿物理",     "role": "電漿物理研究助理",   "arxiv_native": True},
    "optics":      {"cat": "physics.optics",       "name": "光學",         "role": "光學研究助理",       "arxiv_native": True},
    "biophysics":  {"cat": "physics.bio-ph",       "name": "生物物理",     "role": "生物物理研究助理",   "arxiv_native": True},
    "chem":        {"cat": "physics.chem-ph",      "name": "化學",         "role": "化學研究助理",       "arxiv_native": True,  "chemrxiv": True},
    "medphys":     {"cat": "physics.med-ph",       "name": "醫學物理",     "role": "醫學物理研究助理",   "arxiv_native": True},
    "earth":       {"cat": "physics.geo-ph",       "name": "地球科學",     "role": "地球科學研究助理",   "arxiv_native": True},
    "climate":     {"cat": "physics.ao-ph",        "name": "氣候與大氣",   "role": "氣候科學研究助理",   "arxiv_native": True},
    "ocean":       {"cat": "physics.ao-ph",        "name": "海洋科學",     "role": "海洋科學研究助理",   "arxiv_native": True},
    "envsci":      {"cat": "physics.geo-ph",       "name": "環境科學",     "role": "環境科學研究助理",   "arxiv_native": True},
    "materials":   {"cat": "cond-mat.mtrl-sci",    "name": "材料科學",     "role": "材料科學研究助理",   "arxiv_native": True},
    "mecheng":     {"cat": "physics.flu-dyn",      "name": "機械與流體",   "role": "機械工程研究助理",   "arxiv_native": True},
    "aero":        {"cat": "physics.flu-dyn",      "name": "航太工程",     "role": "航太工程研究助理",   "arxiv_native": True},
    "nuclear":     {"cat": "physics.ins-det",      "name": "核能工程",     "role": "核能工程研究助理",   "arxiv_native": True},

    # ── 生物 / 生醫 (arXiv 部份 native, 補 bioRxiv/PubMed) ──────
    "bio":         {"cat": "q-bio.BM",  "name": "生物",         "role": "生物學研究助理",     "arxiv_native": True,  "biorxiv": True},
    "neuro":       {"cat": "q-bio.NC",  "name": "神經科學",     "role": "神經科學研究助理",   "arxiv_native": True,  "biorxiv": True},
    "genomics":    {"cat": "q-bio.GN",  "name": "基因體學",     "role": "基因體學研究助理",   "arxiv_native": True,  "biorxiv": True},
    "molbio":      {"cat": "q-bio.MN",  "name": "分子生物",     "role": "分子生物研究助理",   "arxiv_native": True,  "biorxiv": True},
    "cellbio":     {"cat": "q-bio.SC",  "name": "細胞生物",     "role": "細胞生物研究助理",   "arxiv_native": True,  "biorxiv": True},
    "bioinfo":     {"cat": "q-bio.QM",  "name": "生物資訊",     "role": "生物資訊研究助理",   "arxiv_native": True,  "biorxiv": True},
    "biomed":      {"cat": "q-bio.TO",  "name": "生醫工程",     "role": "生醫工程研究助理",   "arxiv_native": True,  "biorxiv": True, "pubmed_mesh": "Biomedical Engineering"},
    "medimg":      {"cat": "eess.IV",   "name": "醫療影像",     "role": "醫療影像研究助理",   "arxiv_native": True,  "cats": ["eess.IV", "cs.CV"]},
    "epidem":      {"cat": "q-bio.PE",  "name": "流行病學",     "role": "流行病學研究助理",   "arxiv_native": True,  "biorxiv": True, "pubmed_mesh": "Epidemiology"},
    "neuroai":     {"cat": "q-bio.NC",  "name": "認知與神經 AI","role": "認知科學研究助理",   "arxiv_native": True,  "biorxiv": True},
    "pubhealth":   {"cat": "q-bio.PE",  "name": "公衛",         "role": "公衛研究助理",       "arxiv_native": True,  "biorxiv": True, "pubmed_mesh": "Public Health"},
    "bioeng":      {"cat": "q-bio.TO",  "name": "生物工程",     "role": "生物工程研究助理",   "arxiv_native": True,  "biorxiv": True},
    # 純醫學/藥學 — arXiv 沒覆蓋, 主要靠 PubMed + bioRxiv/medRxiv
    "pharma":      {"cat": "q-bio.BM",  "name": "藥學",         "role": "藥學研究助理",       "arxiv_native": False, "biorxiv": True, "medrxiv": True, "pubmed_mesh": "Pharmacology"},
    "nursing":     {"cat": "q-bio.QM",  "name": "護理學",       "role": "護理研究助理",       "arxiv_native": False, "medrxiv": True, "pubmed_mesh": "Nursing"},
    "dentistry":   {"cat": "q-bio.QM",  "name": "牙醫學",       "role": "牙醫研究助理",       "arxiv_native": False, "medrxiv": True, "pubmed_mesh": "Dentistry"},
    "veterinary":  {"cat": "q-bio.TO",  "name": "獸醫學",       "role": "獸醫研究助理",       "arxiv_native": False, "biorxiv": True, "pubmed_mesh": "Veterinary Medicine"},
    "therapy":     {"cat": "q-bio.NC",  "name": "復健治療",     "role": "復健治療研究助理",   "arxiv_native": False, "medrxiv": True, "pubmed_mesh": "Rehabilitation"},
    "audiology":   {"cat": "eess.AS",   "name": "聽力與語言治療","role": "聽語研究助理",      "arxiv_native": False, "medrxiv": True, "pubmed_mesh": "Audiology"},
    "gerontology": {"cat": "q-bio.PE",  "name": "老人學",       "role": "老人學研究助理",     "arxiv_native": False, "medrxiv": True, "pubmed_mesh": "Geriatrics"},
    "foodsci":     {"cat": "q-bio.QM",  "name": "食品科學",     "role": "食品科學研究助理",   "arxiv_native": False, "biorxiv": True, "pubmed_mesh": "Food Science"},
    "sports":      {"cat": "q-bio.QM",  "name": "運動科學",     "role": "運動科學研究助理",   "arxiv_native": False, "medrxiv": True, "pubmed_mesh": "Sports Medicine"},
    "agri":        {"cat": "q-bio.PE",  "name": "農業科學",     "role": "農業科學研究助理",   "arxiv_native": False, "biorxiv": True, "pubmed_mesh": "Agriculture"},

    # ── 經濟 / 金融 / 計量 (arXiv native) ───────────────────────
    "econ":          {"cat": "econ.GN", "name": "經濟",         "role": "經濟學研究助理",   "arxiv_native": True},
    "econometrics":  {"cat": "econ.EM", "name": "計量經濟",     "role": "計量經濟研究助理", "arxiv_native": True},
    "thecon":        {"cat": "econ.TH", "name": "理論經濟",     "role": "理論經濟研究助理", "arxiv_native": True},
    "finance":       {"cat": "q-fin.PR","name": "金融",         "role": "金融研究助理",     "arxiv_native": True},
    "quantfin":      {"cat": "q-fin.MF","name": "計量金融",     "role": "計量金融研究助理", "arxiv_native": True},
    "finengineer":   {"cat": "q-fin.CP","name": "金融工程",     "role": "金融工程研究助理", "arxiv_native": True},
    "riskmgmt":      {"cat": "q-fin.RM","name": "風險管理",     "role": "風險管理研究助理", "arxiv_native": True},
    "tradingstrat":  {"cat": "q-fin.TR","name": "交易策略",     "role": "交易策略研究助理", "arxiv_native": True},

    # ── 電機 / 控制 ─────────────────────────────────────────────
    "eess":          {"cat": "eess.SP", "name": "電機與信號",   "role": "電機工程研究助理", "arxiv_native": True, "cats": ["eess.SP", "eess.SY"]},
    "speech":        {"cat": "eess.AS", "name": "語音與音訊",   "role": "語音研究助理",     "arxiv_native": True, "cats": ["eess.AS", "cs.SD"]},
    "control":       {"cat": "eess.SY", "name": "控制與系統工程","role": "控制工程研究助理","arxiv_native": True},
    "civil":         {"cat": "eess.SY", "name": "土木與結構",   "role": "土木工程研究助理", "arxiv_native": False},
    "indus":         {"cat": "math.OC", "name": "工業工程",     "role": "工業工程研究助理", "arxiv_native": False},
    "chemeng":       {"cat": "physics.chem-ph", "name": "化學工程", "role": "化工研究助理", "arxiv_native": False, "chemrxiv": True},

    # ── 人文社科 (arXiv 沒涵蓋, 主要靠 OpenAlex/Crossref) ──────
    # 這些 cat 只是「最相近的 arXiv 分類」, 主要資料源在 P2 OpenAlex
    "philosophy":    {"cat": _FALLBACK_CY, "name": "哲學",       "role": "哲學研究助理",     "arxiv_native": False, "openalex_concept": "C138885662", "crossref_subject": "Philosophy"},
    "linguistics":   {"cat": "cs.CL",      "name": "語言學",     "role": "語言學研究助理",   "arxiv_native": False, "openalex_concept": "C41895202",  "crossref_subject": "Linguistics"},
    "psychology":    {"cat": "q-bio.NC",   "name": "心理學",     "role": "心理學研究助理",   "arxiv_native": False, "openalex_concept": "C15744967",  "pubmed_mesh": "Psychology", "crossref_subject": "Psychology"},
    "sociology":     {"cat": "physics.soc-ph", "name": "社會學", "role": "社會學研究助理",   "arxiv_native": False, "openalex_concept": "C144024400", "crossref_subject": "Sociology"},
    "political":     {"cat": "econ.GN",    "name": "政治學",     "role": "政治學研究助理",   "arxiv_native": False, "openalex_concept": "C17744445",  "crossref_subject": "Political Science"},
    "intlrelat":     {"cat": "econ.GN",    "name": "國際關係",   "role": "國際關係研究助理", "arxiv_native": False, "openalex_concept": "C94625758",  "crossref_subject": "International Relations"},
    "law":           {"cat": _FALLBACK_CY, "name": "法律",       "role": "法律研究助理",     "arxiv_native": False, "openalex_concept": "C199539241", "crossref_subject": "Law"},
    "education":     {"cat": "physics.ed-ph", "name": "教育",    "role": "教育研究助理",     "arxiv_native": False, "openalex_concept": "C19417346",  "crossref_subject": "Education"},
    "history":       {"cat": "physics.hist-ph", "name": "歷史",  "role": "歷史研究助理",     "arxiv_native": False, "openalex_concept": "C95457728",  "crossref_subject": "History"},
    "literature":    {"cat": "cs.CL",      "name": "文學",       "role": "文學研究助理",     "arxiv_native": False, "openalex_concept": "C124952713", "crossref_subject": "Literature"},
    "anthro":        {"cat": "physics.soc-ph", "name": "人類學", "role": "人類學研究助理",   "arxiv_native": False, "openalex_concept": "C19165224",  "crossref_subject": "Anthropology"},
    "religion":      {"cat": _FALLBACK_CY, "name": "宗教研究",   "role": "宗教研究助理",     "arxiv_native": False, "openalex_concept": "C24667770",  "crossref_subject": "Religious Studies"},
    "arthistory":    {"cat": "physics.hist-ph", "name": "藝術史","role": "藝術史研究助理",   "arxiv_native": False, "openalex_concept": "C52119013",  "crossref_subject": "Art History"},
    "commun":        {"cat": "physics.soc-ph", "name": "傳播學", "role": "傳播研究助理",     "arxiv_native": False, "openalex_concept": "C29595303",  "crossref_subject": "Communication"},
    "geography":     {"cat": "physics.geo-ph", "name": "地理學", "role": "地理學研究助理",   "arxiv_native": False, "openalex_concept": "C205649164", "crossref_subject": "Geography"},
    "publicpolicy":  {"cat": _FALLBACK_CY, "name": "公共政策",   "role": "公共政策研究助理", "arxiv_native": False, "openalex_concept": "C2779343474","crossref_subject": "Public Policy"},
    "socialwork":    {"cat": _FALLBACK_CY, "name": "社會工作",   "role": "社會工作研究助理", "arxiv_native": False, "openalex_concept": "C2778137410","crossref_subject": "Social Work"},
    "urbanplan":     {"cat": "physics.geo-ph", "name": "都市規劃","role": "都市規劃研究助理","arxiv_native": False, "openalex_concept": "C107826830", "crossref_subject": "Urban Planning"},

    # ── 商管 (arXiv 沒涵蓋, 主要靠 OpenAlex/Crossref) ───────────
    "management":    {"cat": "econ.GN", "name": "企業管理",     "role": "管理研究助理",     "arxiv_native": False, "openalex_concept": "C144133560", "crossref_subject": "Business and Management"},
    "marketing":     {"cat": "econ.GN", "name": "行銷",         "role": "行銷研究助理",     "arxiv_native": False, "openalex_concept": "C162853370", "crossref_subject": "Marketing"},
    "accounting":    {"cat": "econ.GN", "name": "會計",         "role": "會計研究助理",     "arxiv_native": False, "openalex_concept": "C121955636", "crossref_subject": "Accounting"},

    # ── 設計 / 藝術 / 人文表演 (arXiv 沒涵蓋) ─────────────────
    "music":         {"cat": "cs.SD",  "name": "音樂學",       "role": "音樂研究助理",     "arxiv_native": False, "openalex_concept": "C558565934", "crossref_subject": "Music"},
    "design":        {"cat": "cs.HC",  "name": "設計",         "role": "設計研究助理",     "arxiv_native": False, "openalex_concept": "C153349607", "crossref_subject": "Design"},
    "uxdesign":      {"cat": "cs.HC",  "name": "使用者經驗設計","role": "UX 研究助理",     "arxiv_native": False, "openalex_concept": "C107457646", "crossref_subject": "User Experience"},
    "industdesign":  {"cat": "cs.HC",  "name": "工業設計",     "role": "工業設計研究助理", "arxiv_native": False, "openalex_concept": "C108170787", "crossref_subject": "Industrial Design"},
    "gamedesign":    {"cat": "cs.GR",  "name": "遊戲設計",     "role": "遊戲設計研究助理", "arxiv_native": False, "openalex_concept": "C107457646", "crossref_subject": "Game Design"},
    "film":          {"cat": "cs.MM",  "name": "電影與媒體",   "role": "電影研究助理",     "arxiv_native": False, "openalex_concept": "C520712124", "crossref_subject": "Film Studies"},
    "theater":       {"cat": "cs.HC",  "name": "劇場表演",     "role": "劇場研究助理",     "arxiv_native": False, "openalex_concept": "C107038049", "crossref_subject": "Performing Arts"},
    "architecture":  {"cat": "cs.CG",  "name": "建築學",       "role": "建築研究助理",     "arxiv_native": False, "openalex_concept": "C107826830", "crossref_subject": "Architecture"},

    # ── #8 arXiv-native 細分學科補齊 (CS / math / physics 子分類) ───
    # CS 子分類
    "compeng":      {"cat": "cs.CE",   "name": "計算工程與科學",   "role": "計算工程研究助理",   "arxiv_native": True},
    "compgeom":     {"cat": "cs.CG",   "name": "計算幾何",         "role": "計算幾何研究助理",   "arxiv_native": True},
    "compsoc":      {"cat": "cs.CY",   "name": "計算與社會",       "role": "計算社會研究助理",   "arxiv_native": True},
    "diglib":       {"cat": "cs.DL",   "name": "數位圖書館",       "role": "數位圖書館研究助理", "arxiv_native": True},
    "discretemath": {"cat": "cs.DM",   "name": "離散數學",         "role": "離散數學研究助理",   "arxiv_native": True},
    "emergtech":    {"cat": "cs.ET",   "name": "新興技術",         "role": "新興技術研究助理",   "arxiv_native": True},
    "mathsoft":     {"cat": "cs.MS",   "name": "數學軟體",         "role": "數學軟體研究助理",   "arxiv_native": True},
    "evocomp":      {"cat": "cs.NE",   "name": "神經與演化計算",   "role": "演化計算研究助理",   "arxiv_native": True},
    # 數學子分類
    "commalg":      {"cat": "math.AC", "name": "交換代數",         "role": "交換代數研究助理",   "arxiv_native": True},
    "classanalysis":{"cat": "math.CA", "name": "古典分析與常微分", "role": "古典分析研究助理",   "arxiv_native": True},
    "cattheory":    {"cat": "math.CT", "name": "範疇論",           "role": "範疇論研究助理",     "arxiv_native": True},
    "complexvar":   {"cat": "math.CV", "name": "複變函數",         "role": "複變函數研究助理",   "arxiv_native": True},
    "dynsys":       {"cat": "math.DS", "name": "動力系統",         "role": "動力系統研究助理",   "arxiv_native": True},
    "funcanalysis": {"cat": "math.FA", "name": "泛函分析",         "role": "泛函分析研究助理",   "arxiv_native": True},
    "grouptheory":  {"cat": "math.GR", "name": "群論",             "role": "群論研究助理",       "arxiv_native": True},
    "geomtop":      {"cat": "math.GT", "name": "幾何拓樸",         "role": "幾何拓樸研究助理",   "arxiv_native": True},
    "mathlogic":    {"cat": "math.LO", "name": "數理邏輯",         "role": "數理邏輯研究助理",   "arxiv_native": True},
    "mathphys":     {"cat": "math.MP", "name": "數學物理",         "role": "數學物理研究助理",   "arxiv_native": True},
    "ringsalg":     {"cat": "math.RA", "name": "環與代數",         "role": "環論研究助理",       "arxiv_native": True},
    "reptheory":    {"cat": "math.RT", "name": "表示論",           "role": "表示論研究助理",     "arxiv_native": True},
    "statstheory":  {"cat": "math.ST", "name": "統計理論",         "role": "統計理論研究助理",   "arxiv_native": True},
    "metricgeom":   {"cat": "math.MG", "name": "度量幾何",         "role": "度量幾何研究助理",   "arxiv_native": True},
    # 物理子分類
    "cosmology":    {"cat": "astro-ph.CO",       "name": "宇宙學",         "role": "宇宙學研究助理",     "arxiv_native": True},
    "planetary":    {"cat": "astro-ph.EP",       "name": "行星科學",       "role": "行星科學研究助理",   "arxiv_native": True},
    "astrohe":      {"cat": "astro-ph.HE",       "name": "高能天文物理",   "role": "高能天文研究助理",   "arxiv_native": True},
    "stellar":      {"cat": "astro-ph.SR",       "name": "太陽與恆星物理", "role": "恆星物理研究助理",   "arxiv_native": True},
    "supercon":     {"cat": "cond-mat.supr-con", "name": "超導體",         "role": "超導研究助理",       "arxiv_native": True},
    "nanophys":     {"cat": "cond-mat.mes-hall", "name": "奈米與介觀物理", "role": "奈米物理研究助理",   "arxiv_native": True},
    "softmatter":   {"cat": "cond-mat.soft",     "name": "軟物質",         "role": "軟物質研究助理",     "arxiv_native": True},
    "disordered":   {"cat": "cond-mat.dis-nn",   "name": "無序系統",       "role": "無序系統研究助理",   "arxiv_native": True},
    "strongcorr":   {"cat": "cond-mat.str-el",   "name": "強關聯電子",     "role": "強關聯研究助理",     "arxiv_native": True},
    "hepex":        {"cat": "hep-ex",            "name": "高能物理實驗",   "role": "高能實驗研究助理",   "arxiv_native": True},
    "heplat":       {"cat": "hep-lat",           "name": "格點高能物理",   "role": "格點研究助理",       "arxiv_native": True},
    "nuclex":       {"cat": "nucl-ex",           "name": "核物理實驗",     "role": "核實驗研究助理",     "arxiv_native": True},
    "chaos":        {"cat": "nlin.CD",           "name": "混沌動力學",     "role": "混沌研究助理",       "arxiv_native": True},
    "selforg":      {"cat": "nlin.AO",           "name": "適應與自組織系統","role": "自組織研究助理",    "arxiv_native": True},
    "patternform":  {"cat": "nlin.PS",           "name": "圖樣形成與孤立子","role": "圖樣形成研究助理",  "arxiv_native": True},
    "integrable":   {"cat": "nlin.SI",           "name": "可積系統",       "role": "可積系統研究助理",   "arxiv_native": True},
    "accelphys":    {"cat": "physics.acc-ph",    "name": "加速器物理",     "role": "加速器研究助理",     "arxiv_native": True},
    "appliedphys":  {"cat": "physics.app-ph",    "name": "應用物理",       "role": "應用物理研究助理",   "arxiv_native": True},
    "atomicphys":   {"cat": "physics.atom-ph",   "name": "原子物理",       "role": "原子物理研究助理",   "arxiv_native": True},
    "compphys":     {"cat": "physics.comp-ph",   "name": "計算物理",       "role": "計算物理研究助理",   "arxiv_native": True},
    "physdataan":   {"cat": "physics.data-an",   "name": "物理資料分析",   "role": "資料分析研究助理",   "arxiv_native": True},
    "spacephys":    {"cat": "physics.space-ph",  "name": "太空物理",       "role": "太空物理研究助理",   "arxiv_native": True},
}

DEFAULT_DISCIPLINE = "cv"


def discipline(d: str | None) -> dict:
    return DISCIPLINES.get((d or "").lower(), DISCIPLINES[DEFAULT_DISCIPLINE])
