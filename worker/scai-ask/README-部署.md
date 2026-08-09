# SCAI 助理後端｜Cloudflare Worker 部署步驟

網站的 AI 問答後端。**免費方案即可**（Workers 每日 100,000 次請求；Workers AI 每日 10,000 Neurons 免費推論額度，00:00 UTC 重置）。模型鎖定 `@cf/openai/gpt-oss-20b`（OpenAI 系列開放權重模型，符合競賽三大系列限制）。

## A. 儀表板部署（建議，全程點選不需裝任何東西）

1. 進入 [dash.cloudflare.com](https://dash.cloudflare.com) → 左側 **Compute（Workers）** → **Create**。
2. 選 **Create Worker**（Hello World 範本即可）→ 名稱輸入 `scai-ask` → **Deploy**。
3. 部署完成後點 **Edit code** → 全選刪掉範本 → **貼上本資料夾 `worker.js` 的全部內容** → 右上 **Deploy**。
4. 回到該 Worker 的 **Settings → Bindings → Add binding** → 選 **Workers AI** → Variable name 填 `AI` → Save。
   ※ 沒有這步，呼叫會回 `ai unavailable`。
5. 複製 Worker 網址（形如 `https://scai-ask.<你的子網域>.workers.dev`），**把這串網址貼給 Claude Code**。
6. Claude Code 會把網址填進 `src/site_template.html` 的 `SCAI_AI_CONFIG.endpoint`、重建並推送——網站上的助理面板自動從「展示模式」轉「AI 連線」，並開始顯示逐次 token 用量。

驗證：面板送出一個問題，回覆下方應出現「模型：@cf/openai/gpt-oss-20b｜本次 in/out tokens」。

## B. CLI 部署（替代路徑，需 Node.js）

```bash
cd worker/scai-ask
npx wrangler login
npx wrangler deploy
```

`wrangler.toml` 已含 AI 綁定，不需再手動設定。

## 安全設計（已寫死在 worker.js，對應網站「治理」頁）

- 模型與 system prompt 固定於後端，前端不可指定。
- CORS 白名單：只允許 `https://sakaban-code.github.io` 與本機驗證用 `http://localhost:8765`。
- 問題 ≤300 字、輸出 ≤512 tokens、每 IP 每分鐘 8 次。
- **不記錄問答內容**（無任何儲存呼叫）；只回傳 token 用量數字。
- 免費額度用罄時回 503，網站前端**自動降級為展示模式**，不會空白。

## 費用

- Workers AI 免費額度內：**零成本**。gpt-oss-20b 計價 $0.20/$0.30 per M tokens（超額才計）。
- 免費方案額度用罄即停（回錯誤），**不會自動扣款**。

## 日後切換 Claude（經費核銷可動時）

兩條路，前端與本 Worker 介面都不用改：

1. **AI Gateway Unified Billing**（免自備 Anthropic key）：dash → AI → AI Gateway → 建立 gateway → 儲值 Cloudflare 額度（購買加收 5%，token 單價無加成）→ 把 `worker.js` 的 `env.AI.run(...)` 段落改為 `fetch` AI Gateway 的 Anthropic 相容端點（`claude-sonnet-5` 等）。
2. **自備 Anthropic key**（核銷收據較單純）：`wrangler secret put ANTHROPIC_API_KEY` 後在 worker 內直呼 Anthropic API。

同一個 Gateway 也可供**週報管線**使用（`pipeline.py` 的 SDK 指 base_url 過去），W9 起自動週報與網站問答共用同一池額度。
