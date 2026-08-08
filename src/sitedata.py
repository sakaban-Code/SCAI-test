# -*- coding: utf-8 -*-
"""網站 payload 組裝（build_site.py 與 build_offline.py 共用，無副作用）。

原本兩支建置腳本各自複製一份相同的 payload 程式碼，任一邊加欄位就會無聲分歧；
抽出於此後兩邊必然一致。

本模組**不讀寫 data/ 以外的東西、也不修改 weeks.json**：`days`／`start`／`end`
與 `coverage` 全部是由既有的 `range` 字串與 `gen` 欄位**推導**出來的顯示用衍生值。
"""
import copy, datetime, json, pathlib

import weekcal


def load(p):
    return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))


def build_coverage(weeks: list):
    """由各週 range／gen 推導期間涵蓋事實：重疊、缺口、非 7 天期別、產出落差。

    任何一筆解析失敗即回傳 None——模板據此整區不顯示，寧可不講也不講半真的。
    """
    items = []
    try:
        for w in weeks:
            start, end = weekcal.parse_range(w["range"])
            gen = datetime.date.fromisoformat(w["gen"]) if w.get("gen") else None
            items.append({
                "week": w["week"], "start": start, "end": end,
                "days": (end - start).days + 1,
                "lag": (gen - end).days if gen else None,
            })
    except Exception:
        return None
    if not items:
        return None

    items.sort(key=lambda x: x["start"])
    overlaps, gaps = [], []
    for a, b in zip(items, items[1:]):
        delta = (b["start"] - a["end"]).days
        if delta < 1:                      # 迄日 >= 次期起日 → 重疊
            overlaps.append({"a": a["week"], "b": b["week"], "days": 1 - delta,
                             "from": b["start"].strftime("%Y/%m/%d"),
                             "to": a["end"].strftime("%Y/%m/%d")})
        elif delta > 1:                    # 中間空了幾天
            gaps.append({"after": a["week"], "before": b["week"], "days": delta - 1,
                         "from": (a["end"] + datetime.timedelta(days=1)).strftime("%Y/%m/%d"),
                         "to": (b["start"] - datetime.timedelta(days=1)).strftime("%Y/%m/%d")})

    span = (items[-1]["end"] - items[0]["start"]).days + 1
    return {
        "spanFrom": items[0]["start"].strftime("%Y/%m/%d"),
        "spanTo": items[-1]["end"].strftime("%Y/%m/%d"),
        "spanDays": span,
        "coveredDays": span - sum(g["days"] for g in gaps),
        "doubleCounted": sum(o["days"] for o in overlaps),
        "overlaps": overlaps,
        "gaps": gaps,
        "irregular": [{"week": i["week"], "days": i["days"]} for i in items if i["days"] != 7],
        "maxLag": max((i["lag"] for i in items if i["lag"] is not None), default=None),
        "maxLagWeek": next((i["week"] for i in items
                            if i["lag"] is not None
                            and i["lag"] == max((j["lag"] for j in items
                                                 if j["lag"] is not None), default=None)), None),
    }


def build_payload(root: pathlib.Path) -> dict:
    weeks = copy.deepcopy(load(root / "data" / "weeks.json"))
    for w in weeks:
        w["week"] = int(str(w["week"]).lstrip("Ww"))
    weeks.sort(key=lambda w: w["week"])

    # 每週補上推導欄位；單筆解析失敗只略過該筆，不讓整站掛掉
    for w in weeks:
        try:
            start, end = weekcal.parse_range(w["range"])
        except Exception:
            continue
        w["days"] = (end - start).days + 1
        w["start"] = start.isoformat()
        w["end"] = end.isoformat()

    cfg = load(root / "data" / "kdf_config.json")
    prof = load(root / "data" / "company_profile.json")
    pb = load(root / "data" / "playbook.json")
    ex_path = root / "data" / "kdf_definitions.json"
    extras = load(ex_path) if ex_path.exists() else {"kdfDefs": {}, "scenarioMeta": []}

    return {
        "weeks": weeks,
        "kdf": cfg["kdf"],
        "dims": cfg["dimensions"],
        "horizons": pb["horizons"],
        "levers": {l["id"]: l for l in prof["decision_levers"]},
        "profile": prof,
        "kdfDefs": extras.get("kdfDefs", {}),
        "scenarioMeta": extras.get("scenarioMeta", []),
        "coverage": build_coverage(weeks),
    }


def payload_js(root: pathlib.Path) -> str:
    return json.dumps(build_payload(root), ensure_ascii=False, separators=(",", ":"))
