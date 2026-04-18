// 研究領域設定：每個學科定義 arXiv 類別、頂會/期刊、主題關鍵字、摘要提示。
// 前端與後端（透過 /api/disciplines 的鏡像）共用本檔案。
window.DISCIPLINES = {
    cv: {
        id: 'cv',
        icon: '👁️',
        name: '電腦視覺',
        nameEn: 'Computer Vision',
        brand: 'Visionary',
        arxivCat: 'cs.CV',
        promptRole: '電腦視覺研究助理',
        accent: { from: '#3b82f6', to: '#a855f7', tint: 'rgba(59,130,246,0.18)' },
        loaderHints: [
            '連接 arXiv 資料庫中...',
            '整理本週 CV 論文（Diffusion / NeRF / 3DGS / VLM 等）...',
            '交叉比對 Semantic Scholar 引用數...',
        ],
        confs: [
            { key: 'cvpr',    label: 'CVPR',    color: '#3b82f6' },
            { key: 'iccv',    label: 'ICCV',    color: '#6366f1' },
            { key: 'eccv',    label: 'ECCV',    color: '#8b5cf6' },
            { key: 'neurips', label: 'NeurIPS', color: '#059669' },
            { key: 'iclr',    label: 'ICLR',    color: '#0d9488' },
            { key: 'icml',    label: 'ICML',    color: '#10b981' },
            { key: 'tpami',   label: 'TPAMI',   color: '#1d4ed8' },
            { key: 'wacv',    label: 'WACV',    color: '#7c3aed' },
            { key: 'bmvc',    label: 'BMVC',    color: '#7c3aed' },
            { key: 'ijcv',    label: 'IJCV',    color: '#2563eb' },
        ],
        topics: [
            'Diffusion Model', 'NeRF', 'Gaussian Splatting', 'Depth Estimation',
            'Segmentation', 'Object Detection', '3D Reconstruction', 'Pose Estimation',
            'SLAM', 'Optical Flow', 'Feature Matching', 'Super Resolution',
            'Video Understanding', 'Point Cloud', 'Multimodal', 'Transformer',
            'Generation', 'Medical Imaging', 'Self-Supervised', 'Autonomous Driving',
        ],
        synonyms: {
            'nerf': ['neural radiance', 'radiance field', 'neural rendering'],
            'gaussian splatting': ['3dgs', 'gs', 'splat', 'splatting', '3d gaussian'],
            'diffusion model': ['ddpm', 'latent diffusion', 'stable diffusion', 'score-based'],
            'transformer': ['attention', 'self-attention', 'vit', 'vision transformer'],
            'segmentation': ['sam', 'mask'],
            'object detection': ['detector', 'yolo', 'detr'],
            'depth estimation': ['monocular depth', 'stereo depth'],
            'multimodal': ['vlm', 'vision-language', 'clip'],
        },
    },

    nlp: {
        id: 'nlp',
        icon: '💬',
        name: '自然語言處理',
        nameEn: 'Natural Language Processing',
        brand: 'Lexical',
        arxivCat: 'cs.CL',
        promptRole: '自然語言處理研究助理',
        accent: { from: '#f97316', to: '#ec4899', tint: 'rgba(249,115,22,0.18)' },
        loaderHints: [
            '連接 arXiv cs.CL 資料中...',
            '整理本週 NLP 論文（LLM / RAG / Alignment / Agent 等）...',
            '對照 ACL Anthology 與 Semantic Scholar...',
        ],
        confs: [
            { key: 'acl',     label: 'ACL',     color: '#c2410c' },
            { key: 'emnlp',   label: 'EMNLP',   color: '#ea580c' },
            { key: 'naacl',   label: 'NAACL',   color: '#f97316' },
            { key: 'coling',  label: 'COLING',  color: '#d97706' },
            { key: 'eacl',    label: 'EACL',    color: '#b45309' },
            { key: 'tacl',    label: 'TACL',    color: '#92400e' },
            { key: 'neurips', label: 'NeurIPS', color: '#059669' },
            { key: 'iclr',    label: 'ICLR',    color: '#0d9488' },
            { key: 'icml',    label: 'ICML',    color: '#10b981' },
        ],
        topics: [
            'Large Language Model', 'Instruction Tuning', 'RAG', 'Retrieval',
            'Alignment', 'RLHF', 'Reasoning', 'Chain-of-Thought', 'Agent',
            'Tool Use', 'Translation', 'Summarization', 'Dialogue',
            'Question Answering', 'Code Generation', 'Multilingual',
            'Prompt Engineering', 'Long Context', 'Benchmark', 'Evaluation',
        ],
        synonyms: {
            'large language model': ['llm', 'gpt', 'llama', 'mistral'],
            'chain-of-thought': ['cot', 'reasoning chain'],
            'rag': ['retrieval-augmented', 'retrieval augmented'],
            'rlhf': ['reward model', 'human feedback', 'dpo', 'preference'],
        },
    },

    ml: {
        id: 'ml',
        icon: '🧠',
        name: '機器學習',
        nameEn: 'Machine Learning',
        brand: 'Gradient',
        arxivCat: 'cs.LG',
        promptRole: '機器學習研究助理',
        accent: { from: '#10b981', to: '#0ea5e9', tint: 'rgba(16,185,129,0.18)' },
        loaderHints: [
            '連接 arXiv cs.LG 資料中...',
            '整理本週 ML 論文（Optimization / MoE / Diffusion / RL 等）...',
            '比對 NeurIPS / ICML / ICLR 近期成果...',
        ],
        confs: [
            { key: 'neurips',  label: 'NeurIPS',  color: '#059669' },
            { key: 'icml',     label: 'ICML',     color: '#10b981' },
            { key: 'iclr',     label: 'ICLR',     color: '#0d9488' },
            { key: 'aistats',  label: 'AISTATS',  color: '#047857' },
            { key: 'uai',      label: 'UAI',      color: '#065f46' },
            { key: 'colt',     label: 'COLT',     color: '#064e3b' },
            { key: 'jmlr',     label: 'JMLR',     color: '#166534' },
            { key: 'aaai',     label: 'AAAI',     color: '#dc2626' },
            { key: 'kdd',      label: 'KDD',      color: '#f43f5e' },
        ],
        topics: [
            'Diffusion', 'Optimization', 'Generalization', 'Representation Learning',
            'Self-Supervised', 'Contrastive', 'Transformer', 'Attention',
            'Mixture of Experts', 'Distillation', 'Quantization', 'Pruning',
            'Federated Learning', 'Meta-Learning', 'Continual Learning',
            'Causal', 'Graph Neural Network', 'Reinforcement Learning',
            'Bayesian', 'Generative Model',
        ],
        synonyms: {
            'mixture of experts': ['moe', 'experts'],
            'graph neural network': ['gnn', 'message passing'],
            'reinforcement learning': ['rl', 'ppo', 'q-learning'],
        },
    },

    ai: {
        id: 'ai',
        icon: '🤖',
        name: '人工智慧',
        nameEn: 'Artificial Intelligence',
        brand: 'Cogito',
        arxivCat: 'cs.AI',
        promptRole: '人工智慧研究助理',
        accent: { from: '#a855f7', to: '#dc2626', tint: 'rgba(168,85,247,0.18)' },
        loaderHints: [
            '連接 arXiv cs.AI 資料中...',
            '整理本週 AI 論文（Reasoning / Planning / Multi-Agent / Neurosymbolic 等）...',
            '掃描 AAAI / IJCAI 最新進展...',
        ],
        confs: [
            { key: 'aaai',    label: 'AAAI',    color: '#dc2626' },
            { key: 'ijcai',   label: 'IJCAI',   color: '#b91c1c' },
            { key: 'neurips', label: 'NeurIPS', color: '#059669' },
            { key: 'icml',    label: 'ICML',    color: '#10b981' },
            { key: 'iclr',    label: 'ICLR',    color: '#0d9488' },
            { key: 'aamas',   label: 'AAMAS',   color: '#7c3aed' },
            { key: 'kr',      label: 'KR',      color: '#6d28d9' },
        ],
        topics: [
            'Reasoning', 'Planning', 'Search', 'Knowledge Graph', 'Symbolic',
            'Logic', 'Multi-Agent', 'Game Theory', 'Explainable',
            'Ethics', 'Alignment', 'Foundation Model', 'Agent',
            'Causal Inference', 'Neurosymbolic', 'Constraint Satisfaction',
        ],
        synonyms: {
            'multi-agent': ['multiagent', 'agent-based'],
            'knowledge graph': ['kg', 'ontology'],
        },
    },

    robotics: {
        id: 'robotics',
        icon: '🦾',
        name: '機器人學',
        nameEn: 'Robotics',
        brand: 'Kinematic',
        arxivCat: 'cs.RO',
        promptRole: '機器人學研究助理',
        accent: { from: '#0ea5e9', to: '#1e3a8a', tint: 'rgba(14,165,233,0.18)' },
        loaderHints: [
            '連接 arXiv cs.RO 資料中...',
            '整理本週 Robotics 論文（Manipulation / Locomotion / Sim-to-Real / Humanoid 等）...',
            '追蹤 ICRA / IROS / CoRL 近期研究...',
        ],
        confs: [
            { key: 'icra',       label: 'ICRA',       color: '#0ea5e9' },
            { key: 'iros',       label: 'IROS',       color: '#0284c7' },
            { key: 'rss',        label: 'RSS',        color: '#0369a1' },
            { key: 'corl',       label: 'CoRL',       color: '#075985' },
            { key: 'humanoids',  label: 'Humanoids',  color: '#0c4a6e' },
            { key: 'tro',        label: 'T-RO',       color: '#1d4ed8' },
            { key: 'ral',        label: 'RA-L',       color: '#2563eb' },
        ],
        topics: [
            'Manipulation', 'Grasping', 'Locomotion', 'Navigation', 'SLAM',
            'Motion Planning', 'Imitation Learning', 'Reinforcement Learning',
            'Sim-to-Real', 'Humanoid', 'Soft Robotics', 'Tactile',
            'Whole-Body Control', 'Quadruped', 'Dexterous', 'Visual Servoing',
            'Teleoperation', 'Haptic', 'Legged', 'Autonomous Driving',
        ],
        synonyms: {
            'sim-to-real': ['sim2real', 'domain randomization'],
            'imitation learning': ['behavior cloning', 'diffusion policy'],
        },
    },

    graphics: {
        id: 'graphics',
        icon: '🎨',
        name: '電腦繪圖',
        nameEn: 'Computer Graphics',
        brand: 'Pixel',
        arxivCat: 'cs.GR',
        promptRole: '電腦繪圖研究助理',
        accent: { from: '#f59e0b', to: '#ec4899', tint: 'rgba(245,158,11,0.18)' },
        loaderHints: [
            '連接 arXiv cs.GR 資料中...',
            '整理本週 Graphics 論文（Neural Rendering / 3DGS / Simulation / Inverse Rendering 等）...',
            '同步 SIGGRAPH / Eurographics 會議流水線...',
        ],
        confs: [
            { key: 'siggraph asia', label: 'SIGGRAPH Asia', color: '#f59e0b' },
            { key: 'siggraph',      label: 'SIGGRAPH',      color: '#d97706' },
            { key: 'eurographics',  label: 'Eurographics',  color: '#b45309' },
            { key: 'tog',           label: 'TOG',           color: '#92400e' },
            { key: 'i3d',           label: 'I3D',           color: '#a16207' },
            { key: 'hpg',           label: 'HPG',           color: '#854d0e' },
            { key: 'sca',           label: 'SCA',           color: '#713f12' },
        ],
        topics: [
            'Ray Tracing', 'Path Tracing', 'Neural Rendering', 'NeRF',
            'Gaussian Splatting', 'Mesh', 'Geometry Processing', 'Simulation',
            'Fluid', 'Cloth', 'Character Animation', 'Shading',
            'BRDF', 'Subdivision', 'Point Cloud', 'Texture Synthesis',
            'Inverse Rendering', 'Light Transport',
        ],
        synonyms: {
            'neural rendering': ['differentiable rendering', 'volume rendering'],
        },
    },

    security: {
        id: 'security',
        icon: '🔒',
        name: '資訊安全',
        nameEn: 'Security & Privacy',
        brand: 'Cipher',
        arxivCat: 'cs.CR',
        promptRole: '資訊安全研究助理',
        accent: { from: '#dc2626', to: '#6b21a8', tint: 'rgba(220,38,38,0.18)' },
        loaderHints: [
            '連接 arXiv cs.CR 資料中...',
            '整理本週 Security 論文（Fuzzing / Side Channel / ZK / Post-Quantum 等）...',
            '對照 USENIX / CCS / IEEE S&P 最新成果...',
        ],
        confs: [
            { key: 'oakland',  label: 'IEEE S&P',        color: '#b91c1c' },
            { key: 'ccs',      label: 'CCS',             color: '#dc2626' },
            { key: 'usenix',   label: 'USENIX Security', color: '#991b1b' },
            { key: 'ndss',     label: 'NDSS',            color: '#7f1d1d' },
            { key: 'pets',     label: 'PETS',            color: '#a21caf' },
            { key: 'crypto',   label: 'CRYPTO',          color: '#6b21a8' },
            { key: 'eurocrypt', label: 'Eurocrypt',      color: '#7e22ce' },
        ],
        topics: [
            'Cryptography', 'Side Channel', 'Malware', 'Fuzzing',
            'Binary Analysis', 'Reverse Engineering', 'Privacy',
            'Differential Privacy', 'Federated Learning', 'Adversarial',
            'Authentication', 'Blockchain', 'Zero Knowledge', 'Post-Quantum',
            'IoT Security', 'Web Security', 'Smart Contract', 'Supply Chain',
        ],
        synonyms: {
            'adversarial': ['adversarial attack', 'evasion'],
            'zero knowledge': ['zk', 'zkp', 'snark', 'stark'],
            'post-quantum': ['pqc', 'lattice'],
        },
    },

    systems: {
        id: 'systems',
        icon: '⚙️',
        name: '系統與架構',
        nameEn: 'Systems & Architecture',
        brand: 'Syscore',
        arxivCat: 'cs.OS',
        promptRole: '系統研究助理',
        accent: { from: '#0f766e', to: '#1e40af', tint: 'rgba(15,118,110,0.18)' },
        loaderHints: [
            '連接 arXiv cs.OS 資料中...',
            '整理本週 Systems 論文（Scheduler / GPU / Storage / Serverless / TEE 等）...',
            '比對 OSDI / SOSP / ASPLOS 近期論文...',
        ],
        confs: [
            { key: 'osdi',    label: 'OSDI',    color: '#0f766e' },
            { key: 'sosp',    label: 'SOSP',    color: '#115e59' },
            { key: 'nsdi',    label: 'NSDI',    color: '#134e4a' },
            { key: 'asplos',  label: 'ASPLOS',  color: '#0e7490' },
            { key: 'isca',    label: 'ISCA',    color: '#155e75' },
            { key: 'micro',   label: 'MICRO',   color: '#164e63' },
            { key: 'hpca',    label: 'HPCA',    color: '#1e40af' },
            { key: 'eurosys', label: 'EuroSys', color: '#1e3a8a' },
            { key: 'atc',     label: 'USENIX ATC', color: '#1e293b' },
        ],
        topics: [
            'Kernel', 'Scheduler', 'Virtualization', 'Container',
            'Storage', 'Distributed', 'Consensus', 'Cache',
            'GPU', 'Accelerator', 'Compilation', 'Memory',
            'File System', 'Serverless', 'RDMA', 'NVMe',
            'TEE', 'Persistent Memory',
        ],
        synonyms: {
            'tee': ['enclave', 'sgx', 'trustzone'],
        },
    },

    db: {
        id: 'db',
        icon: '🗄️',
        name: '資料庫',
        nameEn: 'Databases',
        brand: 'Tuple',
        arxivCat: 'cs.DB',
        promptRole: '資料庫研究助理',
        accent: { from: '#0891b2', to: '#22d3ee', tint: 'rgba(8,145,178,0.18)' },
        loaderHints: [
            '連接 arXiv cs.DB 資料中...',
            '整理本週 DB 論文（Query Opt / Vector DB / Learned Index / HTAP 等）...',
            '參照 SIGMOD / VLDB / CIDR 最新進展...',
        ],
        confs: [
            { key: 'sigmod', label: 'SIGMOD', color: '#0891b2' },
            { key: 'vldb',   label: 'VLDB',   color: '#0e7490' },
            { key: 'icde',   label: 'ICDE',   color: '#155e75' },
            { key: 'pods',   label: 'PODS',   color: '#164e63' },
            { key: 'edbt',   label: 'EDBT',   color: '#083344' },
            { key: 'cidr',   label: 'CIDR',   color: '#22d3ee' },
        ],
        topics: [
            'Query Optimization', 'Index', 'Transaction', 'OLTP', 'OLAP',
            'Distributed', 'Graph Database', 'Vector Database',
            'Stream Processing', 'Data Lake', 'Data Warehouse',
            'MVCC', 'Consistency', 'Sharding', 'Learned Index',
            'HTAP', 'Join Processing',
        ],
        synonyms: {
            'vector database': ['vector search', 'ann', 'hnsw'],
        },
    },

    hci: {
        id: 'hci',
        icon: '🖱️',
        name: '人機互動',
        nameEn: 'Human-Computer Interaction',
        brand: 'Interact',
        arxivCat: 'cs.HC',
        promptRole: '人機互動研究助理',
        accent: { from: '#db2777', to: '#a855f7', tint: 'rgba(219,39,119,0.18)' },
        loaderHints: [
            '連接 arXiv cs.HC 資料中...',
            '整理本週 HCI 論文（LLM Interface / AR/VR / Accessibility / BCI 等）...',
            '對照 CHI / UIST / CSCW 最新研究...',
        ],
        confs: [
            { key: 'chi',      label: 'CHI',      color: '#be185d' },
            { key: 'uist',     label: 'UIST',     color: '#9d174d' },
            { key: 'cscw',     label: 'CSCW',     color: '#831843' },
            { key: 'iui',      label: 'IUI',      color: '#db2777' },
            { key: 'ubicomp',  label: 'UbiComp',  color: '#ec4899' },
            { key: 'tei',      label: 'TEI',      color: '#f472b6' },
        ],
        topics: [
            'User Study', 'Accessibility', 'VR', 'AR', 'Mixed Reality',
            'Wearable', 'Haptic', 'Gaze', 'Brain-Computer Interface',
            'Collaboration', 'LLM Interface', 'AI-Assisted',
            'Sketch', 'Gesture', 'Voice Interface',
        ],
        synonyms: {
            'brain-computer interface': ['bci', 'neural interface'],
        },
    },

    ir: {
        id: 'ir',
        icon: '🔍',
        name: '資訊檢索與推薦',
        nameEn: 'IR & Recommender Systems',
        brand: 'Retrieve',
        arxivCat: 'cs.IR',
        promptRole: '資訊檢索研究助理',
        accent: { from: '#14b8a6', to: '#f43f5e', tint: 'rgba(20,184,166,0.18)' },
        loaderHints: [
            '連接 arXiv cs.IR 資料中...',
            '整理本週 IR / RecSys 論文（Dense Retrieval / Reranker / RAG / Sequential Rec 等）...',
            '對照 SIGIR / WWW / RecSys 最新成果...',
        ],
        confs: [
            { key: 'sigir',   label: 'SIGIR',   color: '#0f766e' },
            { key: 'wsdm',    label: 'WSDM',    color: '#115e59' },
            { key: 'cikm',    label: 'CIKM',    color: '#134e4a' },
            { key: 'www',     label: 'WWW',     color: '#0891b2' },
            { key: 'recsys',  label: 'RecSys',  color: '#0e7490' },
            { key: 'kdd',     label: 'KDD',     color: '#f43f5e' },
        ],
        topics: [
            'Ranking', 'Dense Retrieval', 'Sparse Retrieval', 'Embedding',
            'Reranker', 'Click Model', 'Recommendation',
            'Collaborative Filtering', 'Sequential Recommendation',
            'Cold Start', 'Conversational Search', 'RAG',
            'Knowledge Graph', 'Learning to Rank',
        ],
        synonyms: {
            'dense retrieval': ['bi-encoder', 'dpr'],
            'reranker': ['cross-encoder'],
        },
    },

    speech: {
        id: 'speech',
        icon: '🎙️',
        name: '語音與音訊',
        nameEn: 'Speech & Audio',
        brand: 'Sonar',
        arxivCat: 'eess.AS',
        promptRole: '語音研究助理',
        accent: { from: '#8b5cf6', to: '#ec4899', tint: 'rgba(139,92,246,0.18)' },
        loaderHints: [
            '連接 arXiv eess.AS 資料中...',
            '整理本週 Speech 論文（ASR / TTS / Codec / Voice Cloning / Source Separation 等）...',
            '追蹤 ICASSP / Interspeech 最新進展...',
        ],
        confs: [
            { key: 'icassp',      label: 'ICASSP',      color: '#be185d' },
            { key: 'interspeech', label: 'Interspeech', color: '#9d174d' },
            { key: 'asru',        label: 'ASRU',        color: '#831843' },
            { key: 'slt',         label: 'SLT',         color: '#db2777' },
            { key: 'waspaa',      label: 'WASPAA',      color: '#ec4899' },
            { key: 'taslp',       label: 'TASLP',       color: '#f472b6' },
        ],
        topics: [
            'ASR', 'TTS', 'Speech Synthesis', 'Voice Cloning',
            'Wake Word', 'Diarization', 'Speaker Recognition',
            'Emotion Recognition', 'Keyword Spotting', 'End-to-End',
            'Codec', 'Enhancement', 'Source Separation', 'Accent',
            'Music Generation', 'Audio Generation',
        ],
        synonyms: {
            'asr': ['speech recognition', 'whisper', 'wav2vec'],
            'tts': ['text-to-speech', 'text to speech'],
        },
    },
};

// ───── 非 CS 學科（PR#3 跨領域擴充）─────────────────────────────
// 涵蓋大學／研究所常見主修，arXiv 類別對應主要檔案夾
Object.assign(window.DISCIPLINES, {
    math: {
        id: 'math', icon: '∑', name: '數學', nameEn: 'Mathematics',
        brand: 'Theorem', arxivCat: 'math.OC',
        promptRole: '數學研究助理',
        accent: { from: '#334155', to: '#64748b', tint: 'rgba(100,116,139,0.18)' },
        loaderHints: [
            '連接 arXiv math 資料中...',
            '整理本週數學論文（Optimization / PDE / Combinatorics / Topology 等）...',
            '參照 Annals / Inventiones 近期文獻...',
        ],
        confs: [
            { key: 'annals',       label: 'Ann. of Math.', color: '#334155' },
            { key: 'inventiones',  label: 'Inventiones',   color: '#1e293b' },
            { key: 'acta',         label: 'Acta Math.',    color: '#475569' },
            { key: 'duke',         label: 'Duke Math. J.', color: '#0f172a' },
            { key: 'jams',         label: 'JAMS',          color: '#334155' },
        ],
        topics: [
            'Optimization', 'Convex', 'PDE', 'Combinatorics', 'Graph Theory',
            'Topology', 'Algebra', 'Number Theory', 'Probability',
            'Stochastic', 'Numerical Analysis', 'Dynamical System',
        ],
        synonyms: { 'pde': ['partial differential equation'] },
    },
    stats: {
        id: 'stats', icon: '📊', name: '統計學', nameEn: 'Statistics',
        brand: 'Infer', arxivCat: 'stat.ML',
        promptRole: '統計學研究助理',
        accent: { from: '#0d9488', to: '#06b6d4', tint: 'rgba(13,148,136,0.18)' },
        loaderHints: [
            '連接 arXiv stat 資料中...',
            '整理本週統計論文（Causal / Bayesian / High-Dim / Uncertainty 等）...',
            '對照 JASA / AoS / Biometrika 最新成果...',
        ],
        confs: [
            { key: 'jasa',        label: 'JASA',       color: '#0d9488' },
            { key: 'annals of statistics', label: 'AoS', color: '#0f766e' },
            { key: 'biometrika',  label: 'Biometrika', color: '#115e59' },
            { key: 'jrssb',       label: 'JRSSB',      color: '#134e4a' },
            { key: 'bernoulli',   label: 'Bernoulli',  color: '#0e7490' },
            { key: 'aistats',     label: 'AISTATS',    color: '#047857' },
        ],
        topics: [
            'Causal Inference', 'Bayesian', 'High-Dimensional',
            'Uncertainty', 'Hypothesis Testing', 'Survival Analysis',
            'Mixed Model', 'Time Series', 'Bootstrap', 'Regression',
            'Experimental Design', 'Non-parametric',
        ],
        synonyms: {
            'causal inference': ['causal', 'do-calculus'],
            'bayesian': ['posterior', 'mcmc', 'variational'],
        },
    },
    physics: {
        id: 'physics', icon: '⚛️', name: '物理', nameEn: 'Physics',
        brand: 'Quanta', arxivCat: 'cond-mat.stat-mech',
        promptRole: '物理研究助理',
        accent: { from: '#1e40af', to: '#7c3aed', tint: 'rgba(30,64,175,0.18)' },
        loaderHints: [
            '連接 arXiv physics 資料中...',
            '整理本週物理論文（Condensed Matter / Statistical / Quantum 等）...',
        ],
        confs: [
            { key: 'nature',        label: 'Nature',    color: '#1e3a8a' },
            { key: 'science',       label: 'Science',   color: '#1e40af' },
            { key: 'physical review letters', label: 'PRL', color: '#2563eb' },
            { key: 'prl',           label: 'PRL',       color: '#2563eb' },
            { key: 'prx',           label: 'PRX',       color: '#3b82f6' },
            { key: 'prb',           label: 'PRB',       color: '#1d4ed8' },
        ],
        topics: [
            'Condensed Matter', 'Superconductor', 'Topological',
            'Statistical Mechanics', 'Spin', 'Magnetism',
            'Phase Transition', 'Soft Matter', 'Plasma',
            'Optics', 'Photonics', 'Metamaterial',
        ],
        synonyms: { 'condensed matter': ['cond-mat'] },
    },
    astro: {
        id: 'astro', icon: '🔭', name: '天文物理', nameEn: 'Astrophysics',
        brand: 'Cosmos', arxivCat: 'astro-ph.GA',
        promptRole: '天文物理研究助理',
        accent: { from: '#6b21a8', to: '#1e3a8a', tint: 'rgba(107,33,168,0.18)' },
        loaderHints: [
            '連接 arXiv astro-ph 資料中...',
            '整理本週天文論文（Cosmology / Exoplanet / Galaxy / Black Hole 等）...',
        ],
        confs: [
            { key: 'nature astronomy', label: 'Nature Astronomy', color: '#6b21a8' },
            { key: 'apj',           label: 'ApJ',       color: '#7e22ce' },
            { key: 'mnras',         label: 'MNRAS',     color: '#9333ea' },
            { key: 'aj',            label: 'AJ',        color: '#a855f7' },
            { key: 'a&a',           label: 'A&A',       color: '#581c87' },
        ],
        topics: [
            'Cosmology', 'Dark Matter', 'Dark Energy', 'Exoplanet',
            'Black Hole', 'Galaxy', 'Gravitational Wave',
            'Supernova', 'Pulsar', 'Neutron Star',
            'CMB', 'Stellar', 'JWST',
        ],
        synonyms: {
            'gravitational wave': ['gw', 'ligo', 'virgo'],
            'cmb': ['cosmic microwave background'],
        },
    },
    quantum: {
        id: 'quantum', icon: '🧪', name: '量子', nameEn: 'Quantum Physics',
        brand: 'Entangle', arxivCat: 'quant-ph',
        promptRole: '量子物理研究助理',
        accent: { from: '#7c3aed', to: '#0ea5e9', tint: 'rgba(124,58,237,0.18)' },
        loaderHints: [
            '連接 arXiv quant-ph 資料中...',
            '整理本週量子論文（Error Correction / Algorithm / Circuit / Material 等）...',
        ],
        confs: [
            { key: 'quantum',       label: 'Quantum',   color: '#7c3aed' },
            { key: 'nature physics', label: 'Nat. Phys.', color: '#6d28d9' },
            { key: 'prx quantum',   label: 'PRX Quantum', color: '#8b5cf6' },
            { key: 'npj qi',        label: 'npj QI',    color: '#a78bfa' },
            { key: 'qip',           label: 'QIP',       color: '#6366f1' },
        ],
        topics: [
            'Quantum Computing', 'Error Correction', 'Quantum Algorithm',
            'Entanglement', 'Qubit', 'Superconducting',
            'Trapped Ion', 'Quantum Simulation', 'Variational',
            'Quantum Machine Learning', 'Quantum Cryptography',
        ],
        synonyms: {
            'quantum computing': ['qc', 'quantum processor'],
            'error correction': ['qec', 'surface code'],
        },
    },
    chem: {
        id: 'chem', icon: '🧬', name: '化學', nameEn: 'Chemistry',
        brand: 'Catalyst', arxivCat: 'physics.chem-ph',
        promptRole: '化學研究助理',
        accent: { from: '#16a34a', to: '#eab308', tint: 'rgba(22,163,74,0.18)' },
        loaderHints: [
            '連接 arXiv physics.chem-ph 資料中...',
            '整理本週化學論文（Catalysis / Computational / Materials 等）...',
        ],
        confs: [
            { key: 'jacs',          label: 'JACS',      color: '#166534' },
            { key: 'angewandte',    label: 'Angewandte', color: '#15803d' },
            { key: 'nature chemistry', label: 'Nat. Chem.', color: '#16a34a' },
            { key: 'nature catalysis', label: 'Nat. Catalysis', color: '#22c55e' },
            { key: 'chemrxiv',      label: 'ChemRxiv',  color: '#4ade80' },
        ],
        topics: [
            'Catalysis', 'Reaction Mechanism', 'DFT', 'Organic Synthesis',
            'Drug Discovery', 'Molecular Dynamics', 'Polymer',
            'Electrochemistry', 'Photochemistry', 'Materials',
            'Computational Chemistry',
        ],
        synonyms: {
            'dft': ['density functional theory'],
            'drug discovery': ['medicinal chemistry', 'pharmacology'],
        },
    },
    bio: {
        id: 'bio', icon: '🧫', name: '生物', nameEn: 'Biology',
        brand: 'Genome', arxivCat: 'q-bio.BM',
        promptRole: '生物學研究助理',
        accent: { from: '#059669', to: '#84cc16', tint: 'rgba(5,150,105,0.18)' },
        loaderHints: [
            '連接 arXiv q-bio 資料中...',
            '整理本週生物論文（Genomics / Proteomics / Single Cell / Systems Bio 等）...',
        ],
        confs: [
            { key: 'cell',          label: 'Cell',      color: '#059669' },
            { key: 'nature',        label: 'Nature',    color: '#047857' },
            { key: 'science',       label: 'Science',   color: '#065f46' },
            { key: 'nature biotechnology', label: 'Nat. Biotech', color: '#10b981' },
            { key: 'biorxiv',       label: 'bioRxiv',   color: '#34d399' },
            { key: 'recomb',        label: 'RECOMB',    color: '#6ee7b7' },
        ],
        topics: [
            'Genomics', 'Proteomics', 'Transcriptomics', 'CRISPR',
            'Protein Structure', 'Single-Cell', 'Systems Biology',
            'Drug Discovery', 'Evolution', 'Phylogenetics',
            'Molecular Dynamics', 'AlphaFold', 'Bioinformatics',
        ],
        synonyms: {
            'protein structure': ['alphafold', 'structure prediction'],
            'single-cell': ['scrna', 'sc-rna', 'single cell'],
        },
    },
    neuro: {
        id: 'neuro', icon: '🧠', name: '神經科學', nameEn: 'Neuroscience',
        brand: 'Synapse', arxivCat: 'q-bio.NC',
        promptRole: '神經科學研究助理',
        accent: { from: '#be185d', to: '#7c3aed', tint: 'rgba(190,24,93,0.18)' },
        loaderHints: [
            '連接 arXiv q-bio.NC 資料中...',
            '整理本週神經科學論文（Cortex / Brain Decoding / BCI / fMRI 等）...',
        ],
        confs: [
            { key: 'neuron',          label: 'Neuron',        color: '#be185d' },
            { key: 'nature neuroscience', label: 'Nat. Neuro', color: '#9d174d' },
            { key: 'cell',            label: 'Cell',          color: '#831843' },
            { key: 'jneuro',          label: 'J. Neurosci.',  color: '#db2777' },
            { key: 'cosyne',          label: 'COSYNE',        color: '#ec4899' },
            { key: 'neurips',         label: 'NeurIPS',       color: '#059669' },
        ],
        topics: [
            'Cortex', 'Brain Decoding', 'BCI', 'fMRI', 'EEG', 'MEG',
            'Spiking Neural Network', 'Neural Coding', 'Reinforcement Learning',
            'Memory', 'Attention', 'Perception', 'Connectome',
            'Calcium Imaging', 'Optogenetics',
        ],
        synonyms: {
            'bci': ['brain-computer interface', 'neural interface'],
            'fmri': ['functional mri'],
        },
    },
    econ: {
        id: 'econ', icon: '💹', name: '經濟', nameEn: 'Economics',
        brand: 'Market', arxivCat: 'econ.GN',
        promptRole: '經濟學研究助理',
        accent: { from: '#92400e', to: '#b91c1c', tint: 'rgba(146,64,14,0.18)' },
        loaderHints: [
            '連接 arXiv econ 資料中...',
            '整理本週經濟論文（Macro / Labor / Causal / Game Theory 等）...',
        ],
        confs: [
            { key: 'qje',           label: 'QJE',       color: '#92400e' },
            { key: 'aer',           label: 'AER',       color: '#b45309' },
            { key: 'econometrica',  label: 'Econometrica', color: '#a16207' },
            { key: 'jpe',           label: 'JPE',       color: '#854d0e' },
            { key: 'restud',        label: 'ReStud',    color: '#78350f' },
        ],
        topics: [
            'Causal Inference', 'Labor', 'Macro', 'Trade', 'Development',
            'Game Theory', 'Mechanism Design', 'Industrial Organization',
            'Policy Evaluation', 'Difference-in-Differences',
            'Experimental Economics', 'Econometrics',
        ],
        synonyms: {
            'difference-in-differences': ['did', 'diff-in-diff'],
            'causal inference': ['iv', 'instrumental'],
        },
    },
    finance: {
        id: 'finance', icon: '📈', name: '金融', nameEn: 'Finance',
        brand: 'Alpha', arxivCat: 'q-fin.PR',
        promptRole: '金融研究助理',
        accent: { from: '#0f766e', to: '#065f46', tint: 'rgba(15,118,110,0.18)' },
        loaderHints: [
            '連接 arXiv q-fin 資料中...',
            '整理本週金融論文（Asset Pricing / Risk / Portfolio / Derivatives 等）...',
        ],
        confs: [
            { key: 'journal of finance', label: 'J. of Finance', color: '#0f766e' },
            { key: 'rfs',           label: 'RFS',       color: '#115e59' },
            { key: 'jfe',           label: 'JFE',       color: '#134e4a' },
            { key: 'mathematical finance', label: 'Math. Finance', color: '#065f46' },
        ],
        topics: [
            'Asset Pricing', 'Portfolio', 'Risk Management', 'Derivatives',
            'Volatility', 'High-Frequency Trading', 'Market Microstructure',
            'Credit Risk', 'Option Pricing', 'Stochastic Volatility',
            'Reinforcement Learning', 'Cryptocurrency',
        ],
        synonyms: { 'option pricing': ['black-scholes', 'heston'] },
    },
    eess: {
        id: 'eess', icon: '📡', name: '電機與信號', nameEn: 'EE & Signal',
        brand: 'Signal', arxivCat: 'eess.SP',
        promptRole: '電機工程研究助理',
        accent: { from: '#0369a1', to: '#14b8a6', tint: 'rgba(3,105,161,0.18)' },
        loaderHints: [
            '連接 arXiv eess 資料中...',
            '整理本週電機論文（Signal Processing / Control / Communication 等）...',
        ],
        confs: [
            { key: 'icassp',        label: 'ICASSP',    color: '#0369a1' },
            { key: 'globecom',      label: 'GlobeCom',  color: '#0284c7' },
            { key: 'icc',           label: 'ICC',       color: '#0ea5e9' },
            { key: 'tsp',           label: 'T-SP',      color: '#075985' },
            { key: 'tac',           label: 'T-AC',      color: '#0c4a6e' },
            { key: 'cdc',           label: 'CDC',       color: '#164e63' },
        ],
        topics: [
            'Signal Processing', 'Control', 'Kalman Filter', 'Communication',
            '5G', '6G', 'MIMO', 'Radar', 'Sonar', 'Compressed Sensing',
            'Wireless', 'Power System', 'Reinforcement Learning',
        ],
        synonyms: { '5g': ['5th generation', 'millimeter wave'] },
    },
});

// ───── 人文／社會／工程／藝術（PR#3 續擴，大學全科覆蓋）─────
// 部分學門 arXiv 覆蓋有限，取最接近分類當 fallback；Bridge/搜尋仍可跨領域命中
Object.assign(window.DISCIPLINES, {
    philosophy: {
        id: 'philosophy', icon: '📜', name: '哲學', nameEn: 'Philosophy',
        brand: 'Logos', arxivCat: 'cs.CY',
        promptRole: '哲學研究助理',
        accent: { from: '#475569', to: '#92400e', tint: 'rgba(71,85,105,0.18)' },
        loaderHints: [
            '連接 arXiv cs.CY 資料中（AI 倫理與心靈哲學常見於此）...',
            '整理本週哲學論文（Ethics / Mind / Epistemology / AI Alignment 等）...',
            '對照 PhilPapers / SSRN 最新成果...',
        ],
        confs: [
            { key: 'philpapers',            label: 'PhilPapers',         color: '#475569' },
            { key: 'mind',                  label: 'Mind',               color: '#334155' },
            { key: 'journal of philosophy', label: 'J. of Philosophy',   color: '#1e293b' },
            { key: 'nous',                  label: 'Noûs',               color: '#64748b' },
            { key: 'synthese',              label: 'Synthese',           color: '#94a3b8' },
            { key: 'ssrn',                  label: 'SSRN',               color: '#475569' },
        ],
        topics: [
            'Ethics', 'AI Ethics', 'Alignment', 'Philosophy of Mind',
            'Epistemology', 'Metaphysics', 'Logic', 'Consciousness',
            'Free Will', 'Moral Philosophy', 'Phenomenology',
            'Philosophy of Science', 'Political Philosophy',
            'Value Alignment', 'Existential Risk',
        ],
        synonyms: {
            'ai ethics': ['ai alignment', 'machine ethics', 'responsible ai'],
            'philosophy of mind': ['consciousness', 'qualia', 'mental state'],
        },
    },
    linguistics: {
        id: 'linguistics', icon: '🔤', name: '語言學', nameEn: 'Linguistics',
        brand: 'Phoneme', arxivCat: 'cs.CL',
        promptRole: '語言學研究助理',
        accent: { from: '#ca8a04', to: '#b45309', tint: 'rgba(202,138,4,0.18)' },
        loaderHints: [
            '連接 arXiv cs.CL 資料中（理論語言學側）...',
            '整理本週語言學論文（Phonology / Syntax / Semantics / Pragmatics 等）...',
            '對照 LSA / Journal of Linguistics 最新成果...',
        ],
        confs: [
            { key: 'language',               label: 'Language',           color: '#ca8a04' },
            { key: 'linguistic inquiry',     label: 'Ling. Inquiry',      color: '#a16207' },
            { key: 'journal of linguistics', label: 'J. of Ling.',        color: '#854d0e' },
            { key: 'natural language semantics', label: 'Nat. Lang. Sem.', color: '#713f12' },
            { key: 'lsa',                    label: 'LSA',                color: '#eab308' },
        ],
        topics: [
            'Phonology', 'Syntax', 'Semantics', 'Pragmatics',
            'Morphology', 'Phonetics', 'Sociolinguistics',
            'Historical Linguistics', 'Typology', 'Corpus Linguistics',
            'Language Acquisition', 'Psycholinguistics', 'Discourse',
        ],
        synonyms: {
            'phonology': ['phonological', 'prosody'],
            'syntax': ['syntactic', 'parsing theory'],
        },
    },
    psychology: {
        id: 'psychology', icon: '🧩', name: '心理學', nameEn: 'Psychology',
        brand: 'Cognita', arxivCat: 'q-bio.NC',
        promptRole: '心理學研究助理',
        accent: { from: '#c026d3', to: '#f97316', tint: 'rgba(192,38,211,0.18)' },
        loaderHints: [
            '連接 arXiv q-bio.NC 資料中（認知科學重疊）...',
            '整理本週心理學論文（Cognitive / Social / Developmental / Clinical 等）...',
            '對照 Nature Human Behaviour / Psychological Review 最新成果...',
        ],
        confs: [
            { key: 'psychological review',      label: 'Psych. Review',       color: '#c026d3' },
            { key: 'nature human behaviour',    label: 'Nat. Hum. Behav.',    color: '#a21caf' },
            { key: 'psychological science',     label: 'Psych. Science',      color: '#86198f' },
            { key: 'cognition',                 label: 'Cognition',           color: '#701a75' },
            { key: 'psyarxiv',                  label: 'PsyArXiv',            color: '#d946ef' },
        ],
        topics: [
            'Cognitive Science', 'Social Psychology', 'Developmental',
            'Clinical Psychology', 'Behavioral', 'Decision Making',
            'Memory', 'Attention', 'Emotion', 'Personality',
            'Reasoning', 'Perception', 'Learning', 'Cognitive Bias',
        ],
        synonyms: {
            'decision making': ['heuristic', 'prospect theory'],
            'cognitive bias': ['dual process', 'system 1', 'system 2'],
        },
    },
    sociology: {
        id: 'sociology', icon: '🏘️', name: '社會學', nameEn: 'Sociology',
        brand: 'Polis', arxivCat: 'cs.CY',
        promptRole: '社會學研究助理',
        accent: { from: '#0369a1', to: '#7c2d12', tint: 'rgba(3,105,161,0.18)' },
        loaderHints: [
            '連接 arXiv cs.CY 資料中（計算社會科學）...',
            '整理本週社會學論文（Network / Inequality / Computational Social Science 等）...',
            '對照 SocArXiv / ASR 最新成果...',
        ],
        confs: [
            { key: 'american sociological review', label: 'ASR',             color: '#0369a1' },
            { key: 'american journal of sociology', label: 'AJS',           color: '#075985' },
            { key: 'social forces',                label: 'Social Forces',   color: '#0c4a6e' },
            { key: 'socarxiv',                     label: 'SocArXiv',        color: '#0284c7' },
            { key: 'icwsm',                        label: 'ICWSM',           color: '#7c2d12' },
        ],
        topics: [
            'Social Network', 'Inequality', 'Computational Social Science',
            'Demography', 'Stratification', 'Culture', 'Race',
            'Gender', 'Labor Market', 'Migration', 'Urban',
            'Collective Behavior', 'Misinformation', 'Polarization',
        ],
        synonyms: {
            'social network': ['social graph', 'homophily'],
            'misinformation': ['fake news', 'disinformation'],
        },
    },
    political: {
        id: 'political', icon: '🗳️', name: '政治學', nameEn: 'Political Science',
        brand: 'Civis', arxivCat: 'econ.GN',
        promptRole: '政治學研究助理',
        accent: { from: '#b91c1c', to: '#1e3a8a', tint: 'rgba(185,28,28,0.18)' },
        loaderHints: [
            '連接 arXiv econ.GN 資料中（政治經濟學側）...',
            '整理本週政治學論文（Voting / Democracy / IR / Conflict 等）...',
            '對照 APSR / AJPS 最新成果...',
        ],
        confs: [
            { key: 'american political science review', label: 'APSR',        color: '#b91c1c' },
            { key: 'american journal of political science', label: 'AJPS',   color: '#991b1b' },
            { key: 'journal of politics',                label: 'J. of Pol.', color: '#7f1d1d' },
            { key: 'international organization',         label: 'IO',         color: '#1e3a8a' },
            { key: 'world politics',                     label: 'World Pol.', color: '#1e40af' },
        ],
        topics: [
            'Voting', 'Election', 'Democracy', 'Authoritarianism',
            'International Relations', 'Conflict', 'Civil War',
            'Public Opinion', 'Populism', 'Polarization',
            'Political Economy', 'Institutions', 'Policy Evaluation',
        ],
        synonyms: {
            'international relations': ['ir theory', 'geopolitics'],
            'voting': ['elections', 'ballot'],
        },
    },
    law: {
        id: 'law', icon: '⚖️', name: '法律', nameEn: 'Law',
        brand: 'Stare', arxivCat: 'cs.CY',
        promptRole: '法律研究助理',
        accent: { from: '#57534e', to: '#78350f', tint: 'rgba(87,83,78,0.18)' },
        loaderHints: [
            '連接 arXiv cs.CY 資料中（科技法／AI 治理）...',
            '整理本週法律論文（AI Regulation / Privacy / IP / Constitutional 等）...',
            '對照 SSRN / Harvard Law Review 最新成果...',
        ],
        confs: [
            { key: 'harvard law review',  label: 'Harvard L. Rev.',  color: '#57534e' },
            { key: 'yale law journal',    label: 'Yale L.J.',        color: '#44403c' },
            { key: 'columbia law review', label: 'Columbia L. Rev.', color: '#292524' },
            { key: 'stanford law review', label: 'Stanford L. Rev.', color: '#78350f' },
            { key: 'ssrn',                label: 'SSRN',             color: '#78716c' },
        ],
        topics: [
            'AI Regulation', 'Data Protection', 'Privacy Law',
            'Intellectual Property', 'Copyright', 'Constitutional',
            'Criminal Law', 'Contract', 'Tort', 'Antitrust',
            'International Law', 'Human Rights', 'Algorithmic Accountability',
        ],
        synonyms: {
            'data protection': ['gdpr', 'ccpa', 'privacy'],
            'intellectual property': ['patent', 'trademark'],
        },
    },
    education: {
        id: 'education', icon: '🎓', name: '教育', nameEn: 'Education',
        brand: 'Scholastic', arxivCat: 'cs.CY',
        promptRole: '教育研究助理',
        accent: { from: '#0d9488', to: '#a16207', tint: 'rgba(13,148,136,0.18)' },
        loaderHints: [
            '連接 arXiv cs.CY 資料中（教育科技側）...',
            '整理本週教育論文（EdTech / ITS / MOOC / Assessment / LLM Tutor 等）...',
            '對照 AERA / JLS / L@S 最新成果...',
        ],
        confs: [
            { key: 'learning at scale', label: 'L@S',               color: '#0d9488' },
            { key: 'edm',               label: 'EDM',               color: '#0f766e' },
            { key: 'learning analytics', label: 'LAK',              color: '#115e59' },
            { key: 'aied',              label: 'AIED',              color: '#134e4a' },
            { key: 'jls',               label: 'J. Learning Sci.',  color: '#a16207' },
        ],
        topics: [
            'Intelligent Tutoring', 'Learning Analytics',
            'Assessment', 'MOOC', 'Personalized Learning',
            'Curriculum', 'Teacher Training', 'Educational Game',
            'Literacy', 'STEM Education', 'LLM Tutor',
        ],
        synonyms: {
            'intelligent tutoring': ['its', 'tutor system'],
            'llm tutor': ['chatbot tutor', 'gpt tutor'],
        },
    },
    history: {
        id: 'history', icon: '🏛️', name: '歷史', nameEn: 'History',
        brand: 'Chronos', arxivCat: 'cs.DL',
        promptRole: '歷史研究助理',
        accent: { from: '#78350f', to: '#451a03', tint: 'rgba(120,53,15,0.18)' },
        loaderHints: [
            '連接 arXiv cs.DL 資料中（數位人文）...',
            '整理本週歷史論文（Digital History / OCR / Archival / Historiography 等）...',
            '對照 AHR / Journal of Modern History 最新成果...',
        ],
        confs: [
            { key: 'american historical review', label: 'AHR',               color: '#78350f' },
            { key: 'journal of modern history',  label: 'J. Mod. Hist.',     color: '#9a3412' },
            { key: 'past & present',             label: 'Past & Present',    color: '#7c2d12' },
            { key: 'dh',                         label: 'DH',                color: '#78350f' },
        ],
        topics: [
            'Digital Humanities', 'Historiography', 'Archival',
            'OCR', 'Handwritten Text Recognition', 'Prosopography',
            'Medieval', 'Early Modern', 'Modern', 'Global History',
            'Quantitative History', 'Oral History',
        ],
        synonyms: {
            'digital humanities': ['dh', 'computational humanities'],
            'handwritten text recognition': ['htr', 'manuscript'],
        },
    },
    literature: {
        id: 'literature', icon: '📚', name: '文學', nameEn: 'Literature',
        brand: 'Narrativa', arxivCat: 'cs.CL',
        promptRole: '文學研究助理',
        accent: { from: '#831843', to: '#450a0a', tint: 'rgba(131,24,67,0.18)' },
        loaderHints: [
            '連接 arXiv cs.CL 資料中（計算文學分析）...',
            '整理本週文學論文（Stylometry / Narrative / Poetics / LLM Fiction 等）...',
            '對照 PMLA / New Literary History 最新成果...',
        ],
        confs: [
            { key: 'pmla',                       label: 'PMLA',           color: '#831843' },
            { key: 'new literary history',       label: 'NLH',            color: '#9d174d' },
            { key: 'critical inquiry',           label: 'Critical Inq.',  color: '#701a75' },
            { key: 'dsh',                        label: 'DSH',            color: '#86198f' },
        ],
        topics: [
            'Stylometry', 'Narrative', 'Poetics', 'Authorship Attribution',
            'Literary Theory', 'Distant Reading', 'Close Reading',
            'Creative Writing', 'Fiction', 'Poetry',
            'Computational Criticism',
        ],
        synonyms: {
            'stylometry': ['authorship', 'stylistic fingerprint'],
            'distant reading': ['macroanalysis', 'literary text mining'],
        },
    },
    anthro: {
        id: 'anthro', icon: '🗿', name: '人類學', nameEn: 'Anthropology',
        brand: 'Ethnos', arxivCat: 'cs.CY',
        promptRole: '人類學研究助理',
        accent: { from: '#854d0e', to: '#7c2d12', tint: 'rgba(133,77,14,0.18)' },
        loaderHints: [
            '連接 arXiv cs.CY 資料中（數位民族誌）...',
            '整理本週人類學論文（Ethnography / Kinship / Material Culture / Archaeology 等）...',
            '對照 AA / Current Anthropology 最新成果...',
        ],
        confs: [
            { key: 'american anthropologist', label: 'Am. Anthro.',     color: '#854d0e' },
            { key: 'current anthropology',    label: 'Curr. Anthro.',   color: '#92400e' },
            { key: 'cultural anthropology',   label: 'Cult. Anthro.',   color: '#7c2d12' },
            { key: 'american ethnologist',    label: 'Am. Ethnol.',     color: '#b45309' },
        ],
        topics: [
            'Ethnography', 'Kinship', 'Material Culture', 'Archaeology',
            'Biological Anthropology', 'Linguistic Anthropology',
            'Ritual', 'Religion', 'Indigenous', 'Digital Ethnography',
        ],
        synonyms: {
            'archaeology': ['excavation', 'artefact'],
            'digital ethnography': ['netnography', 'online fieldwork'],
        },
    },

    // ── 自然／工程 ─────────────────────────────────
    earth: {
        id: 'earth', icon: '🌍', name: '地球科學', nameEn: 'Earth Science',
        brand: 'Terra', arxivCat: 'physics.geo-ph',
        promptRole: '地球科學研究助理',
        accent: { from: '#047857', to: '#78350f', tint: 'rgba(4,120,87,0.18)' },
        loaderHints: [
            '連接 arXiv physics.geo-ph 資料中...',
            '整理本週地球科學論文（Geophysics / Seismology / Tectonics / Remote Sensing 等）...',
            '對照 Nature Geoscience / EGU 最新成果...',
        ],
        confs: [
            { key: 'nature geoscience',          label: 'Nat. Geosci.',   color: '#047857' },
            { key: 'jgr',                        label: 'JGR',            color: '#065f46' },
            { key: 'geophysical research letters', label: 'GRL',          color: '#064e3b' },
            { key: 'egu',                        label: 'EGU',            color: '#10b981' },
            { key: 'agu',                        label: 'AGU',            color: '#34d399' },
        ],
        topics: [
            'Seismology', 'Tectonics', 'Geodynamics', 'Volcanology',
            'Geomagnetism', 'Paleoclimate', 'Hydrology',
            'Remote Sensing', 'GIS', 'Mineralogy', 'Petrology',
        ],
        synonyms: {
            'remote sensing': ['satellite imagery', 'earth observation'],
            'seismology': ['earthquake', 'seismic wave'],
        },
    },
    climate: {
        id: 'climate', icon: '🌤️', name: '氣候與大氣', nameEn: 'Climate & Atmosphere',
        brand: 'Clima', arxivCat: 'physics.ao-ph',
        promptRole: '氣候科學研究助理',
        accent: { from: '#0284c7', to: '#15803d', tint: 'rgba(2,132,199,0.18)' },
        loaderHints: [
            '連接 arXiv physics.ao-ph 資料中...',
            '整理本週氣候論文（Climate Model / Extreme Weather / Ocean / Downscaling 等）...',
            '對照 Nature Climate Change 最新成果...',
        ],
        confs: [
            { key: 'nature climate change',  label: 'Nat. Clim. Change', color: '#0284c7' },
            { key: 'journal of climate',     label: 'J. of Climate',     color: '#0369a1' },
            { key: 'climate dynamics',       label: 'Clim. Dyn.',        color: '#075985' },
            { key: 'gmd',                    label: 'GMD',               color: '#15803d' },
        ],
        topics: [
            'Climate Model', 'Extreme Weather', 'Ocean Circulation',
            'Downscaling', 'El Niño', 'Monsoon',
            'Greenhouse Gas', 'Aerosol', 'Precipitation',
            'Sea Level', 'Tropical Cyclone', 'Carbon Cycle',
        ],
        synonyms: {
            'climate model': ['cmip', 'earth system model', 'gcm'],
            'extreme weather': ['heatwave', 'drought', 'flood'],
        },
    },
    materials: {
        id: 'materials', icon: '🔩', name: '材料科學', nameEn: 'Materials Science',
        brand: 'Lattice', arxivCat: 'cond-mat.mtrl-sci',
        promptRole: '材料科學研究助理',
        accent: { from: '#a3a3a3', to: '#ea580c', tint: 'rgba(163,163,163,0.18)' },
        loaderHints: [
            '連接 arXiv cond-mat.mtrl-sci 資料中...',
            '整理本週材料論文（Battery / Photovoltaic / 2D Materials / Superconductor / Alloy 等）...',
            '對照 Nature Materials / Science 最新成果...',
        ],
        confs: [
            { key: 'nature materials',       label: 'Nat. Mater.',    color: '#a3a3a3' },
            { key: 'advanced materials',     label: 'Adv. Mater.',    color: '#737373' },
            { key: 'acs nano',               label: 'ACS Nano',       color: '#ea580c' },
            { key: 'npj computational materials', label: 'npj Comp Mat', color: '#525252' },
        ],
        topics: [
            'Battery', 'Photovoltaic', '2D Materials', 'Graphene',
            'Superconductor', 'Alloy', 'Ceramic', 'Polymer',
            'Nanomaterial', 'Metamaterial', 'Crystal',
            'High-Throughput', 'DFT', 'Materials Genome',
        ],
        synonyms: {
            '2d materials': ['graphene', 'mos2', 'transition metal dichalcogenide'],
            'battery': ['li-ion', 'solid state battery', 'cathode'],
        },
    },
    mecheng: {
        id: 'mecheng', icon: '⚙️', name: '機械與流體', nameEn: 'Mechanical & Fluid Engineering',
        brand: 'Fluxus', arxivCat: 'physics.flu-dyn',
        promptRole: '機械工程研究助理',
        accent: { from: '#1d4ed8', to: '#be185d', tint: 'rgba(29,78,216,0.18)' },
        loaderHints: [
            '連接 arXiv physics.flu-dyn 資料中...',
            '整理本週機械／流體論文（Turbulence / CFD / Aerodynamics / Combustion 等）...',
            '對照 JFM / Phys. Fluids 最新成果...',
        ],
        confs: [
            { key: 'journal of fluid mechanics', label: 'JFM',            color: '#1d4ed8' },
            { key: 'physics of fluids',          label: 'Phys. Fluids',   color: '#2563eb' },
            { key: 'aiaa journal',               label: 'AIAA J.',        color: '#1e40af' },
            { key: 'combustion and flame',       label: 'Combust. Flame', color: '#be185d' },
        ],
        topics: [
            'Turbulence', 'CFD', 'Aerodynamics', 'Combustion',
            'Heat Transfer', 'Boundary Layer', 'Multiphase Flow',
            'Shock Wave', 'Propulsion', 'Acoustics',
            'Structural Mechanics', 'Finite Element',
        ],
        synonyms: {
            'cfd': ['computational fluid dynamics', 'rans', 'les'],
            'finite element': ['fem', 'fea'],
        },
    },
    civil: {
        id: 'civil', icon: '🏗️', name: '土木與結構', nameEn: 'Civil & Structural Engineering',
        brand: 'Beam', arxivCat: 'eess.SY',
        promptRole: '土木工程研究助理',
        accent: { from: '#57534e', to: '#84cc16', tint: 'rgba(87,83,78,0.18)' },
        loaderHints: [
            '連接 arXiv eess.SY / physics.app-ph 資料中...',
            '整理本週土木論文（Structural Health / Earthquake / Transportation / Concrete 等）...',
            '對照 ASCE / Engineering Structures 最新成果...',
        ],
        confs: [
            { key: 'journal of structural engineering', label: 'ASCE J. Struct.', color: '#57534e' },
            { key: 'engineering structures',           label: 'Eng. Struct.',    color: '#44403c' },
            { key: 'earthquake engineering & structural dynamics', label: 'EESD', color: '#78716c' },
            { key: 'cement and concrete research',     label: 'Cem. Concr.',     color: '#84cc16' },
        ],
        topics: [
            'Structural Health Monitoring', 'Earthquake Engineering',
            'Transportation', 'Traffic Flow', 'Bridge',
            'Concrete', 'Reinforced Concrete', 'Composite',
            'Geotechnical', 'Foundation', 'Urban Infrastructure',
        ],
        synonyms: {
            'structural health monitoring': ['shm', 'damage detection'],
            'earthquake engineering': ['seismic design'],
        },
    },

    // ── 醫療／生命／藝術 ─────────────────────────
    medimg: {
        id: 'medimg', icon: '🏥', name: '醫療影像', nameEn: 'Medical Imaging',
        brand: 'Radian', arxivCat: 'eess.IV',
        promptRole: '醫療影像研究助理',
        accent: { from: '#dc2626', to: '#ea580c', tint: 'rgba(220,38,38,0.18)' },
        loaderHints: [
            '連接 arXiv eess.IV 資料中...',
            '整理本週醫療影像論文（MRI / CT / Ultrasound / Pathology / Segmentation 等）...',
            '對照 MICCAI / Medical Image Analysis 最新成果...',
        ],
        confs: [
            { key: 'miccai',                  label: 'MICCAI',           color: '#dc2626' },
            { key: 'medical image analysis',  label: 'MedIA',            color: '#b91c1c' },
            { key: 'tmi',                     label: 'TMI',              color: '#991b1b' },
            { key: 'ipmi',                    label: 'IPMI',             color: '#ea580c' },
            { key: 'midl',                    label: 'MIDL',             color: '#f97316' },
        ],
        topics: [
            'MRI', 'CT', 'Ultrasound', 'PET', 'X-Ray',
            'Histopathology', 'Segmentation', 'Registration',
            'Radiomics', 'Lesion Detection', 'Image Reconstruction',
            'Diffusion MRI', 'Cardiac', 'Radiology Report',
        ],
        synonyms: {
            'mri': ['magnetic resonance imaging'],
            'ct': ['computed tomography'],
            'histopathology': ['whole slide image', 'wsi'],
        },
    },
    pubhealth: {
        id: 'pubhealth', icon: '🩺', name: '公衛', nameEn: 'Public Health',
        brand: 'Epidemia', arxivCat: 'q-bio.PE',
        promptRole: '公衛研究助理',
        accent: { from: '#15803d', to: '#b91c1c', tint: 'rgba(21,128,61,0.18)' },
        loaderHints: [
            '連接 arXiv q-bio.PE 資料中...',
            '整理本週公衛論文（Epidemiology / COVID / Surveillance / Health Equity 等）...',
            '對照 Lancet / NEJM / BMJ 最新成果...',
        ],
        confs: [
            { key: 'lancet',               label: 'Lancet',          color: '#b91c1c' },
            { key: 'nejm',                 label: 'NEJM',            color: '#dc2626' },
            { key: 'bmj',                  label: 'BMJ',             color: '#15803d' },
            { key: 'jama',                 label: 'JAMA',            color: '#16a34a' },
            { key: 'medrxiv',              label: 'medRxiv',         color: '#22c55e' },
        ],
        topics: [
            'Epidemiology', 'Infectious Disease', 'COVID-19',
            'Vaccination', 'Surveillance', 'Health Equity',
            'Global Health', 'Mortality', 'Screening',
            'Clinical Trial', 'Pharmacovigilance', 'One Health',
        ],
        synonyms: {
            'covid-19': ['sars-cov-2', 'covid', 'coronavirus'],
            'epidemiology': ['sir model', 'compartmental model'],
        },
    },
    biomed: {
        id: 'biomed', icon: '🫀', name: '生醫工程', nameEn: 'Biomedical Engineering',
        brand: 'Vitalis', arxivCat: 'q-bio.TO',
        promptRole: '生醫工程研究助理',
        accent: { from: '#e11d48', to: '#0ea5e9', tint: 'rgba(225,29,72,0.18)' },
        loaderHints: [
            '連接 arXiv q-bio.TO 資料中...',
            '整理本週生醫工程論文（Wearable / Tissue / Prosthetics / Drug Delivery 等）...',
            '對照 Nature BME / IEEE TBME 最新成果...',
        ],
        confs: [
            { key: 'nature biomedical engineering', label: 'Nat. BME',         color: '#e11d48' },
            { key: 'ieee tbme',                    label: 'IEEE TBME',         color: '#be123c' },
            { key: 'embc',                         label: 'EMBC',              color: '#9f1239' },
            { key: 'tnsre',                        label: 'TNSRE',             color: '#0ea5e9' },
        ],
        topics: [
            'Wearable', 'Tissue Engineering', 'Organ-on-Chip',
            'Prosthetics', 'Drug Delivery', 'Biosensor',
            'Neural Prosthesis', 'Cardiac Device', 'Rehabilitation',
            'ECG', 'Physiological Signal', 'Lab-on-Chip',
        ],
        synonyms: {
            'ecg': ['electrocardiogram', 'ekg'],
            'wearable': ['smart watch', 'fitness tracker'],
        },
    },
    music: {
        id: 'music', icon: '🎼', name: '音樂學', nameEn: 'Music & Audio Research',
        brand: 'Opus', arxivCat: 'cs.SD',
        promptRole: '音樂研究助理',
        accent: { from: '#7c3aed', to: '#0891b2', tint: 'rgba(124,58,237,0.18)' },
        loaderHints: [
            '連接 arXiv cs.SD 資料中...',
            '整理本週音樂／音訊論文（MIR / Symbolic Music / Generation / Source Separation 等）...',
            '對照 ISMIR / TISMIR 最新成果...',
        ],
        confs: [
            { key: 'ismir',                label: 'ISMIR',            color: '#7c3aed' },
            { key: 'tismir',               label: 'TISMIR',           color: '#6d28d9' },
            { key: 'icmc',                 label: 'ICMC',             color: '#5b21b6' },
            { key: 'dafx',                 label: 'DAFx',             color: '#0891b2' },
            { key: 'smc',                  label: 'SMC',              color: '#06b6d4' },
        ],
        topics: [
            'Music Information Retrieval', 'Symbolic Music',
            'Music Generation', 'Source Separation', 'Melody Extraction',
            'Chord Recognition', 'Beat Tracking', 'Music Emotion',
            'Musicology', 'Timbre', 'Audio Effects',
        ],
        synonyms: {
            'music information retrieval': ['mir', 'music ir'],
            'source separation': ['stem separation', 'demixing'],
        },
    },
    design: {
        id: 'design', icon: '🎨', name: '設計', nameEn: 'Design & UX',
        brand: 'Atelier', arxivCat: 'cs.HC',
        promptRole: '設計研究助理',
        accent: { from: '#f472b6', to: '#f59e0b', tint: 'rgba(244,114,182,0.18)' },
        loaderHints: [
            '連接 arXiv cs.HC 資料中（設計研究重疊）...',
            '整理本週設計論文（UX / Service Design / Co-Design / Generative Design 等）...',
            '對照 DIS / Design Studies 最新成果...',
        ],
        confs: [
            { key: 'dis',                 label: 'DIS',             color: '#f472b6' },
            { key: 'design studies',      label: 'Design Studies',  color: '#db2777' },
            { key: 'codesign',            label: 'CoDesign',        color: '#f59e0b' },
            { key: 'ixd',                 label: 'IxD',             color: '#f97316' },
        ],
        topics: [
            'User Experience', 'Service Design', 'Co-Design',
            'Participatory Design', 'Speculative Design',
            'Generative Design', 'Product Design', 'Industrial Design',
            'Visual Communication', 'Typography', 'Design Thinking',
        ],
        synonyms: {
            'user experience': ['ux', 'usability'],
            'generative design': ['computational design', 'parametric design'],
        },
    },
});

// ───── 大學全科延伸（v3：工程 / 醫療 / 商管 / 社會 / 藝術）─────
Object.assign(window.DISCIPLINES, {
    // ── 工程延伸 ─────────────────────────────────
    chemeng: {
        id: 'chemeng', icon: '⚗️', name: '化學工程', nameEn: 'Chemical Engineering',
        brand: 'Reactor', arxivCat: 'physics.chem-ph',
        promptRole: '化工研究助理',
        accent: { from: '#0d9488', to: '#f97316', tint: 'rgba(13,148,136,0.18)' },
        loaderHints: ['整理本週化工論文（Process / Reaction Eng / Separation 等）...'],
        confs: [
            { key: 'aiche journal', label: 'AIChE J.',   color: '#0d9488' },
            { key: 'chemical engineering science', label: 'Chem. Eng. Sci.', color: '#0f766e' },
            { key: 'industrial & engineering chemistry research', label: 'I&EC Res.', color: '#115e59' },
        ],
        topics: [
            'Process Engineering', 'Reaction Engineering', 'Separation',
            'Distillation', 'Catalyst', 'Transport Phenomena',
            'Polymer Processing', 'Biochemical Engineering', 'CO2 Capture',
        ],
        synonyms: { 'process engineering': ['unit operation', 'flowsheet'] },
    },
    aero: {
        id: 'aero', icon: '✈️', name: '航太工程', nameEn: 'Aerospace Engineering',
        brand: 'Aviatus', arxivCat: 'physics.flu-dyn',
        promptRole: '航太工程研究助理',
        accent: { from: '#1e3a8a', to: '#0891b2', tint: 'rgba(30,58,138,0.18)' },
        loaderHints: ['整理本週航太論文（Aerodynamics / Propulsion / UAV / Space 等）...'],
        confs: [
            { key: 'aiaa journal',   label: 'AIAA J.',     color: '#1e3a8a' },
            { key: 'journal of aircraft', label: 'J. of Aircraft', color: '#1e40af' },
            { key: 'journal of spacecraft and rockets', label: 'J. Spacecr. Rockets', color: '#0891b2' },
            { key: 'acta astronautica', label: 'Acta Astro.', color: '#0369a1' },
        ],
        topics: [
            'Aerodynamics', 'Propulsion', 'Flight Control', 'UAV',
            'Drone', 'Satellite', 'Orbit Mechanics', 'Hypersonic',
            'Structural Dynamics', 'Aeroelasticity', 'Space Exploration',
        ],
        synonyms: { 'uav': ['drone', 'quadcopter'], 'orbit mechanics': ['astrodynamics'] },
    },
    nuclear: {
        id: 'nuclear', icon: '☢️', name: '核能工程', nameEn: 'Nuclear Engineering',
        brand: 'Fission', arxivCat: 'physics.ins-det',
        promptRole: '核能工程研究助理',
        accent: { from: '#84cc16', to: '#a16207', tint: 'rgba(132,204,22,0.18)' },
        loaderHints: ['整理本週核工論文（Reactor / Fusion / Radiation / Shielding 等）...'],
        confs: [
            { key: 'nuclear engineering and design', label: 'Nucl. Eng. Des.', color: '#84cc16' },
            { key: 'journal of nuclear materials',   label: 'J. Nucl. Mat.',   color: '#65a30d' },
            { key: 'annals of nuclear energy',       label: 'Ann. Nucl. Energy', color: '#a16207' },
            { key: 'fusion engineering and design',  label: 'Fusion Eng. Des.', color: '#ca8a04' },
        ],
        topics: [
            'Reactor Physics', 'Fusion', 'Plasma Confinement', 'Fuel Cycle',
            'Radiation Shielding', 'Small Modular Reactor', 'Tokamak',
            'Monte Carlo Transport', 'Neutronics', 'Fuel Materials',
        ],
        synonyms: { 'fusion': ['iter', 'deuterium tritium'], 'smr': ['small modular reactor'] },
    },
    indus: {
        id: 'indus', icon: '🏭', name: '工業工程', nameEn: 'Industrial & Systems Engineering',
        brand: 'Optima', arxivCat: 'math.OC',
        promptRole: '工業工程研究助理',
        accent: { from: '#0f766e', to: '#64748b', tint: 'rgba(15,118,110,0.18)' },
        loaderHints: ['整理本週 IE / OR 論文（Scheduling / Supply Chain / Simulation 等）...'],
        confs: [
            { key: 'operations research',    label: 'Oper. Res.',    color: '#0f766e' },
            { key: 'management science',     label: 'Mgmt. Sci.',    color: '#115e59' },
            { key: 'iise transactions',      label: 'IISE Trans.',   color: '#134e4a' },
            { key: 'ejor',                   label: 'EJOR',          color: '#64748b' },
        ],
        topics: [
            'Operations Research', 'Scheduling', 'Supply Chain',
            'Queueing', 'Simulation', 'Logistics', 'Lean Manufacturing',
            'Quality Control', 'Facility Location', 'Inventory',
            'Stochastic Programming',
        ],
        synonyms: {
            'operations research': ['or', 'optimization'],
            'supply chain': ['scm', 'logistics network'],
        },
    },
    bioeng: {
        id: 'bioeng', icon: '🧪', name: '生物工程', nameEn: 'Bioengineering',
        brand: 'Bioworks', arxivCat: 'q-bio.TO',
        promptRole: '生物工程研究助理',
        accent: { from: '#16a34a', to: '#0ea5e9', tint: 'rgba(22,163,74,0.18)' },
        loaderHints: ['整理本週生物工程論文（Synthetic Bio / Tissue / Bioreactor 等）...'],
        confs: [
            { key: 'nature biotechnology',     label: 'Nat. Biotech.',  color: '#16a34a' },
            { key: 'metabolic engineering',    label: 'Metab. Eng.',    color: '#15803d' },
            { key: 'biotechnology and bioengineering', label: 'Biotech. Bioeng.', color: '#0ea5e9' },
            { key: 'acs synthetic biology',    label: 'ACS Syn. Bio.',  color: '#22c55e' },
        ],
        topics: [
            'Synthetic Biology', 'Metabolic Engineering', 'Tissue Engineering',
            'Biomaterial', 'Bioreactor', 'Directed Evolution',
            'Protein Engineering', 'Cell Therapy', 'Fermentation',
            'Gene Circuit',
        ],
        synonyms: { 'synthetic biology': ['synbio', 'genetic circuit'] },
    },

    // ── 自然延伸 ─────────────────────────────────
    envsci: {
        id: 'envsci', icon: '🌱', name: '環境科學', nameEn: 'Environmental Science',
        brand: 'Eco', arxivCat: 'physics.geo-ph',
        promptRole: '環境科學研究助理',
        accent: { from: '#15803d', to: '#0d9488', tint: 'rgba(21,128,61,0.18)' },
        loaderHints: ['整理本週環境論文（Pollution / Ecology / Sustainability 等）...'],
        confs: [
            { key: 'environmental science & technology', label: 'ES&T',             color: '#15803d' },
            { key: 'nature sustainability',              label: 'Nat. Sustain.',    color: '#166534' },
            { key: 'environmental research letters',     label: 'ERL',              color: '#16a34a' },
            { key: 'one earth',                          label: 'One Earth',        color: '#0d9488' },
        ],
        topics: [
            'Air Pollution', 'Water Quality', 'Ecology',
            'Biodiversity', 'Sustainability', 'Carbon Emission',
            'Life Cycle Assessment', 'Waste Management',
            'Ecosystem', 'Environmental Monitoring', 'Microplastic',
        ],
        synonyms: {
            'air pollution': ['pm2.5', 'particulate matter'],
            'life cycle assessment': ['lca'],
        },
    },
    agri: {
        id: 'agri', icon: '🌾', name: '農業科學', nameEn: 'Agricultural Science',
        brand: 'Terraform', arxivCat: 'q-bio.PE',
        promptRole: '農業科學研究助理',
        accent: { from: '#ca8a04', to: '#65a30d', tint: 'rgba(202,138,4,0.18)' },
        loaderHints: ['整理本週農業論文（Crop / Soil / Precision Ag / Plant Science 等）...'],
        confs: [
            { key: 'nature food',            label: 'Nat. Food',       color: '#ca8a04' },
            { key: 'field crops research',   label: 'Field Crops Res.', color: '#65a30d' },
            { key: 'agricultural systems',   label: 'Agric. Sys.',      color: '#a16207' },
            { key: 'plant cell',             label: 'Plant Cell',       color: '#854d0e' },
        ],
        topics: [
            'Precision Agriculture', 'Crop Yield', 'Plant Breeding',
            'Soil Science', 'Irrigation', 'Pest Management',
            'Phenotyping', 'Genomic Selection', 'Remote Sensing',
            'Agroforestry', 'Food Security',
        ],
        synonyms: {
            'precision agriculture': ['smart farming', 'digital agriculture'],
            'phenotyping': ['plant phenomics'],
        },
    },
    ocean: {
        id: 'ocean', icon: '🌊', name: '海洋科學', nameEn: 'Oceanography',
        brand: 'Abyss', arxivCat: 'physics.ao-ph',
        promptRole: '海洋科學研究助理',
        accent: { from: '#0369a1', to: '#0891b2', tint: 'rgba(3,105,161,0.18)' },
        loaderHints: ['整理本週海洋論文（Circulation / Marine Bio / Sea Level 等）...'],
        confs: [
            { key: 'journal of physical oceanography', label: 'JPO',         color: '#0369a1' },
            { key: 'ocean modelling',                  label: 'Ocean Mod.',  color: '#0284c7' },
            { key: 'deep-sea research',                label: 'Deep Sea Res.', color: '#075985' },
            { key: 'limnology and oceanography',       label: 'Limnol. Oceanogr.', color: '#0c4a6e' },
        ],
        topics: [
            'Ocean Circulation', 'Marine Ecology', 'Sea Level',
            'Biogeochemistry', 'Coral Reef', 'Estuary', 'Deep Sea',
            'Ocean Acidification', 'Fisheries', 'Coastal Engineering',
        ],
        synonyms: { 'ocean acidification': ['ph decrease', 'carbonate chemistry'] },
    },

    // ── 醫療／生命延伸 ────────────────────────
    pharma: {
        id: 'pharma', icon: '💊', name: '藥學', nameEn: 'Pharmacy & Pharmacology',
        brand: 'Pharma', arxivCat: 'q-bio.BM',
        promptRole: '藥學研究助理',
        accent: { from: '#db2777', to: '#0891b2', tint: 'rgba(219,39,119,0.18)' },
        loaderHints: ['整理本週藥學論文（Drug Discovery / Pharmacokinetics / Formulation 等）...'],
        confs: [
            { key: 'nature reviews drug discovery', label: 'Nat. Rev. Drug Disc.', color: '#db2777' },
            { key: 'journal of medicinal chemistry', label: 'J. Med. Chem.',        color: '#be185d' },
            { key: 'clinical pharmacology & therapeutics', label: 'Clin. Pharmacol. Ther.', color: '#9d174d' },
        ],
        topics: [
            'Drug Discovery', 'Pharmacokinetics', 'Pharmacodynamics',
            'Clinical Pharmacology', 'Formulation', 'Drug Delivery',
            'Pharmacogenomics', 'Antibiotic', 'Oncology',
            'Medicinal Chemistry', 'Biologics',
        ],
        synonyms: {
            'drug discovery': ['hit-to-lead', 'lead optimization'],
            'pharmacokinetics': ['pk/pd', 'adme'],
        },
    },
    nursing: {
        id: 'nursing', icon: '👩‍⚕️', name: '護理學', nameEn: 'Nursing & Care',
        brand: 'Caritas', arxivCat: 'q-bio.QM',
        promptRole: '護理研究助理',
        accent: { from: '#f472b6', to: '#0ea5e9', tint: 'rgba(244,114,182,0.18)' },
        loaderHints: ['整理本週護理論文（Patient Care / Clinical Outcome / Workforce 等）...'],
        confs: [
            { key: 'journal of nursing scholarship', label: 'J. Nurs. Scholar.', color: '#f472b6' },
            { key: 'nursing research',               label: 'Nurs. Res.',        color: '#db2777' },
            { key: 'international journal of nursing studies', label: 'Int. J. Nurs. Stud.', color: '#0ea5e9' },
        ],
        topics: [
            'Patient Outcome', 'Clinical Nursing', 'Geriatric Care',
            'Palliative Care', 'Pediatric Nursing', 'Mental Health',
            'Nursing Workforce', 'Telehealth', 'Patient Safety',
            'Evidence-Based Practice',
        ],
        synonyms: { 'telehealth': ['telemedicine', 'remote care'] },
    },
    dentistry: {
        id: 'dentistry', icon: '🦷', name: '牙醫學', nameEn: 'Dentistry',
        brand: 'Dentis', arxivCat: 'q-bio.QM',
        promptRole: '牙醫研究助理',
        accent: { from: '#0ea5e9', to: '#f472b6', tint: 'rgba(14,165,233,0.18)' },
        loaderHints: ['整理本週牙醫論文（Implant / Orthodontics / CBCT / Periodontal 等）...'],
        confs: [
            { key: 'journal of dental research', label: 'J. Dent. Res.',  color: '#0ea5e9' },
            { key: 'journal of periodontology',  label: 'J. Periodontol.', color: '#0284c7' },
            { key: 'clinical oral implants research', label: 'Clin. Oral Impl. Res.', color: '#075985' },
        ],
        topics: [
            'Dental Implant', 'Orthodontics', 'Periodontology',
            'Endodontics', 'Cariology', 'CBCT', 'Prosthodontics',
            'Oral Pathology', 'Dental Materials', 'Digital Dentistry',
        ],
        synonyms: { 'cbct': ['cone beam ct'] },
    },
    sports: {
        id: 'sports', icon: '🏃', name: '運動科學', nameEn: 'Sports Science & Kinesiology',
        brand: 'Kinesia', arxivCat: 'q-bio.QM',
        promptRole: '運動科學研究助理',
        accent: { from: '#ea580c', to: '#10b981', tint: 'rgba(234,88,12,0.18)' },
        loaderHints: ['整理本週運動科學論文（Biomechanics / Training / Nutrition / IMU 等）...'],
        confs: [
            { key: 'medicine & science in sports & exercise', label: 'MSSE',       color: '#ea580c' },
            { key: 'journal of biomechanics',                  label: 'J. Biomech.', color: '#c2410c' },
            { key: 'sports medicine',                          label: 'Sports Med.', color: '#10b981' },
        ],
        topics: [
            'Biomechanics', 'Exercise Physiology', 'Strength Training',
            'Endurance', 'Sports Nutrition', 'Injury Prevention',
            'Motion Capture', 'IMU Sensor', 'Rehabilitation',
            'Athlete Monitoring',
        ],
        synonyms: { 'imu sensor': ['inertial measurement unit', 'wearable sensor'] },
    },

    // ── 商業／管理 ────────────────────────────
    management: {
        id: 'management', icon: '💼', name: '企業管理', nameEn: 'Management',
        brand: 'Strato', arxivCat: 'econ.GN',
        promptRole: '管理研究助理',
        accent: { from: '#1e293b', to: '#ca8a04', tint: 'rgba(30,41,59,0.18)' },
        loaderHints: ['整理本週管理論文（Strategy / Organization / Innovation 等）...'],
        confs: [
            { key: 'strategic management journal', label: 'SMJ',               color: '#1e293b' },
            { key: 'academy of management journal', label: 'AMJ',              color: '#0f172a' },
            { key: 'administrative science quarterly', label: 'ASQ',           color: '#334155' },
            { key: 'organization science',             label: 'Org. Sci.',      color: '#ca8a04' },
        ],
        topics: [
            'Strategy', 'Corporate Governance', 'Innovation',
            'Entrepreneurship', 'Leadership', 'HR',
            'Organizational Behavior', 'M&A', 'Platform Strategy',
            'Dynamic Capabilities', 'Knowledge Management',
        ],
        synonyms: { 'hr': ['human resources', 'talent management'] },
    },
    marketing: {
        id: 'marketing', icon: '📣', name: '行銷', nameEn: 'Marketing',
        brand: 'Brand', arxivCat: 'econ.GN',
        promptRole: '行銷研究助理',
        accent: { from: '#ec4899', to: '#f59e0b', tint: 'rgba(236,72,153,0.18)' },
        loaderHints: ['整理本週行銷論文（Consumer / Digital / Brand / Pricing 等）...'],
        confs: [
            { key: 'journal of marketing',           label: 'J. of Marketing', color: '#ec4899' },
            { key: 'journal of consumer research',    label: 'JCR',            color: '#db2777' },
            { key: 'marketing science',              label: 'Mkt. Sci.',      color: '#be185d' },
            { key: 'journal of marketing research',  label: 'JMR',             color: '#f59e0b' },
        ],
        topics: [
            'Consumer Behavior', 'Brand', 'Digital Marketing',
            'Pricing', 'Advertising', 'Recommendation',
            'Social Media', 'Customer Lifetime Value',
            'A/B Testing', 'Conjoint Analysis', 'Choice Model',
        ],
        synonyms: {
            'a/b testing': ['randomized experiment', 'split test'],
            'customer lifetime value': ['clv', 'ltv'],
        },
    },
    accounting: {
        id: 'accounting', icon: '📒', name: '會計', nameEn: 'Accounting',
        brand: 'Ledger', arxivCat: 'econ.GN',
        promptRole: '會計研究助理',
        accent: { from: '#166534', to: '#1e293b', tint: 'rgba(22,101,52,0.18)' },
        loaderHints: ['整理本週會計論文（Financial Reporting / Audit / Disclosure / Tax 等）...'],
        confs: [
            { key: 'journal of accounting research',   label: 'JAR',               color: '#166534' },
            { key: 'the accounting review',            label: 'TAR',               color: '#15803d' },
            { key: 'journal of accounting and economics', label: 'JAE',            color: '#14532d' },
            { key: 'review of accounting studies',     label: 'RAST',              color: '#1e293b' },
        ],
        topics: [
            'Financial Reporting', 'Auditing', 'Disclosure',
            'Earnings Management', 'Tax', 'IFRS', 'GAAP',
            'Corporate Governance', 'ESG Reporting', 'Fraud Detection',
            'Textual Analysis',
        ],
        synonyms: { 'earnings management': ['accrual'], 'textual analysis': ['10-k', 'mda'] },
    },

    // ── 社會／人文延伸 ────────────────────────
    commun: {
        id: 'commun', icon: '📺', name: '傳播學', nameEn: 'Communication & Media',
        brand: 'Broadcast', arxivCat: 'cs.CY',
        promptRole: '傳播研究助理',
        accent: { from: '#7c3aed', to: '#f43f5e', tint: 'rgba(124,58,237,0.18)' },
        loaderHints: ['整理本週傳播論文（Media / Journalism / Platform / Misinformation 等）...'],
        confs: [
            { key: 'journal of communication',         label: 'J. of Commun.',      color: '#7c3aed' },
            { key: 'new media & society',              label: 'New Media & Soc.',   color: '#6d28d9' },
            { key: 'communication research',           label: 'Commun. Res.',       color: '#5b21b6' },
            { key: 'ica',                              label: 'ICA',                color: '#f43f5e' },
        ],
        topics: [
            'Media Effects', 'Journalism', 'Platform Governance',
            'Political Communication', 'Social Media',
            'Misinformation', 'Algorithmic Curation',
            'Public Opinion', 'Framing', 'Agenda Setting',
            'Computational Communication',
        ],
        synonyms: {
            'platform governance': ['content moderation'],
            'misinformation': ['disinformation', 'fake news'],
        },
    },
    geography: {
        id: 'geography', icon: '🗺️', name: '地理學', nameEn: 'Geography & Urban',
        brand: 'Cartos', arxivCat: 'physics.geo-ph',
        promptRole: '地理學研究助理',
        accent: { from: '#0284c7', to: '#78350f', tint: 'rgba(2,132,199,0.18)' },
        loaderHints: ['整理本週地理論文（GIS / Urban / Mobility / Spatial Analysis 等）...'],
        confs: [
            { key: 'annals of the american association of geographers', label: 'AAG Annals', color: '#0284c7' },
            { key: 'transactions in gis',             label: 'T-GIS',                    color: '#0369a1' },
            { key: 'urban studies',                   label: 'Urban Studies',             color: '#78350f' },
            { key: 'landscape and urban planning',    label: 'Landsc. Urban Plan.',      color: '#92400e' },
        ],
        topics: [
            'GIS', 'Spatial Analysis', 'Urban Planning', 'Mobility',
            'Remote Sensing', 'Cartography', 'Urban Form',
            'Segregation', 'Transportation', 'Smart City',
            'Land Use', 'Environmental Justice',
        ],
        synonyms: { 'gis': ['geographic information system'], 'urban form': ['urban morphology'] },
    },
    religion: {
        id: 'religion', icon: '🕊️', name: '宗教研究', nameEn: 'Religious Studies',
        brand: 'Sanctus', arxivCat: 'cs.CY',
        promptRole: '宗教研究助理',
        accent: { from: '#713f12', to: '#b45309', tint: 'rgba(113,63,18,0.18)' },
        loaderHints: ['整理本週宗教研究論文（Theology / Comparative / Ritual / Digital Religion 等）...'],
        confs: [
            { key: 'journal of religion',                label: 'J. of Religion',      color: '#713f12' },
            { key: 'religion',                           label: 'Religion',            color: '#92400e' },
            { key: 'journal for the scientific study of religion', label: 'JSSR',      color: '#b45309' },
        ],
        topics: [
            'Theology', 'Comparative Religion', 'Secularization',
            'Ritual', 'Buddhism', 'Christianity', 'Islam', 'Judaism',
            'Hinduism', 'Digital Religion', 'Religion and AI',
        ],
        synonyms: {},
    },

    // ── 藝術／人文延伸 ────────────────────────
    arthistory: {
        id: 'arthistory', icon: '🖼️', name: '藝術史', nameEn: 'Art History & Visual Studies',
        brand: 'Pinakotheke', arxivCat: 'cs.DL',
        promptRole: '藝術史研究助理',
        accent: { from: '#831843', to: '#92400e', tint: 'rgba(131,24,67,0.18)' },
        loaderHints: ['整理本週藝術史論文（Iconography / Digital Art History / Attribution 等）...'],
        confs: [
            { key: 'art bulletin',                 label: 'Art Bulletin',      color: '#831843' },
            { key: 'art history',                  label: 'Art History',       color: '#9d174d' },
            { key: 'journal of the warburg and courtauld institutes', label: 'JWCI', color: '#92400e' },
            { key: 'dhq',                          label: 'DHQ',               color: '#78350f' },
        ],
        topics: [
            'Iconography', 'Renaissance', 'Modern Art', 'Contemporary Art',
            'Visual Studies', 'Attribution', 'Museum Studies',
            'Digital Art History', 'Print Culture', 'Curatorial',
            'Non-Western Art',
        ],
        synonyms: { 'attribution': ['stylistic analysis', 'connoisseurship'] },
    },
    film: {
        id: 'film', icon: '🎬', name: '電影與媒體', nameEn: 'Film & Media Studies',
        brand: 'Cinema', arxivCat: 'cs.MM',
        promptRole: '電影研究助理',
        accent: { from: '#111827', to: '#eab308', tint: 'rgba(17,24,39,0.2)' },
        loaderHints: ['整理本週電影研究論文（Cinema Studies / Digital Media / Platform 等）...'],
        confs: [
            { key: 'cinema journal',           label: 'Cinema J.',          color: '#111827' },
            { key: 'screen',                   label: 'Screen',             color: '#1f2937' },
            { key: 'film quarterly',           label: 'Film Quart.',        color: '#374151' },
            { key: 'journal of film and video', label: 'JFV',               color: '#eab308' },
        ],
        topics: [
            'Cinema Studies', 'Genre', 'Auteur', 'Film Theory',
            'Visual Effects', 'Streaming Platform', 'Documentary',
            'Animation', 'Virtual Production', 'Computational Cinema',
        ],
        synonyms: { 'visual effects': ['vfx'] },
    },
    theater: {
        id: 'theater', icon: '🎭', name: '劇場表演', nameEn: 'Theater & Performance',
        brand: 'Proskenion', arxivCat: 'cs.HC',
        promptRole: '劇場研究助理',
        accent: { from: '#6b21a8', to: '#dc2626', tint: 'rgba(107,33,168,0.18)' },
        loaderHints: ['整理本週表演藝術論文（Drama / Dance / Embodiment / Immersive 等）...'],
        confs: [
            { key: 'theatre journal',        label: 'Theatre J.',      color: '#6b21a8' },
            { key: 'tdr',                    label: 'TDR',             color: '#7e22ce' },
            { key: 'performance research',   label: 'Perf. Research',  color: '#9333ea' },
            { key: 'dance research journal', label: 'Dance Res. J.',   color: '#dc2626' },
        ],
        topics: [
            'Drama', 'Performance Studies', 'Dance', 'Choreography',
            'Immersive Theatre', 'Acting', 'Playwriting', 'Dramaturgy',
            'Embodiment', 'Motion Capture Performance', 'VR Performance',
        ],
        synonyms: {},
    },
    architecture: {
        id: 'architecture', icon: '🏛️', name: '建築學', nameEn: 'Architecture',
        brand: 'Archon', arxivCat: 'cs.CG',
        promptRole: '建築研究助理',
        accent: { from: '#57534e', to: '#0891b2', tint: 'rgba(87,83,78,0.18)' },
        loaderHints: ['整理本週建築論文（Parametric / Sustainability / Urban / BIM 等）...'],
        confs: [
            { key: 'journal of architectural education', label: 'JAE',            color: '#57534e' },
            { key: 'architectural design',              label: 'AD',              color: '#44403c' },
            { key: 'automation in construction',        label: 'Autom. Constr.',  color: '#0891b2' },
            { key: 'building and environment',          label: 'Build. Environ.', color: '#155e75' },
        ],
        topics: [
            'Parametric Design', 'BIM', 'Sustainability',
            'Architectural Theory', 'Computational Design',
            'Urban Design', 'Energy Performance', 'Daylighting',
            'Facade', 'Generative Design', 'Digital Fabrication',
        ],
        synonyms: { 'bim': ['building information modeling'] },
    },
});

// ───── 類別分組（picker 顯示用）─────
window.DISCIPLINE_CATEGORIES = [
    { id: 'computing',   name: '電腦科學',   nameEn: 'Computing',             icon: '💻',
      ids: ['cv', 'nlp', 'ml', 'ai', 'robotics', 'graphics',
            'security', 'systems', 'db', 'hci', 'ir', 'speech'] },
    { id: 'math_stats',  name: '數理統計',   nameEn: 'Math & Statistics',     icon: '∑',
      ids: ['math', 'stats'] },
    { id: 'natural',     name: '自然科學',   nameEn: 'Natural Sciences',      icon: '⚛️',
      ids: ['physics', 'astro', 'quantum', 'chem', 'bio', 'neuro',
            'earth', 'climate', 'envsci', 'ocean', 'agri'] },
    { id: 'engineering', name: '工程科學',   nameEn: 'Engineering',           icon: '⚙️',
      ids: ['eess', 'materials', 'mecheng', 'civil',
            'chemeng', 'aero', 'nuclear', 'indus', 'bioeng'] },
    { id: 'medical',     name: '醫療生命',   nameEn: 'Medical & Life',        icon: '🩺',
      ids: ['medimg', 'pubhealth', 'biomed',
            'pharma', 'nursing', 'dentistry', 'sports'] },
    { id: 'business',    name: '商業管理',   nameEn: 'Business & Economics',  icon: '💼',
      ids: ['econ', 'finance', 'management', 'marketing', 'accounting'] },
    { id: 'social',      name: '社會科學',   nameEn: 'Social Sciences',       icon: '🏛️',
      ids: ['psychology', 'sociology', 'political', 'anthro',
            'commun', 'geography'] },
    { id: 'humanities',  name: '人文學科',   nameEn: 'Humanities',            icon: '📜',
      ids: ['philosophy', 'linguistics', 'history', 'literature', 'religion'] },
    { id: 'law_edu',     name: '法律教育',   nameEn: 'Law & Education',       icon: '⚖️',
      ids: ['law', 'education'] },
    { id: 'arts',        name: '藝術設計',   nameEn: 'Arts & Design',         icon: '🎨',
      ids: ['music', 'design', 'arthistory', 'film', 'theater', 'architecture'] },
];

// 預設顯示順序：依類別展開（picker 也照此順）
window.DISCIPLINE_ORDER = window.DISCIPLINE_CATEGORIES.flatMap(c => c.ids);

window.getActiveDiscipline = function () {
    const saved = localStorage.getItem('visionary_discipline');
    if (saved && window.DISCIPLINES[saved]) return window.DISCIPLINES[saved];
    return null;
};

window.setActiveDiscipline = function (id) {
    if (!window.DISCIPLINES[id]) return;
    localStorage.setItem('visionary_discipline', id);
};

// ── 跨領域 Bridge Papers（PR#3）─────────────────────────────────
// 為每個領域建立低雜訊關鍵字集合（topics + synonyms），並把常見縮寫剔除
const _BRIDGE_STOP = new Set([
    'all', 'agent', 'ml', 'ai', 'rl', 'vr', 'ar', 'bci', 'cnn', 'rnn',
    'nlp', 'cv', 'qc', 'did', 'iv', 'gw', '5g', '6g', '3d', 'cot',
    'llm', 'gpt', 'dft', 'evaluation', 'benchmark', 'optimization',
    'representation learning', 'reinforcement learning', 'transformer',
    'attention', 'generalization', 'diffusion', 'diffusion model',
    'self-supervised', 'contrastive',
]);
function _bridgeKeyword(raw) {
    const k = String(raw || '').toLowerCase().trim();
    if (!k || k.length < 3) return null;
    if (_BRIDGE_STOP.has(k)) return null;
    return k;
}

let _BRIDGE_INDEX = null;
window.buildDisciplineIndex = function () {
    if (_BRIDGE_INDEX) return _BRIDGE_INDEX;
    const idx = {};
    for (const [id, d] of Object.entries(window.DISCIPLINES || {})) {
        const kws = new Set();
        (d.topics || []).forEach(t => { const k = _bridgeKeyword(t); if (k) kws.add(k); });
        for (const arr of Object.values(d.synonyms || {})) {
            (arr || []).forEach(s => { const k = _bridgeKeyword(s); if (k) kws.add(k); });
        }
        (d.confs || []).forEach(c => {
            const k = _bridgeKeyword(c.label);
            // 只納入長標籤（避免 CVPR/ICML 類 4 字縮寫爆炸）
            if (k && k.length >= 5) kws.add(k);
        });
        idx[id] = { id, icon: d.icon, name: d.name, kws };
    }
    _BRIDGE_INDEX = idx;
    return idx;
};

// 回傳論文命中的 discipline id 陣列（title+summary 任一命中該領域任一關鍵字即計一次）
window.detectBridgeDisciplines = function (paper) {
    const idx = window.buildDisciplineIndex();
    const tLc = paper._titleLc || String(paper.title || '').toLowerCase();
    const sLc = paper._summaryLc || String(paper.summary || '').toLowerCase();
    const hay = tLc + ' ' + sLc;
    const hits = [];
    for (const [id, entry] of Object.entries(idx)) {
        let hit = false;
        for (const k of entry.kws) {
            if (hay.includes(k)) { hit = true; break; }
        }
        if (hit) hits.push(id);
    }
    return hits;
};

// ── 多領域追蹤清單（使用者可勾選多個領域，PR#3 onboarding）────
const TRACKS_KEY = 'visionary_tracks_v1';
window.getTracks = function () {
    try {
        const arr = JSON.parse(localStorage.getItem(TRACKS_KEY) || '[]');
        return Array.isArray(arr) ? arr.filter(id => !!window.DISCIPLINES[id]) : [];
    } catch (e) { return []; }
};
window.setTracks = function (ids) {
    const clean = (ids || []).filter(id => !!window.DISCIPLINES[id]);
    localStorage.setItem(TRACKS_KEY, JSON.stringify(clean));
};
