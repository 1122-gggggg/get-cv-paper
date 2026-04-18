# Scholarly Web · v2 和紙 washi edition

Native-v2 React recreation of the main Scholarly dashboard, plus three standalone supplementary screens.

## Files

| File | What it is |
|---|---|
| `index.html` + `App.jsx` + `style.css` | Main dashboard — sidebar, filter chips, search + sort header, paper grid, discipline picker |
| `login.html` | Split-panel login — marketing left, Google SSO + guest right |
| `empty-state.html` | "条件に合う論文が見つかりません" — illustration + mustard suggestion block + 3 action cards |
| `note-modal.html` | Paper-notes modal — ruled-paper textarea, tag chips, tabs (筆記 / 引用フラグメント / 関連論文) |

All four screens import `../../colors_and_type.v2.css` directly — no build step.

## Design notes

**Motifs used across screens**
- 3px top page-rule (`--accent-gradient-wide` — mustard → persimmon → vermillion → plum)
- 印 hanko seal (red square next to primary titles)
- Paper-grain background (two radial-gradient dot layers)
- Japanese captions above Chinese/English titles (疎組 `letter-spacing: 0.3em`)
- Dashed separators inside cards, solid borders around cards
- Yamabuki (`--mustard`) as primary accent, everywhere — buttons, highlight fills, filter-active borders

**Signature washi details**
- **Login**: serif wordmark + vermillion 印 + feature marks as small ink-block icons (要 / 印 / 雲)
- **Empty state**: vertical 学術·論文·研究·考察 kanji as a watermark down the left edge; 🔭 telescope in a dashed mustard circle with a red 空 seal
- **Note modal**: textarea painted with horizontal rule-lines (like 原稿用紙 / notebook paper); save button has the characteristic 2px offset shadow (`2px 2px 0 var(--mustard-deep)`)

## What's mocked vs. what's real

These are cosmetic mocks — no form submission, no real auth, no textarea persistence. They exist to:
1. Show the v2 system handles edge-case surfaces beyond the main grid
2. Give Claude Code concrete reference when rebuilding these flows in production

## Typography reminders

- Display / logo: **Noto Serif JP** (700)
- Body: **Zen Kaku Gothic New** (400–500)
- Soft labels / Japanese captions: **Zen Maru Gothic** (500)
- Mono: **JetBrains Mono** (400–600)
- Japanese body text: `letter-spacing: 0.03em`, labels up to `0.3em`
- Enable `font-feature-settings: "palt" 1` for proportional JP metrics
