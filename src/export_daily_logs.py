#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_daily_logs.py — 把本機（cowork 側）每日監測日誌淨化成公開版（一次性遷移工具）

保留：date、checked、items 之 title/source/date/url/tier/ruleId/summary/alerted、
      redCount/yellowCount；alerts_log.csv 之 datetime/tier/ruleId/title/url/emailSent。
移除：自由格式 note 欄整欄（收件地址與郵件資訊都在裡面）。
寫檔前先以 daily_watch.scan_text 全文掃描：命中信箱／API key／家目錄路徑即中止，
一個位元組都不寫。

用法：python src/export_daily_logs.py --src <cowork 資料夾路徑>
（來源路徑一律由命令列給定，程式碼內不留本機路徑。）
"""
import argparse, csv, io, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from daily_watch import scan_text, CSV_COLS

KEEP_ITEM = ("title", "source", "date", "url", "tier", "ruleId", "summary", "alerted")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="cowork 資料夾路徑")
    a = ap.parse_args()
    src = pathlib.Path(a.src)
    out = []  # (目的路徑, 內容)——全部先組在記憶體，掃描通過才落地

    for f in sorted((src / "logs" / "daily_watch").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        items = [{k: it[k] for k in KEEP_ITEM if k in it} for it in d.get("items", [])]
        pub = {"date": d.get("date"), "checked": d.get("checked", []), "items": items,
               "redCount": sum(1 for i in items if i.get("tier") == "RED"),
               "yellowCount": sum(1 for i in items if i.get("tier") == "YELLOW"),
               "_sanitized": "公開淨化版：note 欄（含收件資訊）整欄移除；原始檔留在本機"}
        out.append((ROOT / "logs" / "daily_watch" / f.name,
                    json.dumps(pub, ensure_ascii=False, indent=2) + "\n"))

    srccsv = src / "logs" / "alerts_log.csv"
    if srccsv.exists():
        with srccsv.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=CSV_COLS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in CSV_COLS})  # note 欄整欄丟棄
        out.append((ROOT / "logs" / "alerts_log.csv", buf.getvalue()))

    hits = []
    for p, text in out:
        hits += scan_text(text, str(p.relative_to(ROOT)))
    if hits:
        print(f"[中止] 淨化後仍掃到 {len(hits)} 處疑似私人資訊，一個位元組都沒寫：")
        for h in hits:
            print("  " + h)
        sys.exit(1)

    for p, text in out:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    print(f"[完成] 淨化輸出 {len(out)} 檔 → logs/")


if __name__ == "__main__":
    main()
