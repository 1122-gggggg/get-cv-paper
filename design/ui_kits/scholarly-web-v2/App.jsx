// Scholarly UI kit v2 — "和紙 Washi" edition
// Warm paper background · ink foreground · Japanese-academic-casual
// Designed for iteration; paired with colors_and_type.v2.css

const { useState, useEffect } = React;

const DISCIPLINES_V2 = [
  { id: 'cv',    emoji: '👁️', name: '電腦視覺',     jp: 'コンピュータビジョン', brand: 'Visionary',  arxiv: 'cs.CV' },
  { id: 'nlp',   emoji: '💬', name: '自然語言處理', jp: '自然言語処理',         brand: 'Lexical',    arxiv: 'cs.CL' },
  { id: 'ml',    emoji: '🧠', name: '機器學習',     jp: '機械学習',             brand: 'Gradient',   arxiv: 'cs.LG' },
  { id: 'ai',    emoji: '🤖', name: '通用 AI',       jp: '人工知能',             brand: 'Cogito',     arxiv: 'cs.AI' },
  { id: 'robot', emoji: '🦾', name: '機器人',       jp: 'ロボティクス',         brand: 'Kinematic',  arxiv: 'cs.RO' },
  { id: 'gr',    emoji: '🎨', name: '圖形學',       jp: 'グラフィックス',       brand: 'Pixel',      arxiv: 'cs.GR' },
  { id: 'sec',   emoji: '🔒', name: '資訊安全',     jp: 'セキュリティ',         brand: 'Cipher',     arxiv: 'cs.CR' },
  { id: 'hci',   emoji: '🖱️', name: '人機互動',     jp: 'HCI',                  brand: 'Tuple',      arxiv: 'cs.HC' },
  { id: 'math',  emoji: '∑',  name: '數學',         jp: '数学',                 brand: 'Axiom',      arxiv: 'math' },
];

const SAMPLE = [
  { id:'p1', venue:'CVPR', title:'Efficient Diffusion Training via Two-Stage Distillation',
    authors:['Y. Zhang','W. Chen','H. Liu'], date:'2026-04-15', citations:1284, hf:428, signal:8.7,
    tags:['Diffusion','Distillation'], starred:true, read:false,
    zh:{problem:'低リソースで高品質な拡散モデルを学習する', method:'二段階蒸留 + 再パラメータ化 UNet',
        contrib:'訓練コスト 3.8× 削減 · FID 維持', result:'ImageNet 256² FID 2.18 (SOTA)'}},
  { id:'p2', venue:'ACL', title:'Reading Between the Layers: Vision-Language Alignment',
    authors:['S. Kim','A. Petrov'], date:'2026-04-14', citations:182, hf:56, signal:7.2,
    tags:['VLM','Probing'], starred:false, read:true,
    zh:{problem:'VLM はどの層で対齐するか', method:'20 個のプロービングタスク',
        contrib:'中間層が最も強く整合 (非最終層)', result:'CLIP-L 第 16 層 score 0.87'}},
  { id:'p3', venue:'NeurIPS', title:'Gaussian Splatting with Sparse Views',
    authors:['R. Nakamura','E. Torres'], date:'2026-04-12', citations:520, signal:6.9,
    tags:['3D','Splatting'], starred:false, read:false,
    zh:{problem:'稀疏視角下 3DGS 容易過擬合', method:'深度一致性 + 不確定度裁剪',
        contrib:'3~5 張即達密集 80% PSNR', result:'Mip-NeRF 360 sparse PSNR 24.3'}},
  { id:'p4', venue:'ICML', title:'On the Effectiveness of Pure MLPs at Scale',
    authors:['K. Ito','C. Dubois'], date:'2026-04-11', citations:96, signal:6.3,
    tags:['MLP','Scaling'], starred:true, read:false,
    zh:{problem:'MLP は transformer に匹敵できるか', method:'純深層 MLP + token-mixing',
        contrib:'首個達 90%+ IN-V top-1', result:'IN-V 90.2 / 1.4× 訓練'}},
  { id:'p5', venue:'ICLR', title:'Latent Video Diffusion at 48 FPS',
    authors:['G. Rossi','J. Park'], date:'2026-04-10', hf:1204, signal:7.8,
    tags:['Video','Speed'], starred:false, read:false,
    zh:{problem:'影片擴散推論太慢', method:'時序解耦 + 4-step ODE',
        contrib:'單卡 3090 達 48 FPS', result:'UCF-101 FVD 138 · 48 fps'}},
  { id:'p6', venue:'CVPR', title:'Tactile-Visual Policies from 40 Minutes of Demo',
    authors:['D. Okonkwo','Y. Bahri'], date:'2026-04-09', citations:44, signal:6.1,
    tags:['Robotics'], starred:false, read:false,
    zh:{problem:'機器人樣本效率差', method:'觸覺 + 視覺 token 聯合編碼',
        contrib:'40 分鐘數據學會插電源', result:'成功率 92% / baseline 34%'}},
];

const VenueBadge = ({ v }) => {
  const c = {CVPR:'#2e4d7b', ACL:'#c1440e', NeurIPS:'#6b8e23', ICML:'#8a3a5f', ICLR:'#e8711a'}[v] || '#2a2418';
  return <span style={{display:'inline-block',padding:'3px 10px',borderRadius:3,fontFamily:'var(--font-display)',fontSize:11,fontWeight:700,letterSpacing:'0.1em',color:'#fff',background:c}}>{v}</span>;
};

const Sidebar = ({ discipline, filter, setFilter, onPicker }) => {
  const cats = [
    {id:'all',label:'All'},
    {id:'favorites',label:'⭐ 收藏夾'},
    {id:'hf',label:'🤗 HF Daily'},
    {id:'conf',label:'🏆 頂會嚴選', conf:true},
    {id:'diffusion',label:'Diffusion'},
    {id:'3d',label:'3D'},
    {id:'video',label:'Video'},
  ];
  return (
    <aside style={{width:260,padding:'28px 20px',borderRight:'1px solid var(--card-border)',background:'var(--paper-shade)',display:'flex',flexDirection:'column',gap:22,position:'sticky',top:0,minHeight:'100vh'}}>
      <div>
        <div className="jp-label" style={{marginBottom:4}}>論文追跡 · paper tracker</div>
        <div style={{display:'flex',alignItems:'baseline',gap:8}}>
          <h1 style={{fontFamily:'var(--font-display)',fontWeight:700,fontSize:'2rem',letterSpacing:'0.02em',lineHeight:1,color:'var(--ink)'}}>Scholarly<span style={{color:'var(--vermillion)'}}>.</span></h1>
          <span className="ds-hanko">印</span>
        </div>
      </div>
      <button onClick={onPicker} style={{display:'flex',alignItems:'center',justifyContent:'space-between',padding:'11px 14px',background:'var(--card-bg)',border:'1px solid var(--card-border)',borderRadius:10,color:'var(--ink)',fontFamily:'var(--font-body)',fontSize:13,cursor:'pointer'}}>
        <span style={{display:'inline-flex',alignItems:'center',gap:8}}><span style={{fontSize:18}}>{discipline.emoji}</span><b style={{fontFamily:'var(--font-display)'}}>{discipline.name}</b></span>
        <span style={{color:'var(--ink-mute)'}}>▾</span>
      </button>
      <div>
        <div className="jp-label" style={{marginBottom:10}}>けんさく　しぼりこみ</div>
        <div style={{display:'flex',flexDirection:'column',gap:6}}>
          {cats.map(c => {
            const active = filter === c.id;
            return (
              <button key={c.id} onClick={()=>setFilter(c.id)}
                style={{
                  textAlign:'left',padding:'8px 14px',borderRadius:999,cursor:'pointer',
                  fontFamily:'var(--font-body)',fontSize:13,letterSpacing:'0.02em',
                  background: active ? (c.conf ? 'var(--persimmon-soft)' : 'var(--ink)') : 'var(--card-bg)',
                  color: active ? (c.conf ? '#b35a0c' : 'var(--paper)') : 'var(--ink-soft)',
                  border: active ? (c.conf ? '1px solid var(--persimmon)' : '1px solid var(--ink)') : '1px solid var(--card-border)',
                  fontWeight: active ? 600 : 400,
                }}>{c.label}</button>
            );
          })}
          <button style={{textAlign:'left',padding:'8px 14px',borderRadius:999,border:'1.5px dashed var(--ink-pale)',background:'transparent',color:'var(--ink-mute)',fontFamily:'var(--font-soft)',fontSize:13,cursor:'pointer'}}>＋ 主題を追加</button>
        </div>
      </div>
      <div style={{marginTop:'auto',paddingTop:20,borderTop:'1px solid var(--card-border)',fontSize:11,color:'var(--ink-mute)',display:'flex',flexDirection:'column',gap:8,fontFamily:'var(--font-body)'}}>
        <div><kbd className="ds-kbd">J</kbd> <kbd className="ds-kbd">K</kbd> 前へ / 次へ</div>
        <div><kbd className="ds-kbd">F</kbd> 收藏 · <kbd className="ds-kbd">R</kbd> 已讀 · <kbd className="ds-kbd">N</kbd> 筆記</div>
      </div>
    </aside>
  );
};

const Header = ({ sort, setSort, query, setQuery }) => {
  const [open, setOpen] = useState(false);
  const sorts = [
    {v:'signal',label:'✨ Signal 推薦',sub:'Signal'},
    {v:'latest',label:'⚡ 本日最新',sub:'Latest'},
    {v:'hot_week',label:'🔥 本週熱門',sub:'Trending'},
    {v:'citations',label:'📊 引用最多',sub:'Most Cited'},
  ];
  const cur = sorts.find(s=>s.v===sort) || sorts[0];
  return (
    <header style={{display:'flex',flexDirection:'column',gap:16,marginBottom:28}}>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'baseline'}}>
        <div>
          <div className="jp-label">こんにちは</div>
          <h2 style={{fontFamily:'var(--font-display)',fontWeight:700,fontSize:'1.5rem',color:'var(--ink)',letterSpacing:'0.02em',marginTop:4}}>今日の注目 <span style={{color:'var(--vermillion)',fontSize:'0.7em'}}>·</span> <span style={{fontFamily:'var(--font-soft)',fontSize:'0.85em',color:'var(--ink-mute)'}}>Today's papers</span></h2>
        </div>
        <div style={{display:'flex',gap:6}}>
          <button style={{padding:'6px 12px',borderRadius:8,background:'var(--card-bg)',border:'1px solid var(--card-border)',color:'var(--ink-soft)',fontSize:12,fontFamily:'var(--font-body)',cursor:'pointer'}}>⬇ JSON</button>
          <button style={{padding:'6px 12px',borderRadius:8,background:'var(--card-bg)',border:'1px solid var(--card-border)',color:'var(--ink-soft)',fontSize:12,fontFamily:'var(--font-body)',cursor:'pointer'}}>G 登入</button>
        </div>
      </div>
      <div style={{display:'flex',gap:10,alignItems:'center',flexWrap:'wrap'}}>
        <div style={{position:'relative',flex:1,minWidth:280}}>
          <svg width="16" height="16" viewBox="0 0 24 24" style={{position:'absolute',left:14,top:'50%',transform:'translateY(-50%)',color:'var(--ink-mute)'}}><circle cx="11" cy="11" r="8" fill="none" stroke="currentColor" strokeWidth="2"/><line x1="21" y1="21" x2="16.65" y2="16.65" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></svg>
          <input value={query} onChange={e=>setQuery(e.target.value)} placeholder="タイトル・著者・キーワードで検索（Enter で全庫）"
            style={{width:'100%',background:'var(--card-bg)',border:'1px solid var(--card-border)',borderRadius:10,padding:'11px 16px 11px 40px',color:'var(--ink)',fontFamily:'var(--font-body)',fontSize:14,outline:'none'}}/>
        </div>
        <div style={{position:'relative'}}>
          <button onClick={()=>setOpen(o=>!o)} style={{display:'inline-flex',alignItems:'center',gap:8,padding:'10px 16px',background:'var(--card-bg)',border:'1px solid var(--card-border)',borderRadius:10,color:'var(--ink)',fontFamily:'var(--font-body)',fontSize:13,cursor:'pointer'}}>
            <span>{cur.label}</span><span style={{color:'var(--ink-mute)'}}>▾</span>
          </button>
          {open && (
            <div style={{position:'absolute',top:'calc(100% + 6px)',right:0,zIndex:20,background:'var(--card-bg)',border:'1px solid var(--card-border)',borderRadius:10,padding:6,minWidth:220,boxShadow:'var(--shadow-modal)'}}>
              {sorts.map(s => (
                <button key={s.v} onClick={()=>{setSort(s.v);setOpen(false);}}
                  style={{display:'flex',justifyContent:'space-between',alignItems:'center',width:'100%',padding:'8px 12px',borderRadius:6,border:'none',background: s.v===sort?'var(--mustard-soft)':'transparent',color:'var(--ink)',fontFamily:'var(--font-body)',fontSize:13,cursor:'pointer',textAlign:'left'}}>
                  <span>{s.label}</span>
                  <span className="ds-mono" style={{fontSize:10,opacity:0.6}}>{s.sub}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </header>
  );
};

const PaperCard = ({ p, onStar, onRead }) => (
  <article style={{background:'var(--card-bg)',border:'1px solid var(--card-border)',borderRadius:14,padding:'20px 22px',position:'relative',boxShadow:'var(--shadow-card)',display:'flex',flexDirection:'column',gap:10,transition:'all 0.28s var(--ease-brand)'}}>
    <button onClick={()=>onStar(p.id)} title="収藏"
      style={{position:'absolute',top:12,right:12,background:'none',border:'none',cursor:'pointer',color:p.starred?'var(--vermillion)':'var(--ink-pale)',fontSize:18,lineHeight:1}}>{p.starred?'★':'☆'}</button>
    <div style={{display:'flex',alignItems:'center',gap:8}}>
      <VenueBadge v={p.venue}/>
      {p.signal != null && <span className="ds-mono" style={{fontSize:11,color:'var(--mustard-deep)'}}>✨ {p.signal.toFixed(1)}</span>}
      {p.read && <span style={{fontSize:10,color:'var(--matcha)',border:'1px solid var(--matcha)',borderRadius:3,padding:'1px 6px',fontFamily:'var(--font-soft)',letterSpacing:'0.1em'}}>既読</span>}
    </div>
    <div style={{background:'#fff6cf',borderLeft:'3px solid var(--mustard)',borderRadius:'0 8px 8px 0',padding:'10px 14px',fontSize:12.5,lineHeight:1.85,color:'var(--ink-soft)'}}>
      <span style={{fontFamily:'var(--font-soft)',fontSize:10,fontWeight:700,letterSpacing:'0.24em',color:'#8a5f0a',display:'block',marginBottom:4}}>🤖 AI 重點分析</span>
      🔍 {p.zh.problem}<br/>⚙️ {p.zh.method}<br/>🏆 {p.zh.contrib}<br/>📊 {p.zh.result}
    </div>
    <h3 style={{fontFamily:'var(--font-display)',fontWeight:700,fontSize:15.5,lineHeight:1.55,color:'var(--ink)',paddingRight:24,letterSpacing:'0.01em'}}>{p.title}</h3>
    <p style={{fontFamily:'var(--font-display)',fontStyle:'italic',fontSize:12,color:'#8a6d3a'}}>{p.authors.join(', ')}</p>
    <div style={{display:'flex',gap:6,flexWrap:'wrap'}}>
      {(p.tags||[]).map(t => <span key={t} style={{padding:'2px 10px',borderRadius:999,fontSize:11,background:'var(--mustard-soft)',border:'1px solid var(--mustard)',color:'#8a5f0a',fontFamily:'var(--font-body)'}}>{t}</span>)}
    </div>
    <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',borderTop:'1px dashed var(--card-border)',paddingTop:12,marginTop:'auto',gap:8,flexWrap:'wrap'}}>
      <span className="ds-mono" style={{fontSize:11,color:'var(--ink-mute)'}}>{p.date}</span>
      {p.citations != null && <span style={{padding:'2px 8px',borderRadius:999,fontSize:11,color:'#557019',background:'var(--matcha-soft)',border:'1px solid #9cb45a',fontFamily:'var(--font-mono)'}}>📊 {p.citations.toLocaleString()}</span>}
      {p.hf != null && <span style={{padding:'2px 8px',borderRadius:999,fontSize:11,color:'#8a5f0a',background:'#fff1b8',border:'1px solid var(--mustard)'}}>🤗 {p.hf}</span>}
      <button onClick={()=>onRead(p.id)} style={{padding:'3px 10px',borderRadius:999,fontSize:11,color:'var(--plum)',background:'var(--plum-soft)',border:'1px solid #b06080',cursor:'pointer',fontFamily:'var(--font-body)'}}>{p.read?'既読に戻す':'既読にする'}</button>
      <a href="#" style={{color:'var(--indigo)',fontWeight:600,fontSize:12,textDecoration:'none',fontFamily:'var(--font-body)',marginLeft:'auto'}}>読む ↗</a>
    </div>
  </article>
);

const Picker = ({ open, active, onClose, onSelect }) => {
  if (!open) return null;
  return (
    <div style={{position:'fixed',inset:0,zIndex:100,display:'flex',alignItems:'center',justifyContent:'center'}}>
      <div onClick={onClose} style={{position:'absolute',inset:0,background:'rgba(42,36,24,0.4)',backdropFilter:'blur(2px)'}}/>
      <div style={{position:'relative',background:'var(--card-bg)',border:'1px solid var(--card-border)',borderRadius:14,padding:32,maxWidth:820,width:'calc(100% - 48px)',maxHeight:'80vh',overflow:'auto',boxShadow:'var(--shadow-modal)'}}>
        <div className="jp-label" style={{marginBottom:4}}>けんきゅう　りょういき</div>
        <h2 style={{fontFamily:'var(--font-display)',fontWeight:700,fontSize:'1.5rem',color:'var(--ink)',marginBottom:6,letterSpacing:'0.02em'}}>研究分野を選んでください</h2>
        <p style={{color:'var(--ink-mute)',fontSize:13,lineHeight:1.8,marginBottom:20,fontFamily:'var(--font-body)'}}>主分野によって arXiv カテゴリと頂会主題が読み込まれます。2 つ以上にまたがる論文は 🌉 Bridge としてマークされます。</p>
        <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill, minmax(180px, 1fr))',gap:10}}>
          {DISCIPLINES_V2.map(d => (
            <div key={d.id} onClick={()=>onSelect(d)}
              style={{padding:'16px 14px',borderRadius:12,cursor:'pointer',transition:'all 0.2s var(--ease-brand)',
                background: active===d.id ? '#fff6cf' : 'var(--paper-shade)',
                border: active===d.id ? '1.5px solid var(--mustard)' : '1px solid var(--card-border)'}}>
              <div style={{fontSize:26,marginBottom:4}}>{d.emoji}</div>
              <div style={{fontFamily:'var(--font-display)',fontSize:15,fontWeight:700,color:'var(--ink)'}}>{d.name}</div>
              <div style={{fontFamily:'var(--font-soft)',fontSize:11,color:'var(--ink-mute)',letterSpacing:'0.06em'}}>{d.jp} · {d.brand}</div>
              <div className="ds-mono" style={{fontSize:10,color:'var(--plum)',marginTop:6}}>{d.arxiv}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

const App = () => {
  const [papers, setPapers] = useState(SAMPLE);
  const [filter, setFilter] = useState('all');
  const [sort, setSort] = useState('signal');
  const [query, setQuery] = useState('');
  const [pick, setPick] = useState(false);
  const [disc, setDisc] = useState(DISCIPLINES_V2[0]);
  const star = id => setPapers(ps => ps.map(p => p.id===id?{...p,starred:!p.starred}:p));
  const read = id => setPapers(ps => ps.map(p => p.id===id?{...p,read:!p.read}:p));
  const shown = papers
    .filter(p => filter==='all' ? true : filter==='favorites' ? p.starred : filter==='hf' ? p.hf != null : filter==='conf' ? !!p.venue : (p.tags||[]).some(t => t.toLowerCase().includes(filter)))
    .filter(p => !query.trim() || p.title.toLowerCase().includes(query.toLowerCase()) || p.authors.join(' ').toLowerCase().includes(query.toLowerCase()))
    .sort((a,b) => sort==='signal' ? (b.signal||0)-(a.signal||0) : sort==='citations' ? (b.citations||0)-(a.citations||0) : b.date.localeCompare(a.date));
  return (
    <>
      <div style={{position:'fixed',top:0,left:0,right:0,height:3,background:'linear-gradient(90deg,#e6b422,#e8711a 60%,#c1440e,#8a3a5f)',opacity:0.75,zIndex:200}}/>
      <div style={{display:'flex',minHeight:'100vh'}}>
        <Sidebar discipline={disc} filter={filter} setFilter={setFilter} onPicker={()=>setPick(true)}/>
        <div style={{flex:1,maxWidth:1280,padding:'36px 44px'}}>
          <Header sort={sort} setSort={setSort} query={query} setQuery={setQuery}/>
          {shown.length === 0 ? (
            <div style={{textAlign:'center',padding:'80px 20px'}}>
              <div style={{fontSize:48,marginBottom:12}}>🔭</div>
              <p style={{fontFamily:'var(--font-display)',fontSize:'1.3rem',fontWeight:700,color:'var(--ink)',marginBottom:8}}>条件に合う論文が見つかりません</p>
              <p style={{color:'var(--ink-mute)',fontSize:13,fontFamily:'var(--font-body)'}}>検索キーワードを変えるか、カテゴリを切り替えてみてください。</p>
            </div>
          ) : (
            <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill, minmax(340px, 1fr))',gap:'1.5rem'}}>
              {shown.map(p => <PaperCard key={p.id} p={p} onStar={star} onRead={read}/>)}
            </div>
          )}
        </div>
      </div>
      <Picker open={pick} active={disc.id} onClose={()=>setPick(false)} onSelect={d=>{setDisc(d);setPick(false);}}/>
    </>
  );
};

ReactDOM.createRoot(document.getElementById('root')).render(<App/>);
