# -*- coding: utf-8 -*-
"""網站 payload 組裝（build_site.py 與 build_offline.py 共用，無副作用）。

原本兩支建置腳本各自複製一份相同的 payload 程式碼，任一邊加欄位就會無聲分歧；
抽出於此後兩邊必然一致。

本模組**不讀寫 data/ 以外的東西、也不修改 weeks.json**：`days`／`start`／`end`
與 `coverage` 全部是由既有的 `range` 字串與 `gen` 欄位**推導**出來的顯示用衍生值。
"""
import copy, datetime, json, pathlib, sys

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


_HTML_MAP = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}


def escape_html_deep(obj):
    """遞迴 HTML 跳脫所有字串葉節點（`&` 必須先換，否則會二次跳脫）。

    只施用於 `weeks`——該子樹由 Tavily 檢索結果與模型輸出寫入，不完全可控，
    而模板以樣板字面值組出 HTML 後經 innerHTML 寫入，未跳脫的 `<img onerror=…>`
    會在該週渲染時執行。`kdf_config`／`company_profile`／`playbook` 是版本控管
    下的自家設定檔，能改動它們的人同樣能改模板本身，故不在此防線範圍。

    現有資料中的 `<` `>` 皆為正當內容（`KDF#4=66 >= 70`、`R&D`、`>40%`），
    跳脫後瀏覽器渲染結果與跳脫前完全相同。
    """
    if isinstance(obj, str):
        for ch, rep in _HTML_MAP.items():
            obj = obj.replace(ch, rep)
        return obj
    if isinstance(obj, list):
        return [escape_html_deep(v) for v in obj]
    if isinstance(obj, dict):
        # 鍵也要跳脫：tokenUsage.byStep 這類「鍵名本身會被顯示」的結構，
        # 惡意鍵一樣能進 innerHTML。既有 schema 鍵名皆為英數，跳脫後不變。
        return {(escape_html_deep(k) if isinstance(k, str) else k): escape_html_deep(v)
                for k, v in obj.items()}
    return obj


def build_companies(root: pathlib.Path, weeks: list, prof: dict, pb: dict):
    """企業畫像可切換：欣銓＋兩家虛構示範企業。

    - 欣銓（real=True）：§02 規畫仍取 weeks.json 的 companyPlan（append-only 官方紀錄，
      不重算）；此處只帶 §08 畫像顯示資料。
    - 示範企業（real=False）：於建置時以 plan_engine 對**真實週次資料**逐週重算——
      觸發依據引用的座標／KDF／關鍵字都是真實的，虛構的只有企業本身。
      展示「同一套情境判定 × 不同企業畫像 → 不同觸發結果」的引擎可移植性。
    demo_profiles.json 不存在時只回傳欣銓一筆，網站自動退回單一企業模式（不顯示切換器）。
    """
    # 欣銓的畫像資料（§08 四張統計卡）改由此供給，故 demo_profiles.json 不存在時
    # 不能整個回 None——那會讓 §08 拿到空的 stats 陣列而少掉四張卡。
    # 改為仍回傳只含欣銓的單筆清單，模板照樣以 CO[0] 渲染、只是不出現切換器。
    demo_path = root / "data" / "demo_profiles.json"
    import sys as _sys
    _here = str(pathlib.Path(__file__).resolve().parent)
    if _here not in _sys.path:
        _sys.path.insert(0, _here)
    import plan_engine

    companies = [{
        "id": "anst", "real": True,
        "short": "欣銓科技", "name": "欣銓科技",
        "tickerLabel": "3264.TWO｜公開資料",
        "industry": prof["company"]["industry"],
        "stats": [
            {"k": "2026Q2 營收", "v": "45.3 億", "n": "季增 13.8%／年增 32.4%　法說會"},
            {"k": "毛利率", "v": "40.2%", "n": "季增 1.8pp／年增 3.9pp"},
            {"k": "上半年 capex", "v": "約 70 億", "n": "主投龍潭廠高階測試設備", "tbc": True},
            {"k": "稼動率", "v": ">70%", "n": "龍潭廠 2026/07 量產", "tbc": True},
        ],
        "profileNote": "營收組合占比、客戶集中度、耗材庫存月數等未公開項目均標示【待確認】，本系統不以估計值冒充內部數據。",
        "decision_levers": prof["decision_levers"],
    }]

    if not demo_path.exists():
        return companies          # 只有欣銓：§08 照常渲染，模板不顯示切換器

    demo = load(demo_path)
    for c in demo["companies"]:
        pbwrap = {"playbooks": c["playbooks"]}
        profwrap = {"scenario_stance": c["scenario_stance"]}
        plans = {}
        for w in weeks:                      # weeks＝正規化後、跳脫前的原值
            p = plan_engine.build_plan(w, profwrap, pbwrap)
            p["note"] = "示範資料：虛構企業，用於展示引擎可移植性；觸發依據引用的週次資料為真實紀錄。"
            plans[str(w["week"])] = p
        entry = {k: v for k, v in c.items() if k not in ("playbooks", "scenario_stance")}
        entry["real"] = False
        entry["plans"] = plans
        companies.append(entry)
    return companies


def build_token_dev(root: pathlib.Path):
    """開發階段 token 用量（由 src/token_stats.py 產出，見 TOKEN-STATS.md）。

    只取網站要顯示的欄位——原檔含 145 筆 session 明細共 88KB，全塞進頁面沒有意義。
    檔案不存在時回傳 None，模板據此退回「尚未統計」的說明，不顯示半套數字。

    刻意**不**在此重算或補值：數字的唯一來源是那支腳本，網站只負責呈現。
    """
    p = root / "data" / "token_usage_dev.json"
    if not p.exists():
        return None
    try:
        d = load(p)
        core = d["totals"]["core"]
    except Exception:
        return None          # 格式不符即整區不顯示，寧可不講也不講半真的

    def slim(m):
        return {k: m.get(k) for k in
                ("msgs", "billableInput", "output", "outputUnknown",
                 "processed", "cacheHitRate")}

    return {
        "generated": d.get("generated") or "",
        "core": slim(core),
        "all": slim(d["totals"].get("all") or core),
        "byTool": {k: slim(v) for k, v in (d.get("byTool") or {}).items()},
        "byModel": {k: slim(v) for k, v in (d.get("byModel") or {}).items()
                    if (v or {}).get("billableInput")},   # 濾掉 <synthetic> 等 0 用量項
        "rules": d.get("countingRules") or [],
        "caveats": d.get("caveats") or [],
        "days": len(d.get("byDay") or []),
        "sessions": len(d.get("sessions") or []),
    }


def build_alerts(root: pathlib.Path, weeks: list):
    """即時警報紅條資料：每日監測的 RED，「出現～被週報涵蓋」為止。

    - 只帶 emailSent=true——紅條與警報信同一道門檻（使用者 2026-08-22 裁定），
      shadow 期的純關鍵字誤判不上公開首頁。
    - 建置端條件①：警報日期尚未被任何已發佈週次的窗口涵蓋（W11 一匯入即熄）。
    - 瀏覽器端條件②：現在 < 警報時間＋7 天（exp，毫秒）——就算沒人重建，8/28 也自動熄。
    - 衍生顯示值，不寫回任何正本（與 coverage／risk_outcomes 同模式）。
    """
    import csv as _csv
    p = root / "logs" / "alerts_log.csv"
    if not p.exists():
        return []
    rules = load(root / "data" / "alert_rules.json")
    rb = {r["id"]: r for rs in rules["ruleSets"].values() if isinstance(rs, list) for r in rs}
    covered_end = max((w.get("end") or "" for w in weeks), default="")
    tz_tw = datetime.timezone(datetime.timedelta(hours=8))
    out = []
    with p.open(encoding="utf-8", newline="") as f:
        for row in _csv.DictReader(f):
            if row.get("tier") != "RED" or row.get("emailSent") != "true":
                continue
            try:
                # 警報時間記的是台北時間；CI 建置機是 UTC，必須顯式掛時區否則 exp 差 8 小時
                ts = datetime.datetime.strptime(row["datetime"], "%Y-%m-%d %H:%M").replace(tzinfo=tz_tw)
            except (ValueError, KeyError):
                continue
            day = ts.date().isoformat()
            if covered_end and day <= covered_end:
                continue  # 已被週報涵蓋 → 熄
            r = rb.get(row.get("ruleId", ""), {})
            rec = {"dt": row["datetime"], "title": row["title"], "url": row["url"],
                   "ruleId": row.get("ruleId", ""), "why": r.get("why", ""),
                   "action": r.get("action", ""), "playbook": r.get("playbook", "—"),
                   "exp": int((ts + datetime.timedelta(days=7)).timestamp() * 1000)}
            dw = root / "logs" / "daily_watch" / f"{day}.json"
            if dw.exists():
                for it in load(dw).get("items", []):
                    if it.get("url") == row["url"] and it.get("summary"):
                        rec["summary"] = it["summary"]
                        break
            out.append(rec)
    out.sort(key=lambda a: a["dt"], reverse=True)
    return out


def build_alert_layer(root: pathlib.Path, weeks: list):
    """『一則新聞的完整旅程』面板所需：警報規則 ＋ 自證基準。

    面板要在瀏覽器端即時重跑語氣剔除與警報分級，等於同一份邏輯出現第三份實作
    （plan_engine.py／daily_watch.py／JS）。金庫〈重寫的判定必須自證與正本一致〉
    的教訓是：重寫的判定若沒有自證，遲早與正本分岔而沒人發現。

    故此處以 **Python 正本** 對全部歷史事件跑一次分級，把結果一併送進頁面；
    JS 載入時用同一批事件重跑並逐則比對，不一致即在畫面上示警。
    ⚠ 比對前 JS 必須先 deEnt()——DATA.weeks 的字串在建置時已 HTML 跳脫，
    而這裡的基準是用未跳脫的原文算的。
    """
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import daily_watch as DW

    rules = load(root / "data" / "alert_rules.json")
    active = rules["ruleSets"][rules["activeCompanyType"]]

    expect = []
    for w in weeks:
        for i, e in enumerate(w.get("events") or []):
            text = f'{e.get("title", "")} {e.get("summary", "")}'
            m = DW.classify(text)
            # week 在 build_payload 內已正規化為整數，但本函式也可能被單獨呼叫測試；
            # 兩種格式都吃，避免出現 "WW1-0" 這種鍵
            expect.append({"k": f'W{str(w["week"]).lstrip("Ww")}-{i}',
                           "tier": DW.tier_of(m),
                           "ids": sorted(r["id"] for r, _ in m)})
    return {
        "companyType": rules["activeCompanyType"],
        "tiers": rules["tiers"],
        "rules": [{"id": r["id"], "tier": r["tier"], "match": r["match"],
                   "why": r.get("why", ""), "action": r.get("action", ""),
                   "playbook": r.get("playbook", "—")} for r in active],
        # 語氣剔除詞表：JS 鏡像必須用同一份，不可各自維護
        "neg": list(DW.NEG), "negOk": list(DW.NEG_OK),
        "hypo": list(DW.HYPO), "hypoOk": list(DW.HYPO_OK),
        "clause": DW._CLAUSE.pattern,
        "selfCheck": expect,
    }


def build_playbook_coverage(weeks: list, pb: dict):
    """劇本覆蓋率：每條在已發佈週次中觸發過幾次，未觸發者列出卡在哪個條件。

    刻意於建置時計算而非寫死——新增週次後數字自動跟上，不會出現「網站說 11 週、
    資料已有 12 週」的過期宣稱。

    「從未觸發」有兩種，性質完全不同，必須分開呈現：
      · 條件真的沒發生（如 Spring 擴張窗口要 X 轉正，而十一週全碎裂）→ 正確休眠
      · 條件自相矛盾、永不可能成立 → 設計缺陷
    後者由 playbook.json 的 _designNote 人工標註；本函式只負責算出「幾次、卡在哪」。
    """
    fired = {p["id"]: [] for p in pb["playbooks"]}
    for w in weeks:
        for f in ((w.get("companyPlan") or {}).get("firedPlaybooks") or []):
            if f["id"] in fired:
                fired[f["id"]].append(w["week"])

    def blockers(p):
        """未觸發者：逐條件統計在幾週成立，找出從未成立的那些（＝真正的阻擋條件）。"""
        out = []
        for c in p["trigger"]["conditions"]:
            if c["type"] == "axis":
                vals = [w["xy"][c["axis"]] for w in weeks]
                label = f'{c["axis"].upper()} {c["op"]} {c["value"]}'
                rng = f'實際 {min(vals):+.2f}～{max(vals):+.2f}'
            elif c["type"] == "kdf":
                vals = [w["w"][c["id"] - 1] for w in weeks]
                label = f'KDF#{c["id"]} {c["op"]} {c["value"]}'
                rng = f'實際 {min(vals)}～{max(vals)}'
            else:
                continue                      # 關鍵字條件逐週文字比對，不在此統計
            ok = sum(1 for v in vals if _CMP[c["op"]](v, c["value"]))
            out.append({"cond": label, "range": rng, "metWeeks": ok, "total": len(weeks)})
        return out

    rows = []
    for p in pb["playbooks"]:
        n = len(fired[p["id"]])
        r = {"id": p["id"], "title": p["title"], "count": n,
             "weeks": [f"W{w}" for w in fired[p["id"]]]}
        if n == 0:
            r["blockers"] = blockers(p)
            if p.get("_designNote"):
                r["defect"] = p["_designNote"]
        rows.append(r)
    return {"weeks": len(weeks), "rows": rows,
            "everFired": sum(1 for r in rows if r["count"] > 0), "total": len(rows)}


_CMP = {"<=": lambda a, b: a <= b, ">=": lambda a, b: a >= b,
        "<": lambda a, b: a < b, ">": lambda a, b: a > b, "==": lambda a, b: a == b}


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

    # 風險雷達的事後結果：獨立檔於此合併，weeks.json 不動（append-only）。
    # 與 coverage 同一模式——衍生／後補的顯示值一律不寫回正本。
    oc_path = root / "data" / "risk_outcomes.json"
    if oc_path.exists():
        oc = load(oc_path)["outcomes"]
        used = set()
        for w in weeks:
            for i, r in enumerate(w.get("riskRadar") or []):
                key = f"W{w['week']}-{i}"
                hit = oc.get(key)
                if hit:
                    used.add(key)
                    r["status"] = hit["status"]
                    if hit.get("followUp"):
                        r["followUp"] = hit["followUp"]
        # 鍵是「週次＋索引」，某週的 riskRadar 一旦增刪就會整排錯位而無聲貼錯風險。
        # 對不上的鍵直接中止，不要讓錯誤的結果判定上站。
        orphan = sorted(set(oc) - used)
        if orphan:
            raise SystemExit(f"[錯誤] risk_outcomes.json 有 {len(orphan)} 個鍵找不到對應風險："
                             f"{orphan}——riskRadar 筆數已變動，請重新核對索引")

    cfg = load(root / "data" / "kdf_config.json")
    prof = load(root / "data" / "company_profile.json")
    # 產業定位基礎盤（§02）。與 kdf_config／playbook 同屬版本控管之自家設定檔，
    # 內容由人工撰寫而非檢索結果，故與它們一致：不施用 escape_html_deep。
    pos_path = root / "data" / "industry_position.json"
    position = load(pos_path) if pos_path.exists() else None
    pb = load(root / "data" / "playbook.json")
    ex_path = root / "data" / "kdf_definitions.json"
    extras = load(ex_path) if ex_path.exists() else {"kdfDefs": {}, "scenarioMeta": []}

    coverage = build_coverage(weeks)      # 以未跳脫的原值推導日期，須早於跳脫
    companies = build_companies(root, weeks, prof, pb)   # 亦須用未跳脫的原值計算
    token_dev = build_token_dev(root)
    return {
        # 模型名稱來自各工具的紀錄檔（非自家設定檔），與 weeks 同樣施用跳脫
        # 即時警報同樣來自外部新聞文字，與 weeks 一體施用跳脫
        "alerts": escape_html_deep(build_alerts(root, weeks)),
        "tokenDev": escape_html_deep(token_dev) if token_dev else None,
        "companies": escape_html_deep(companies) if companies else None,
        "weeks": escape_html_deep(weeks),
        "kdf": cfg["kdf"],
        "dims": cfg["dimensions"],
        "horizons": pb["horizons"],
        # 觸發條件原文，供前端規則模擬器重跑判定。playbook.json 是版本控管的自家檔，
        # 與 horizons 同樣不施跳脫。只帶欣銓正本這一組——示範企業各有劇本組，
        # 模擬器僅對 co.real 開放。
        "triggers": {p["id"]: {"title": p["title"], **p["trigger"]} for p in pb["playbooks"]},
        "levers": {l["id"]: l for l in prof["decision_levers"]},
        "profile": prof,
        "position": position,
        # 劇本覆蓋率：以未跳脫的原值計算（同 coverage／companies）
        "pbCoverage": build_playbook_coverage(weeks, pb),
        # 警報層與自證基準（同上，須用未跳脫原值）；規則檔為自家版控檔，不施跳脫
        "alertLayer": build_alert_layer(root, weeks),
        "kdfDefs": extras.get("kdfDefs", {}),
        "scenarioMeta": extras.get("scenarioMeta", []),
        "coverage": coverage,
    }


def js_safe_json(payload) -> str:
    """序列化為可安全嵌入 <script> 的 JSON。

    `json.dumps` 不會跳脫 `<`，故資料中若出現 `</script>` 就能提前關閉標籤、
    其後的內容會被當成 HTML 解析並執行（管線資料來自 Tavily 與模型輸出，
    不完全可控）。將 `<` `>` `&` 改寫為 `\\u00XX`：這三個字元只可能出現在
    JSON 的字串值裡（結構字元僅 {}[],:"），改寫後**解析結果完全相同**。
    另跳脫 U+2028／U+2029——它們是合法的 JSON 字元卻是 JS 的行終止符。

    這是全站唯一的注入咽喉點，`build_site` / `build_offline` / `build_token_app`
    共用同一份。**不要在別處另寫一份**——重複的組裝邏輯是安全修補的隱形破口，
    只在一邊修就會無聲分歧。
    """
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    safe = (raw.replace("<", "\\u003c").replace(">", "\\u003e")
               .replace("&", "\\u0026")
               .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
    if json.loads(safe) != payload:          # 等價性硬性保證，不等價即中止
        raise AssertionError("payload 跳脫後與原資料不等價")
    return safe


def payload_js(root: pathlib.Path) -> str:
    return js_safe_json(build_payload(root))
