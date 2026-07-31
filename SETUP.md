# SCAI-Agent 雲端自動管線 — 部署步驟

## 架構一覽

```
GitHub Actions cron（每週一 08:00 台北時間，雲端自動觸發，不需開機）
  └─ fetch.py     Tavily + RSS 抓事件（純搜尋 API，不用模型 → 合規）
  └─ pipeline.py  Sonnet 擷取 → Opus 情境推理 → Gemini 交叉驗證
  │                一致 → 信心「高」；不一致 → 【建議查證】信心「低」
  └─ make_charts.py 四張圖表
  └─ git commit    JSON / 圖 / 週報 / 儀表板 全部留痕（Observability）
```

模型合規：Sonnet、Opus（Anthropic）＋ Gemini（Google），皆在競賽三大系列內。
Token 治理：每次執行產出 `weekly/W{n}/token_usage.json`，逐模型記錄 input/output
tokens，直接對應決賽「Token 使用量說明」20% 評分項。

## 一次性設定（約 20 分鐘）

1. **建 GitHub 倉庫**，把本資料夾內容推上去。建議先用 public repo
   （Actions 免費分鐘數無上限；private 每月 2,000 分鐘也綽綽有餘）。

2. **申請三把 API key**
   - Anthropic：console.anthropic.com → 用競賽補助購買 credits（留收據核銷）
   - Google Gemini：aistudio.google.com → API key（有免費額度）
   - Tavily：tavily.com（免費層每月 1,000 次搜尋，夠用）

3. **設定 Secrets**：GitHub repo → Settings → Secrets and variables → Actions
   新增 `ANTHROPIC_API_KEY`、`GEMINI_API_KEY`、`TAVILY_API_KEY`。

4. **儀表板與歷史資料已內建**：`dashboard/SCAI-Agent_週報儀表板.html` 與
   `data/weeks.json` 已回填 Cowork 人工判定之 W1–W6（含 decisionTrace；
   W3/W5/W6 另含 riskRadar／selfAudit），管線將自動從 **W7** 接續編號。
   定義正本＝`data/kdf_config.json`（憲法 v2.0／提案書 1–25 編號），
   欄位契約見 `data/week_schema.json`。W1–W6 無 `confidence`/`crossCheck`
   欄位（當時無雙模型交叉驗證），儀表板會顯示「Cowork 人工判定」；W7 起自動帶入。

5. **手動跑第一次**：repo → Actions → SCAI-Agent Weekly Pipeline →
   Run workflow。確認 commit 產出後，之後每週一自動執行。

6. **（選配）GitHub Pages**：Settings → Pages → 指到 `dashboard/`，
   取得公開網址，決賽簡報直接放連結。

## 決賽 Demo 建議

現場打開 Actions 頁按一次 Run workflow，3–5 分鐘後展示：
新 commit → 新週報 md → 儀表板新增一週資料點 → token_usage.json 明細。
這一套完整展示「任務完成＋治理留痕＋Token 可稽核」三個評分面向。

## 已知注意事項

- GitHub cron 不保證準點（可能延遲數分鐘～更久），簡報用語寫「每週自動觸發」。
- 排程 workflow 在 repo 60 天無活動後會被停用；每週有 commit 天然不會觸發，
  但競賽結束後若要續跑請留意。
- `pipeline.py` 的 `GEMINI` 模型常數請於開跑前確認 Google 當時最新可用版本。
- 週報正式 Word 版（docx）仍照憲法流程在 Cowork/Claude.ai 互動產出即可；
  雲端管線輸出 report.md 作為自動化交付與 git 留痕版本。
