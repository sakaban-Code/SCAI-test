# 每日監測日誌（公開淨化版）

「**有沒有執行**」與「**有沒有警報**」是兩件事，分兩套紀錄——否則「沒跑」和「全綠」在檔案系統上長得一模一樣。

| 檔案 | 何時寫 | 語意 |
|---|---|---|
| `receipts/YYYY-MM-DD.json` | 每次執行必寫（含失敗） | 有收據且 `red=0` ＝ 真的跑過且無警報；**沒有收據 ＝ 當天沒跑**；`status=failed` ＝ 跑了但失敗 |
| `daily_watch/YYYY-MM-DD.json` | 當日有 RED／YELLOW 才寫 | 分級結果與命中詞（GREEN 不落檔，避免噪音） |
| `alerts_log.csv` | 出現新 RED 時追加 | 72 小時去重依據；`emailSent=false` ＝ shadow 期（判了、沒寄） |

- 分級為純關鍵字規則（`data/alert_rules.json` 之 any／all／anyB），**不呼叫任何模型**——警報是確定性規則，可稽核、零 token。比對前先以 `src/plan_engine.py` 的 `strip_negated()` 剔除否定子句：「園區**無**停電通報」不會觸發 RT-04。
- 寄信閘門 `ALERT_MODE`（shadow → test → live，預設 shadow）與上線驗收六項見 `src/daily_watch.py` 檔頭；收件地址只存 GitHub Secret `ALERT_TO`，任何檔案不留真實信箱。
- **2026-08-21（含）以前**為本機人工巡邏之淨化匯出（`src/export_daily_logs.py`）：note 欄整欄移除、收件資訊不進公開 repo，原始檔留在本機。該時期無收據，以日誌檔本身為執行證據（含 0 則之日）；未執行之日（8/2–8/3、8/5、8/10、8/13、8/15–8/17、8/19）依 P1 誠信原則不補填。
- **2026-08-22 起**由 `.github/workflows/daily.yml` 每日台北 21:00 自動執行，收據制同時啟用。
