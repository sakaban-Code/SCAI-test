# SCAI-Agent 公開網站 — 美編協作紀錄（唯一累積主檔）

> 用途：提供 GPT（美編／圖像軌）、Claude Code（工程／整合軌）、其他 AI 或人類接手本網站的視覺工作。本文必須保留從基準版、每輪美編、素材整合、錯誤與修正到目前上線狀態的完整過程。
> 建立日期：2026-08-07 · 工作分支：`main`
> 線上網站：https://sakaban-code.github.io/SCAI-test/
> GitHub：https://github.com/sakaban-Code/SCAI-test
> 部署方式：GitHub Pages（`main` 分支 `/docs` 目錄）；每週一 GitHub Actions 自動重建

## 文件維護規則（所有 AI 都必須遵守）

1. **本檔是唯一主紀錄。** 不得另建 `美編紀錄V2.md`、`新版.md` 或第二份交接檔；只能在本檔末端依日期續寫。
2. **要寫全過程，不只寫最後結果。** 每輪至少記錄：人類需求原文或忠實摘要、執行者、修改前狀態、實際修改檔案、實作內容、遇到的錯誤與原因、修正方法、驗證結果、Git commit、Pages 線上確認。
3. **每個 AI 都要署名。**（GPT／Claude Code／Codex／人類）；來源未明示時寫「來源紀錄未明示」。
4. **失敗也要寫，不覆寫歷史。** 舊判斷被修正時保留原記錄再加「後續修正」。
5. **紅線（§3）只能補充，不能刪除、弱化或改寫。**
6. **每次更新本檔。** 視覺、素材、部署方式變動須與程式碼同批提交。

### 每輪固定紀錄格式

```markdown
## YYYY-MM-DD｜本輪名稱

- 人類需求：
- 執行者：GPT／Claude Code／人類／來源紀錄未明示
- 修改前狀態：
- 修改檔案：
- 實作內容：
- 遇到的錯誤與原因：
- 修正方式：
- 驗證：
- Git commit：
- Pages 線上確認：
- 未完成與後續工作：
```

---

## 0. 給接手 AI 的話（先讀這段）

**運行地點與 GOLF 案（Streamlit）完全不同**：這是**純靜態單檔網站**，由 Python 腳本把模板＋六週 JSON 資料打包成 `docs/index.html`，掛在 GitHub Pages。沒有後端、沒有資料庫、沒有 session。

最重要的一條：**`docs/index.html` 是機器產物，絕對不要直接改它**——GitHub Actions 每週一會自動重新產生，直接改產物的美編會在下次重建時**整批消失**。美編一律改 **`src/site_template.html`**（模板），改完由 `build_site.py` 重新產出。

**目前分工（2026-08-07 人類定案）**：
- **Claude Code**：版面／字體／間距／配色系統、程式整合、重建、驗證、推送（第 1 輪已完成，見 §7）
- **GPT**：圖像素材（logo／OG 分享圖／裝飾底紋）與大膽視覺方向提案。**只交圖檔或方向稿，不改程式碼**；成品由 Claude Code 嵌入
- 素材檔請交付：PNG（透明背景）或 SVG；建議置於 `docs/assets/`（此目錄內的圖檔是素材不是產物，不會被重建覆蓋——`build_site.py` 只覆寫 `docs/index.html`）

## 1. 這個網站是什麼

SCAI-Agent（元智大學管理學院競賽，指導教授謝志宏、陳懷傑，團隊海香菇）的**公開成果門面**：每週自動判定半導體產業情境（雙軸 × 四情境）、校準 25 項 KDF 權重、輸出欣銓（半導體測試廠）專屬的風險雷達與觸發式規畫。受眾＝競賽評審、教授、組員。

設計目標排序：**可信 ＞ 專業好讀 ＞ 美**。這是戰略情報產品，不是行銷頁；GOLF 的企鵝路線在這裡不適用。

## 2. 技術架構與檔案導覽

```
data/weeks.json（六週資料）＋ kdf_config.json ＋ company_profile.json
＋ playbook.json ＋ kdf_definitions.json
        │
        ▼
src/build_site.py ──把 DATA 注入──► src/site_template.html 的 /*__DATA__*/ 佔位符
        │
        ▼
docs/index.html（自包含單檔，~82KB）──GitHub Pages──► 線上網站
```

| 檔案 | 角色 | 美編時 |
|---|---|---|
| `src/site_template.html` | 版面＋CSS＋渲染 JS | **主戰場** |
| `src/build_site.py` | 打包器 | 勿動 |
| `docs/index.html` | 機器產物 | **絕對勿直改** |
| `docs/assets/`（可新建） | 圖像素材 | GPT 素材放這裡 |
| `data/*.json` | 週資料與定義（凍結正本） | 勿動 |
| `dashboard/` | 內部儀表板（非公開門面） | 本協作不涉及 |
| `src/pipeline.py` 等 | 週報管線 | 本協作不涉及 |

cowork 端另有一份模板副本（`cowork/scripts/site_template.html`），由 Claude Code 負責保持同步；其他 AI 不用管它。

## 3. 紅線（美編時不可違反）

1. **`/*__DATA__*/` 佔位符**必須原樣存在於模板中（含前後空白格式），這是資料注入點。
2. **渲染 JS 綁定的 DOM 掛勾不可改名刪除**：`#main`、`#wsel`、`#wprev`、`#wnext`、`#gen`、`#cx`／`#ct`／`#ck`（三張 Chart.js canvas）、`#dimchips`、`#capx`、`#top`、`.secnav` 各 `href` 錨點與 section id（`overview/plan/risk/trend/events/trace/profile/method`）。CSS class 可改造，但改 HTML 結構須連 `render()` JS 一起改並全站驗證。
3. **內容誠實標示不可拿掉**：【推斷】chip、【待公司確認】標籤、footer 不確定性聲明、事件來源連結（原文 ↗）、Decision Trace 的 ✓/✗ 觸發依據。這些是憲法要求與提案承諾，不是裝飾。
4. **資料數值一律不可改**：X/Y 座標、KDF 權重、事件內容、公司數字全部來自 JSON，美編不碰資料。
5. **語言**：繁體中文；禁止中國用語（晶片≠芯片、光罩≠掩膜等）。
6. **方法論定義**（雙軸名稱、四情境名、25 KDF、五維分組）＝凍結正本，文字不可改寫。
7. **單檔自包含**：不得引入需要後端、localStorage 或建置工具鏈（npm/bundler）的方案。外部資源目前僅 Google Fonts（Noto Sans TC）與 cdnjs 的 Chart.js 4.4.1；新增外部依賴須先徵得人類同意。
8. **本 repo 是 public**：任何素材與文字不得含未公開數據或機密。

## 4. 目前設計系統（2026-08-07，第 1 輪後）

- **中性色**：暖白底 `#faf9f7`、卡片 `#fffefd`、墨黑 `#211f1c`、次級 `#4a4741`、弱化 `#8b867d`、框線 `#e8e4dd`
- **品牌色**：深陶土 `#a44a24`（hero 情境字、當週資料點、accent 專用——**不作資料序列色**）
- **語意色**：升/正 `#2f7050`、警示 `#a97b1f`、降/險 `#b03a30`
- **五維資料色**：`#38547a`（技術研發）`#357355`（企業競爭）`#b07a28`（全球供應鏈）`#6f5486`（政策營運）`#9c5058`（制度規範）——CSS 變數與 JS `DC` 陣列兩處必須同步
- **字體**：Noto Sans TC（400/500/600/700/900）；hero 情境字 900 字重 clamp(30–40px)；數字一律 `tabular-nums`
- **間距**：section 垂直 40px、卡片 22/24px、圓角 10px、極淡陰影 `--shadow`
- **動效**：僅「管線運行中」綠點呼吸（respect `prefers-reduced-motion`）；克制為原則

## 5. 如何跑起來與驗證

```powershell
# 重建網站（在 repo 根目錄）
python src/build_site.py        # 產出 docs/index.html
# 本機預覽
python -m http.server 8765 -d docs
# 推送 = 部署（Pages 約 1 分鐘後更新）
git add -A; git commit -m "說明"; git push
```

美編輪的 Definition of Done：

- [ ] `build_site.py` 執行成功，`/*__DATA__*/` 已被替換
- [ ] 六週資料都渲染（週次切換 ‹›、`#w{n}` hash 可用）
- [ ] 三張圖表正常（雙軸軌跡／五維趨勢／25 KDF 橫條＋維度篩選）
- [ ] 【推斷】chip、footer 聲明、事件來源連結、✓/✗ 觸發依據全部仍在
- [ ] 手機寬度（≤560px）與桌面版都檢查過
- [ ] 無中國用語混入
- [ ] 本檔已續寫本輪紀錄

## 6. 已知限制（誠實清單）

- 決賽斷網備援 `index_offline.html`（Chart.js 內嵌版）目前停在舊版設計；美編全部定案後由 Claude Code 重製一次。
- Artifact 私有預覽版因平台 CSP 會擋 Google Fonts／CDN，字體會退回系統字型——正式效果以 GitHub Pages 為準。
- W7 起資料由雲端管線自動產出（目前等 `ANTHROPIC_API_KEY` 設定後首跑）；美編不影響也不依賴此事。
- OG 分享圖（`og:image`）尚未存在——GPT 素材到位後由 Claude Code 加 meta 標籤。

---

## 7. 2026-08-07｜第 1 輪：版面／字體／間距／配色系統精修

- 人類需求：「版面／字體／間距／配色系統、專案脈絡交給你（Claude），剩下（圖像素材、大膽方向）給 GPT」
- 執行者：Claude Code（Fable 5）
- 修改前狀態：網站 v2（另一 Claude session 建置）；terracotta `#b8623a` 同時充當品牌色與「全球供應鏈」維度色（語意混用）；hero 700 字重 30px；無手機細節斷點。
- 修改檔案：`src/site_template.html`（同步 `cowork/scripts/site_template.html`）、重建 `docs/index.html`
- 實作內容：品牌色與資料色分離（accent 深化 `#a44a24`、c3 改琥珀 `#b07a28`）；全站中性色統一暖灰；語意色加深；CSS 變數與 Chart.js JS 端色票同步替換；hero 900 字重＋clamp；標題 18px；section 40px 節奏；卡片陰影；綠點呼吸動畫（reduced-motion 安全）；selection/hover 細節；新增 560px 斷點。
- 遇到的錯誤與原因：本機 file:// 預覽面板無法截圖（面板限制，非網站問題）；改以 localhost http.server 驗證。
- 修正方式：`python -m http.server` 本機驗證＋curl 確認 Pages 已上新色票。
- 驗證：重建後佔位符替換 OK、舊色票 0 殘留；手機寬度實測（hero／雙軸條／行動建議／事件卡正常）；桌面 1280 版型正常（雙圖並排、篩選圓鈕）；Pages 實機 HTTP 200 且含新色票。
- Git commit：`1ce4e19` style: 版面/字體/間距/配色系統精修（美編第一軌）
- Pages 線上確認：https://sakaban-code.github.io/SCAI-test/ 已為新版
- 未完成與後續工作：等 GPT 圖像素材（logo／OG 圖／選配底紋）→ Claude Code 嵌入＋og meta＋重製離線版。

---

## 8. 給 GPT 的本輪委託（2026-08-07 起）

交付三項（規格見下），**只交圖，不改任何程式碼或 HTML/CSS**：

1. **品牌標誌**：SCAI-Agent logo/mark。向量感、簡潔幾何，可用雙軸／象限／雷達抽象意象。正方形透明背景 PNG 512×512（或 SVG），深色底、淺色底各一版。
2. **OG 分享圖**：1200×630 PNG。含「SCAI-Agent」與副標「半導體前瞻戰略情報」，配色用 §4 系統（暖白底＋深陶土＋墨黑），留白充足，文字勿超過兩行。
3. **（選配）頁首裝飾底紋**：極淡抽象幾何（雙軸／等高線意象），透明 PNG，透明度低到不干擾文字。

風格硬規則：專業克制、不要吉祥物、不要卡通風、不含任何未公開數據。完成後把檔案交給人類轉交 Claude Code，或直接說明放置於 `docs/assets/` 的檔名，由 Claude Code 嵌入、重建、推送。若對版面有「大膽視覺方向」的提案，寫成文字／示意稿附在交付裡，由 Claude Code 評估落地（紅線 §3 之內都歡迎）。

---

## 2026-08-07｜第 2 輪：GPT 圖像素材交付

- 人類需求：先讀 §0「給接手 AI 的話」與 §3「紅線」，確認本案為 GitHub Pages 靜態站且 GPT 只交圖、不改程式碼；依 §4 設計系統與 §8 委託，產出 logo 深淺兩版、1200×630 OG 分享圖及選配頁首底紋，並將本輪製作紀錄與素材一併打包。
- 執行者：GPT（ChatGPT／OpenAI image generation）
- 修改前狀態：第 1 輪版面、字體、間距與配色系統已上線；尚無正式品牌標誌、`og:image` 分享圖與頁首裝飾底紋。
- 修改檔案：僅新增圖像素材 `scai-logo-light-bg.png`、`scai-logo-dark-bg.png`、`scai-og-1200x630.png`、`scai-header-pattern.png`，並在本協作主檔追加本節；**未修改任何 HTML、CSS、JavaScript、JSON、Python 管線或 `docs/index.html`**。
- 實作內容：
  1. **Logo 淺底版**：512×512 透明 PNG；以墨黑 `#211f1c` 為主、深陶土 `#a44a24` 為 accent，將雙軸交會、四象限與雷達訊號抽象為單一幾何符號。
  2. **Logo 深底版**：512×512 透明 PNG；維持相同幾何語言，主體改用暖白 `#faf9f7`，保留深陶土訊號弧，供深色背景使用。
  3. **OG 分享圖**：1200×630 PNG；暖白底、左側品牌符號、右側兩行文字「SCAI-Agent」與「半導體前瞻戰略情報」，使用墨黑與深陶土，未放入任何週報數值或未公開資料。
  4. **頁首底紋**：1600×480 透明 PNG；以極淡雙軸、雷達弧線與等高線構成，視覺重量置於右側，中央與左側保留文字安全區。
- 遇到的錯誤與原因：工具端無法直接開啟線上 GitHub Pages／GitHub repo（網址安全過濾或存取停用，非網站本身故障）；改以本主檔 §0、§3、§4、§8 的完整規格作為設計正本。原始透明素材先以單色鍵背景生成，需再執行去背與尺寸統一。
- 修正方式：以色鍵去背流程產生 alpha 通道；Logo 統一輸出為 512×512、OG 精準輸出為 1200×630、底紋裁切為 1600×480；再分別疊於暖白與墨黑背景進行目視 QA。
- 驗證：兩版 Logo 皆為透明 PNG（RGBA），四角透明且無明顯綠邊；OG 尺寸 1200×630、繁體中文副標正確且文字僅兩行；底紋為透明 PNG、在暖白背景上保持低對比；全套不含吉祥物、卡通元素、虛構數據、未公開數據或中國用語。
- Git commit：尚未執行；依分工，本輪只交圖檔與方向，不操作 repo。
- Pages 線上確認：尚未執行；待 Claude Code 嵌入素材、重建並推送後確認。
- 未完成與後續工作：由 Claude Code 將素材放入 `docs/assets/`，在 `src/site_template.html` 嵌入 Logo／底紋並新增 OG meta，執行 `build_site.py` 重建 `docs/index.html`，同步 cowork 模板、完成桌機與手機驗證、推送 GitHub Pages，最後重製 `index_offline.html` 並在本主檔續寫整合結果與 commit。

### 素材整合建議

- `scai-logo-light-bg.png`：暖白或卡片背景使用。
- `scai-logo-dark-bg.png`：墨黑或深色區塊使用。
- `scai-og-1200x630.png`：設定為公開網址的 `og:image`，並確認 Pages 可由絕對 URL 讀取。
- `scai-header-pattern.png`：建議置於頁首右側或外圍，以約 15–25% 視覺強度疊加；不可降低正文對比或遮住【推斷】等誠實標示。

---

## 2026-08-07｜第 3 輪：素材整合上線（Claude Code）

- 人類需求：「GPT 的」（附素材 zip）——依分工由 Claude Code 嵌入、重建、推送。
- 執行者：Claude Code（Fable 5）
- 修改前狀態：第 2 輪素材已交付但未入站；favicon 為內嵌 SVG「SC」、header 為文字方塊 logo、無 og:image。
- 修改檔案：`docs/assets/`（新增四張 PNG，檔名照 GPT 交付）、`src/site_template.html`（同步 `cowork/scripts/site_template.html`）、本主檔（接受 GPT 第 2 輪 append＋本節）、重建 `docs/index.html`。
- 實作內容：
  1. 素材驗收：兩版 logo 512×512 RGBA、OG 1200×630、底紋 1600×480 RGBA，規格與風格（無吉祥物、配色對齊 §4）全數合格；GPT 對主檔為純 append、未觸紅線。
  2. favicon／apple-touch-icon 改用 `assets/scai-logo-light-bg.png`（取代內嵌 SVG）。
  3. header 品牌區改為 `<img class="logo">`（34px，`object-fit:contain`）。
  4. og meta：`og:url`＋`og:image`（絕對網址）＋尺寸＋`twitter:card=summary_large_image`。
  5. 頁首底紋：`header::before` 右側疊加（`auto 230%` 裁切、`opacity:.55`、`pointer-events:none`），內容以 `header>*` 墊高層級；同步把 header 底色 rgba 校正為第 1 輪的 `#faf9f7` 基調。
- 遇到的錯誤與原因：本機預覽面板無法截圖（面板未顯示、非網站問題）。
- 修正方式：改以 DOM 實測驗證（JS 檢查素材載入與樣式生效）。
- 驗證：logo `naturalWidth=512` 載入成功；`header::before` 背景確認掛上底紋；`og:image` 絕對網址正確；Chart.js 三張 canvas、六週資料、0 個失敗區塊；`/*__DATA__*/` 已替換。
- Git commit：見本輪推送 commit（feat: 整合 GPT 圖像素材）。
- Pages 線上確認：推送後 curl 驗證 assets 與 og meta（見下輪或本輪補記）。
- 未完成與後續工作：`index_offline.html` 重製（待人類確認整體美編定案）；底紋強度如需增減（目前 .55 於近白圖上屬克制），一行 CSS 可調。

---

## 2026-08-08｜第 4 輪：內容與互動全面升級（S/A/B 十四項）

- 人類需求：「我覺得網站還能再更新，但不知道有哪些」→ Claude 提出三檔選單 →「全做」。
- 執行者：Claude Code（Fable 5）
- 修改前狀態：第 3 輪素材整合完成；站上尚無交叉驗證徽章、token 稽核、風險命中追蹤、累積敘事、導覽與備援機制。
- 修改檔案：`src/site_template.html`（同步 cowork 副本）、`src/pipeline.py`（週物件加 `tokenUsage`）、`docs/assets/chart.umd.min.js`（新增本地備援）、重建 `docs/index.html`。
- 實作內容（S＝評分項、A＝展演、B＝小而美）：
  - S1 雙模型交叉驗證徽章：hero 顯示「雙模型一致 ✓／✕｜信心 高/低」chip＋不一致警示條——**條件渲染，W7 資料到自動亮**；W1–W6 人工週不顯示。
  - S2 Token 稽核：pipeline 週物件新增 `tokenUsage`（byStep＋total）；稽核區渲染逐模型 in/out 表——W7 起自動帶，之前顯示說明文字。
  - S3 稽核連結：決策軌跡區底部新增「管線稽核」列（repo＋Actions 執行紀錄外連）。
  - S4 風險命中追蹤 UI：riskRadar 項目支援選填 `status`（hit已應驗/resolved已化解/watching追蹤中）與 `followUp`——**資料由 Cowork 週報判定時補，本輪僅 UI**。
  - A5 XY 軌跡逐週描繪動畫（per-point delay 160ms，`prefers-reduced-motion` 時停用）。
  - A6 KDF 橫條 ghost 刻度：灰短線標上週權重位置＋tooltip 顯示「上週→本週」。
  - A7 六週累積觀察卡：自動計算 W1→當週的雙軸位移、情境跨度、五維最大變動（純算術、無臆測文字）。
  - A8 30 秒導覽條：header 下三步引導（判定→軌跡→規畫），非 sticky。
  - A9 Chart.js 本地備援：CDN 失敗自動改載 `assets/chart.umd.min.js`（決賽斷網保險進正式站）。
  - B：複製本週連結按鈕（clipboard＋fallback prompt）、列印/存 PDF 按鈕（手機隱藏）、事件來源數統計、風險雷達空狀態誠實文案（LAYER 10 導入時點）、五維趨勢 tooltip 顯示該週情境名。
- 不採納（前輪已議定）：深色模式（Chart.js 色票需 JS 整套跟切、受眾場景價值低）、雷達圖（與五維趨勢線資訊重複）。
- 遇到的錯誤與原因：無重大錯誤；瀏覽器面板截圖仍受限，驗證改走 DOM 實測。
- 驗證：py_compile 通過；重建後 14 項功能標記到位（87KB）；本機實測——W1（空狀態文案 ✓、無累積卡 ✓、稽核區 W7 提示 ✓）、W6（三圖 0 失敗、累積卡文字「X 軸由 −0.35 移至 −0.45（碎裂加深 0.10）」正確、導覽條/複製鈕/來源統計/稽核連結 ✓）。
- Git commit：見本輪推送 commit（feat: 網站內容與互動升級）。
- Pages 線上確認：推送後背景驗證。
- 未完成與後續工作：riskRadar 之 status/followUp 資料待 Cowork 每週判定補入；`index_offline.html` 重製仍待美編定案。
