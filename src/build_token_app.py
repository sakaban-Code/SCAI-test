#!/usr/bin/env python3
"""開發階段 Token 用量——本機單檔應用建置器。

    src/token_stats.py --json  →  data/token_usage_dev.json
                                          ↓  （本腳本）
                              dashboard/token-usage.html（自帶資料，雙擊即開）

規格見 TOKEN-STATS.md §5。三個設計決定，都是有理由的：

**不建資料庫。** 全掃 148 MB 只要 2.1 秒（逐行讀 ＋ `'"usage"' not in line` 先擋掉
九成九的行）。ingest → SQLite → 增量 offset 在這個資料量下是純粹的複雜度，還會引入
「快取與真實檔案不同步」的一整類 bug。每次重掃就好。

**不起 server。** 資料與 Chart.js 全部內嵌成一份 HTML：雙擊就開，沒有 `file://` 的
CORS 問題，也不必為了看報表在本機開一個網路服務。讀的是全機 AI 逐字稿的彙總，
能離線就離線（TOKEN-STATS.md §6）。

**不重算數字。** 唯一的數字來源是 `token_stats.py`。本腳本只做呈現層的組裝與跳脫；
頁面上唯一的推導是「由 session 明細彙總出分工具數字」，而那件事出檔前會與原始
`byTool` 做逐欄等值斷言，不等值即中止。

零相依（僅標準庫），與 build_offline.py 同精神。

用法：
    python src/build_token_app.py                 # 讀現成 JSON 建置
    python src/build_token_app.py --rescan        # 先重掃三個來源再建置
    python src/build_token_app.py --open          # 建置後開啟
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import subprocess
import sys
import webbrowser

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from sitedata import js_safe_json          # noqa: E402  全站唯一的注入咽喉點

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOME = pathlib.Path.home()

TEMPLATE = ROOT / "src" / "token_app_template.html"
STATS = ROOT / "src" / "token_stats.py"
DATA_JSON = ROOT / "data" / "token_usage_dev.json"
CHART_JS = ROOT / "docs" / "assets" / "chart.umd.min.js"
OUT = ROOT / "dashboard" / "token-usage.html"

M_DATA = "/*__DATA__*/null"
M_CHART = "/*__CHARTJS__*/"

# 頁面在瀏覽器端由 sessions 推導分工具彙總時相加的欄位，與 token_stats.py 的 _FIELDS 同組。
FIELDS = ("msgs", "input", "cacheCreate", "cw5m", "cw1h", "cacheRead",
          "codexCacheRead", "output", "outputUnknown")


def die(msg: str):
    sys.exit(f"[錯誤] {msg}")


def enrich(a: dict, rates: dict) -> dict:
    """與 token_stats.py 的 enrich() 同一套算式（頁面 JS 亦同）。

    三處實作必須一致，故下方 verify_derivation() 拿它去對原始 byTool——
    對得上，才證明這裡與腳本沒有分歧，頁面上那份 JS 也才可信。
    """
    read_in = a["input"] + a["cacheCreate"] + a["cacheRead"] + a["codexCacheRead"]
    cached = a["cacheRead"] + a["codexCacheRead"]
    out = dict(a)
    out["processed"] = read_in + a["output"]
    out["billableInput"] = round(
        a["input"] * rates["input"]
        + a["cw5m"] * rates["cacheWrite5m"]
        + a["cw1h"] * rates["cacheWrite1h"]
        + a["cacheRead"] * rates["cacheRead"]
        + a["codexCacheRead"] * rates["codexCacheRead"]
    )
    out["cacheHitRate"] = round(cached / read_in, 4) if read_in else None
    return out


def by_tool_from_sessions(d: dict, scope: str) -> dict:
    keep = {"core": {"core"}, "core+related": {"core", "related"}}.get(scope)
    agg: dict[str, dict] = {}
    for s in d["sessions"]:
        if keep is not None and s["scope"] not in keep:
            continue
        a = agg.setdefault(s["tool"], {f: 0 for f in FIELDS})
        for f in FIELDS:
            a[f] += s.get(f) or 0
    return {k: enrich(v, d["rates"]) for k, v in agg.items()}


def verify_derivation(d: dict):
    """頁面的分工具圖表可切口徑，靠的是由 session 明細重新彙總。

    原始 JSON 的 byTool 只在 core+related 口徑下彙總，所以能對照的也只有那一個口徑。
    對得上，就證明推導方式正確，其餘口徑用同一段程式才站得住腳；對不上就代表
    session 明細與彙總已經分歧，此時出檔只會產生一份看起來合理的錯數字。
    """
    ref = d.get("byTool") or {}
    got = by_tool_from_sessions(d, "core+related")
    if set(ref) != set(got):
        die(f"分工具推導的工具集合與原始 byTool 不符：{sorted(got)} vs {sorted(ref)}")
    for tool, r in ref.items():
        for f in list(FIELDS) + ["processed", "billableInput", "cacheHitRate"]:
            if r.get(f) != got[tool].get(f):
                die(f"分工具推導不等值：{tool}.{f} 推導 {got[tool].get(f)} ≠ 原始 {r.get(f)}")
    return len(ref)


def sanity(d: dict):
    for key in ("totals", "byTool", "byModel", "byDay", "sessions", "rates", "countingRules"):
        if key not in d:
            die(f"{DATA_JSON.name} 缺少 {key} 欄位——請重跑 token_stats.py --json")
    for sc in ("core", "core+related", "all"):
        if sc not in d["totals"]:
            die(f"totals 缺少口徑 {sc}")
    # 快取寫入的 5m/1h 拆分必須加回總數。曾有原始紀錄回報 total=0 卻同時給 1h=1542，
    # 而當時的補差邏輯只夾 5m，於是成分和大於總量、多出來那截還按最貴的 2× 計價。
    # 頁面的成分拆解正是把這五項相加，對不上就會端出兩個互相矛盾的合計。
    for sc, t in d["totals"].items():
        if t["cw5m"] + t["cw1h"] != t["cacheCreate"]:
            die(f"totals[{sc}]：cw5m+cw1h={t['cw5m'] + t['cw1h']} "
                f"≠ cacheCreate={t['cacheCreate']}——快取寫入拆分未加回總數")

    # 計價當量必須等於各成分乘倍率之和；不等即代表 rates 與數字不同源，頁面會自算出另一個值
    R = d["rates"]
    for sc, t in d["totals"].items():
        want = round(t["input"] * R["input"] + t["cw5m"] * R["cacheWrite5m"]
                     + t["cw1h"] * R["cacheWrite1h"] + t["cacheRead"] * R["cacheRead"]
                     + t["codexCacheRead"] * R["codexCacheRead"])
        if abs(want - t["billableInput"]) > 1:
            die(f"totals[{sc}].billableInput={t['billableInput']} 與倍率重算值 {want} 不符")
    if not d.get("generated"):
        print("[提醒] JSON 的 generated 為空——頁面會顯示「未標示」。加 --rescan 可補上。")


def rescan(date: str):
    print(f"[重掃] python {STATS.relative_to(ROOT)} --json --date {date}")
    # token_stats.py 刻意不取系統時間（同輸入必得同輸出）；日期由呼叫端給，本腳本就是呼叫端。
    r = subprocess.run([sys.executable, str(STATS), "--json", "--date", date],
                       cwd=str(ROOT))
    if r.returncode != 0:
        die(f"token_stats.py 失敗（exit {r.returncode}）")


def main():
    ap = argparse.ArgumentParser(description="開發階段 Token 用量單檔應用建置器")
    ap.add_argument("--rescan", action="store_true",
                    help="先重跑 token_stats.py 重掃三個來源（約 2 秒）再建置")
    ap.add_argument("--date", default="",
                    help="重掃時寫入 generated 的日期 YYYY-MM-DD（預設為今天）")
    ap.add_argument("--open", action="store_true", dest="open_", help="建置後以預設瀏覽器開啟")
    ap.add_argument("-o", "--out", default=str(OUT), help=f"輸出路徑（預設 {OUT.relative_to(ROOT)}）")
    a = ap.parse_args()

    if a.rescan:
        rescan(a.date or datetime.date.today().isoformat())
    elif a.date:
        die("--date 只在 --rescan 時有意義（不重掃就不會重寫 generated）")

    for p in (TEMPLATE, DATA_JSON, CHART_JS):
        if not p.exists():
            die(f"缺少 {p}")

    d = json.loads(DATA_JSON.read_text(encoding="utf-8"))
    sanity(d)
    n_tools = verify_derivation(d)
    print(f"[斷言] 分工具推導 vs 原始 byTool：{n_tools} 個工具逐欄相等 ✓")

    html = TEMPLATE.read_text(encoding="utf-8")
    chart_js = CHART_JS.read_text(encoding="utf-8")
    payload = js_safe_json(d)              # <>& 與 U+2028/9 跳脫＋等價性斷言

    for name, marker in (("DATA", M_DATA), ("CHARTJS", M_CHART)):
        if html.count(marker) != 1:
            die(f"模板的 {name} 佔位符出現 {html.count(marker)} 次，應為 1 次")
    # 插入內容若含另一個佔位符，替換順序就會影響結果——先確認不會，才不必煩惱順序
    for name, content in (("DATA", payload), ("CHARTJS", chart_js)):
        for m in (M_DATA, M_CHART):
            if m in content:
                die(f"{name} 內容含佔位符 {m}，拒絕建置")
    if "</script" in payload.lower():
        die("跳脫後的 payload 仍含 </script——跳脫失效")

    html = html.replace(M_DATA, payload).replace(M_CHART, chart_js)

    # 隱私硬性把關：與 token_stats.py 同一道。產物是要拿給人看的，不得含本機路徑／帳號名。
    for leak in (str(HOME), HOME.name, os.environ.get("USERNAME") or "\0"):
        if leak and leak in html:
            die(f"產物含本機路徑或使用者名稱（{leak}）——拒絕寫出")

    out = pathlib.Path(a.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    core = d["totals"]["core"]
    kb = out.stat().st_size // 1024
    print(f"[完成] {out}（{kb} KB，資料與 Chart.js 皆已內嵌，無外部請求）")
    print(f"[內容] {len(d['sessions'])} 個 session、{len(d['byDay'])} 個日期、"
          f"{len(d['byModel'])} 個模型；core 計價當量 {core['billableInput']:,}、"
          f"快取命中率 {core['cacheHitRate'] * 100:.1f}%")
    print(f"[驗收] 已確認產物不含使用者路徑／名稱")

    if a.open_:
        webbrowser.open(out.as_uri())


if __name__ == "__main__":
    main()
