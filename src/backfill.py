#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backfill.py — 回補缺漏週次

用途：API 中斷期間累積的缺口（例如 W7/W8/W9），一次補齊且**每週各自對應正確的
歷史區間與該區間的真實新聞**——而不是連跑三次得到三份掛著同一段日期的重複資料。

推算規則：從 data/weeks.json 最後一週的迄日往後接，每 7 天一週；只補**已完整結束**
的週次（迄日 > 今天者不補，資料不完整）。

用法：
    python src/backfill.py                 # 只列出計畫，不執行（預設）
    python src/backfill.py --execute       # 實際執行（會消耗 API token）
    python src/backfill.py --execute --max 2   # 最多補 2 週

執行內容：對每個缺漏週次依序跑
    python src/fetch.py    --week N --start S --end E
    python src/pipeline.py --week N
任一步失敗即中止，已完成的週次保留（append-only，不回滾）。
"""
import argparse, datetime, json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = sys.executable

from weekcal import wnum, parse_range_end, last_week_entry


def plan(max_weeks: int | None) -> list[tuple[int, datetime.date, datetime.date]]:
    weeks = json.loads((ROOT / "data" / "weeks.json").read_text(encoding="utf-8"))
    if not weeks:
        sys.exit("[錯誤] data/weeks.json 是空的，無法推算起點")
    last = last_week_entry(weeks)
    n, cursor = wnum(last["week"]), parse_range_end(last["range"])
    print(f"[基準] 最後一週 W{n}（{last['range']}），迄日 {cursor}")

    today, out = datetime.date.today(), []
    while True:
        n += 1
        s = cursor + datetime.timedelta(days=1)
        e = s + datetime.timedelta(days=6)
        if e > today:
            print(f"[停止] W{n}（{s}–{e}）尚未結束（今天 {today}），不回補未完成的週次")
            break
        out.append((n, s, e))
        cursor = e
        if max_weeks and len(out) >= max_weeks:
            print(f"[停止] 已達 --max {max_weeks}")
            break
    return out


def run(cmd: list[str]) -> None:
    print("  $ " + " ".join(cmd[1:]))
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        sys.exit(f"[中止] 指令失敗（exit {r.returncode}）：{' '.join(cmd[1:])}")


def main():
    ap = argparse.ArgumentParser(description="回補缺漏週次")
    ap.add_argument("--execute", action="store_true", help="實際執行（省略＝只列計畫）")
    ap.add_argument("--max", type=int, help="最多回補幾週")
    a = ap.parse_args()

    todo = plan(a.max)
    if not todo:
        print("[完成] 沒有可回補的完整週次")
        return

    print(f"\n計畫回補 {len(todo)} 週：")
    for n, s, e in todo:
        print(f"  W{n}  {s} – {e}")

    if not a.execute:
        print("\n（此為計畫預覽，未執行。確認無誤後加 --execute）")
        print("注意：回補會消耗 Anthropic／Tavily token，且 RSS 不納入（feed 無歷史）。")
        return

    for n, s, e in todo:
        print(f"\n── 回補 W{n}（{s} – {e}）──")
        run([PY, "src/fetch.py", "--week", str(n), "--start", s.isoformat(), "--end", e.isoformat()])
        run([PY, "src/pipeline.py", "--week", str(n)])
        print(f"[ok] W{n} 完成")

    print("\n[完成] 全部回補結束。請接著執行：")
    print("  python src/make_charts.py && python src/build_site.py && python src/build_offline.py --no-net")


if __name__ == "__main__":
    main()
