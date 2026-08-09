# 開發階段 Token 統計 — 資料來源、陷阱與應用化規格

競賽評分第 3 項（20%）要求說明「**開發 AI 員工／以及 AI 員工運作時**的 Token 消耗，
花在哪裡、如何優化」。開發階段那一半由 `src/token_stats.py` 產出；運作階段那一半
要等雲端管線首跑後的 `weekly/W{n}/token_usage.json`。

本文件同時是**把它做成本機應用程式的規格書**——所有踩過的坑都寫在這，
不必再踩一次。

---

## 1. 資料來源（皆為本機原始紀錄，非估算）

| 工具 | 路徑 | 實測量 |
|---|---|---|
| Claude Code | `~/.claude/projects/**/*.jsonl` | 79.4 MB |
| Cowork | `%APPDATA%\Claude\local-agent-mode-sessions\**\audit.jsonl`<br>（macOS：`~/Library/Application Support/Claude/…`） | 24 MB（該目錄總計 52.2 MB） |
| Codex | `~/.codex/sessions/**/*.jsonl` | 16.8 MB |

Cowork 的 `audit.jsonl` **每行帶 `_audit_hmac` 簽章**（同層另有 `.audit-key`），
是設計成防竄改的稽核鏈，不是應用程式隨手寫的 log。本腳本**只讀取不驗簽**。
拿去佐證「token 數字可稽核」時可以提這件事，但不要宣稱我們驗過簽。

另有 `%APPDATA%\Claude\plan-usage-history.json`（470 筆 `{t, org, u:{fh, sd}}`）。
`fh`／`sd` 值域 0–40，**研判是額度百分比而非 token 數**，且混入整個帳號的活動。
可作時間軸交叉驗證，**不可當數字來源**。（此為研判，非查證。）

---

## 2. 五個坑

三個是重複計算，兩個是資料品質。**任何重寫版本都必須處理這五個，否則數字是錯的。**

### 坑 1｜Claude Code：一次回應寫成多行，每行都帶完整 usage

同一次 API 回應會依內容型別拆行寫入（`thinking` 一行、`text` 一行），
**兩行的 `message.id`、`requestId` 與整包 `usage` 完全相同**。

> 實測本專案逐字稿：3241 行 → 1621 則，**正好 2 倍**。

→ 依 `message.id` 去重。Cowork 同格式、同坑。

### 坑 2｜Codex：`total_token_usage` 是累計值不是增量

整份加總會得到天文數字。

> 實測 99 個 session、973 個 `token_count` 事件，累計值**全程單調遞增、0 次重置**
> → 取每檔**末筆**即為該 session 真實總量。

`last_token_usage` 的總和會比末筆高約一成（同一回合內多次呼叫重複計入），
**只作交叉檢查，不採用**。

### 坑 3｜Codex 的 `cached_input_tokens` 是 `input_tokens` 的子集

```
33134 (input) + 204 (output) = 33338 (total)   ← cached 7552 已含在 input 內
```

Anthropic 的 `input` / `cache_creation` / `cache_read` 則是**互斥三份**。
兩家結構不同，**不可用同一段程式相加**。腳本的做法是把 Codex 拆成互斥兩份
（`input − cached` 與 `cached`），之後彙總才能一視同仁。

### 坑 4｜Cowork 的 `output_tokens` 不可用

> 實測單一 session 去重後 339 則，output **最大值僅 73、平均 23**；
> 且同一 `message.id` 的重複紀錄其 output 首末**完全相同**
> —— 不是串流中途快照取錯，是稽核紀錄在回應產出前就寫入了。

輸入側（`input` / `cache_creation` / `cache_read`）數值完整且合理，可用。

→ 計為 `outputUnknown` 而非 `0`。**`0` 會被讀成「真的沒產出」，那是假數字。**

### 坑 5｜四項直接相加會被 `cache_read` 主導

長對話每次呼叫都重讀整段快取前綴，`cache_read` 累積後占處理總量 **96%**。
把四項相加叫「總 token 用量」——技術上為真，**實務上誤導一個數量級**。

> 實測 core 口徑：處理總量 **9.8 億** vs 輸入計價當量 **1.71 億**

→ 並列三個各有明確意義的量，**不提供單一「總 token」**：

| 欄位 | 意義 |
|---|---|
| `processed` | 實際處理量（含重讀快取），衡量工作規模 |
| `billableInput` | 依快取倍率折算的**輸入計價當量**，反映成本結構 ← **報告請引用這個** |
| `output` | 產出量，另計 |

快取倍率定義在 `src/token_stats.py` 的 `RATE`（1.25× 寫入5m／2× 寫入1h／
0.1× 讀取／0.25× OpenAI 快取）。**這是倍率不是金額**，正式報告前請對照
當時的官方定價頁覆核 —— OpenAI 側的快取折扣改過。

---

## 3. 歸屬口徑：腳本只算，不替人決定

逐字稿有純有混。腳本掃出每檔的 SCAI 提及數與密度後，由人在
`data/token_scope.json` 逐檔標記，**該檔進版控 → 歸屬決定本身可被稽核**。

| 口徑 | 定義 |
|---|---|
| `core` | 純 SCAI 工作階段 —— **確定下界** |
| `core + related` | 再加上混合階段中判定與 SCAI 相關者 |
| `all` | 全部掃到的紀錄 —— **確定上界** |

密度門檻（`DENSITY_CORE=20/MB`、`DENSITY_RELATED=1/MB`）只用來產**建議草稿**，
草稿一律帶 `"confirmed": false`。**真正的歸屬以人工覆核後的檔案為準。**

---

## 4. 輸出 schema：`data/token_usage_dev.json`

```jsonc
{
  "generated": "",              // 刻意留空由呼叫端填——腳本不取系統時間以維持可重現
  "generator": "src/token_stats.py",
  "stage": "development",
  "sources":       { "claude-code": "…", "cowork": "…", "codex": "…" },
  "countingRules": [ /* 上述五個坑的處置，逐條寫入產物本身 */ ],
  "rates":         { "input":1.0, "cacheWrite5m":1.25, "cacheWrite1h":2.0,
                     "cacheRead":0.1, "codexCacheRead":0.25 },
  "scopeFile": "data/token_scope.json",

  "totals":  { "core": <M>, "core+related": <M>, "all": <M> },
  "byTool":  { "claude-code": <M>, "cowork": <M>, "codex": <M> },
  "byModel": { "claude-opus-5": <M>, … },
  "byDay":   [ { "date": "2026-08-09", …<M> } ],
  "sessions":[ { "tool", "session", "scope", "mentions", "from", "to", …<M> } ]
}

// <M> = { msgs, input, cacheCreate, cw5m, cw1h, cacheRead, codexCacheRead,
//         output, outputUnknown, processed, billableInput, cacheHitRate }
```

**產物不含檔案路徑、不含對話內容。** 腳本結尾有硬性把關：輸出字串若含
使用者家目錄或帳號名即中止不寫出（`data/` 會進 public repo）。
首則訊息預覽只出現在本機主控台，供人工標 scope 用。

---

## 5. 本機應用 — **已建置（2026-08-10）**

```bash
python src/build_token_app.py            # 讀現成 JSON 建置
python src/build_token_app.py --rescan   # 先重掃三個來源（約 2 秒）再建置
python src/build_token_app.py --open     # 建置後開啟
```

產物 `dashboard/token-usage.html`（約 293 KB）：資料與 Chart.js 全部內嵌，**雙擊即開、
零外部請求**、零相依（僅標準庫）。模板在 `src/token_app_template.html`。

跳脫走 `sitedata.js_safe_json()`——建置當初把 `payload_js()` 內的那段抽了出來，
`build_site` / `build_offline` / `build_token_app` 共用同一個咽喉點。**不要在別處再寫一份。**

建置器出檔前有四道硬性斷言，任一不過就中止而非產出一份看起來合理的錯數字：

| 斷言 | 防的是 |
|---|---|
| `cw5m + cw1h == cacheCreate`（逐口徑） | 快取寫入拆分沒加回總數（見下方 ①） |
| `billableInput` == 各成分乘倍率之和 | `rates` 與數字不同源，頁面自算出另一個值 |
| 由 sessions 推導的 `byTool` == 原始 `byTool` | 明細與彙總分歧；頁面的分工具圖靠這個推導才能切口徑 |
| 跳脫後 `json.loads` 等價、產物不含家目錄／帳號名 | 注入與隱私 |

### 建置過程抓到的兩個既有缺陷（皆已修）

**① `cw5m + cw1h` 會大於 `cacheCreate`。** 實測有 3 筆原始紀錄（去重後 1 筆）
回報 `cache_creation_input_tokens=0` 卻同時給 `ephemeral_1h=1542`。原本的補差邏輯
`cw5m = max(cw_total - cw1h, 0)` 只夾 5m、留著 1h，於是成分和多出 1,542，而且那截
**是按最貴的 2× 計價**（+3,084 當量），與程式自己註解寫的「寧可低估不可高估」相反。
→ 改成 `cw1h = min(cw1h, cw_total); cw5m = cw_total - cw1h`，不變式恆成立。

**② 新出現的 session 會靜默變成 `excluded`。** `load_scope()` 對歸屬檔裡沒有的
session 取預設值 `excluded`，畫面上和「人工判定與本專案無關」**完全一樣**，於是新工作
被無聲排除在 core 之外，還沒有任何跡象提醒該去覆核。
→ 每筆 session 加上 `reviewed` 欄位，主控台印出待覆核筆數，頁面上獨立標示並揭露
其計價當量。**覆核前 core 是低估，這件事現在會自己講出來。**

兩者都屬同一類：**數字看起來合理，所以沒人會去對。** 見金庫 [[看起來合理的數字最難察覺]]。

### 先講最重要的一件事：**不要建資料庫**

> 實測全掃 148 MB **只要 2.1 秒**。

因為做了兩件事：讀檔逐行、`json.loads` 前先用 `'"usage"' not in line` 這種
字串測試擋掉九成九的行（真正解析的只有約 5000 行）。

所以 ingest → SQLite → 增量 offset 那套架構（`tokentongji` 走的路）在這個
資料量下**是純粹的複雜度**，還會引入「快取與真實檔案不同步」的一整類 bug。
**每次重掃就好。**

### 架構（實作）

```
src/token_stats.py  --json   →   data/token_usage_dev.json
                                          ↓  src/build_token_app.py
                              dashboard/token-usage.html（資料已內嵌）
```

- **後端**：沒有。資料直接內嵌進 HTML，連 `file://` 的 CORS 問題都不會遇到，
  也不必為了看報表在本機開一個網路服務。要重掃就重跑建置器（含重掃約 2 秒）。
- **前端**：單檔 HTML + Chart.js（`docs/assets/chart.umd.min.js` 的本機副本內嵌，不外連）。
- **樣式**：沿用 `src/site_template.html` 的 CSS 變數，跟 SCAI 網站同一套視覺；
  另加 `prefers-color-scheme` 深色。**兩色系皆 1667 節點 0 項未達 AA**
  （淺色最低 4.54、深色最低 4.94；alpha 逐層合成後量測）。
- **注入**：字串一律 `textContent`，全檔 **0 處** `.innerHTML =`——模型名稱等字串來自
  三個工具的紀錄檔，不完全可控。`countingRules`／`caveats` 的 `**…**` 重點標記
  由 `emph()` 拆成文字節點與 `<b>` 插入，**不走 innerHTML**；且只施用於這兩個陣列
  ——`DATA.sources` 裡 `~/.claude/projects/**/*.jsonl` 的 `**` 是萬用字元不是強調。

### 畫面（依「花在哪裡、如何優化」反推，不是憑喜好）

| 區塊 | 對應評審會問的問題 |
|---|---|
| 三種口徑並列（下界／中／上界） | 「這數字怎麼來的？可信嗎？」 |
| 依工具、依模型的堆疊長條 | 「花在哪裡？」 |
| 每日趨勢（`byDay`） | 「開發節奏如何？」 |
| **快取命中率 96%** 大字 | 「**如何優化？**」← 最強的一張牌 |
| `countingRules` 直接顯示在頁面上 | 「你怎麼確定沒重複計算？」 |
| `outputUnknown` 缺漏揭露 | 誠實標準與 SCAI 網站 §09 一致 |

最後兩項不要省。**把計數規則和已知缺漏印在報表上，比數字漂亮更有說服力**
—— 這正是 SCAI 網站在期間涵蓋那一段做的事。

### 若要擴充到其他工具

`.gemini`、`.cursor`、`.openclaw` 本機都有目錄。加新來源時，
**先驗證三件事再寫彙總**：

1. 一次回應是否寫成多行？（→ 去重鍵是什麼）
2. 數值是累計還是增量？
3. 各欄位互斥還是包含？

坑 1–3 就是這三題在三個工具上的不同答案。**沒有一個工具的答案是一樣的。**

---

## 6. 隱私紅線

這些逐字稿含**你在這些工具裡做過的所有事**——不只 SCAI。

- ❌ 不要為了「更直觀」而把逐字稿內容送到任何外部服務
- ❌ 不要把含路徑／帳號名的產物提交進 public repo（腳本已硬性把關）
- ⚠️ 不要執行來路不明、會讀取這些目錄的第三方程式

這也是本專案沒有直接採用現成工具的原因：省下的那一百行，
換來的是一支能讀取全部 AI 對話紀錄並開啟網路服務的陌生程式。

---

## 附：用法

```bash
python src/token_stats.py                # 主控台報表
python src/token_stats.py --init-scope   # 產生歸屬草稿（待人工覆核）
python src/token_stats.py --json         # 寫出 data/token_usage_dev.json
```
