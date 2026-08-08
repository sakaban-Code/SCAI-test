# -*- coding: utf-8 -*-
"""週次曆法共用工具（fetch.py / pipeline.py / backfill.py 共用，無副作用）。

週次區間字串格式沿用 W1–W6 既有樣式：同年 `2026/07/14–07/20`、跨年 `2026/12/28–2027/01/03`。
分隔符為 EN DASH（U+2013）。
"""
import datetime


def wnum(w) -> int:
    """'W7' / 'w7' / 7 → 7"""
    return int(str(w).lstrip("Ww"))


def fmt_range(start: datetime.date, end: datetime.date) -> str:
    return (f"{start:%Y/%m/%d}–{end:%m/%d}" if start.year == end.year
            else f"{start:%Y/%m/%d}–{end:%Y/%m/%d}")


def parse_range_end(rng: str) -> datetime.date:
    """解析區間字串的迄日；容忍迄日省略年份、以及 – — - 三種分隔符。"""
    parts = rng.replace("—", "–").replace("-", "–").split("–")
    if len(parts) != 2:
        raise ValueError(f"無法解析區間字串：{rng!r}")
    start = datetime.datetime.strptime(parts[0].strip(), "%Y/%m/%d").date()
    tail = parts[1].strip()
    if tail.count("/") == 2:
        return datetime.datetime.strptime(tail, "%Y/%m/%d").date()
    m, d = (int(x) for x in tail.split("/"))
    year = start.year + 1 if m < start.month else start.year   # 迄日月份較小＝跨年
    return datetime.date(year, m, d)


def last_week_entry(weeks: list) -> dict | None:
    """取週次編號最大的一筆（weeks.json 未必依序）"""
    return max(weeks, key=lambda w: wnum(w.get("week"))) if weeks else None
