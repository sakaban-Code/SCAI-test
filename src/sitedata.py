# -*- coding: utf-8 -*-
"""網站 payload 組裝（build_site.py 與 build_offline.py 共用，無副作用）。

原本兩支建置腳本各自複製一份相同的 payload 程式碼，任一邊加欄位就會無聲分歧；
抽出於此後兩邊必然一致。

本模組**不讀寫 data/ 以外的東西、也不修改 weeks.json**：`days`／`start`／`end`
與 `coverage` 全部是由既有的 `range` 字串與 `gen` 欄位**推導**出來的顯示用衍生值。
"""
import copy, datetime, json, pathlib, re, sys

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

    - 欣銓（real=True）：§13 規畫仍取 weeks.json 的 companyPlan（append-only 官方紀錄，
      不重算）；此處只帶 §15 畫像顯示資料。
    - 示範企業（real=False）：於建置時以 plan_engine 對**真實週次資料**逐週重算——
      觸發依據引用的座標／KDF／關鍵字都是真實的，虛構的只有企業本身。
      展示「同一套情境判定 × 不同企業畫像 → 不同觸發結果」的引擎可移植性。
    demo_profiles.json 不存在時只回傳欣銓一筆，網站自動退回單一企業模式（不顯示切換器）。
    """
    # 欣銓的畫像資料（§15 四張統計卡）改由此供給，故 demo_profiles.json 不存在時
    # 不能整個回 None——那會讓 §15 拿到空的 stats 陣列而少掉四張卡。
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
        return companies          # 只有欣銓：§15 照常渲染，模板不顯示切換器

    demo = load(demo_path)
    for c in demo["companies"]:
        pbwrap = {"playbooks": c["playbooks"]}
        profwrap = {"scenario_stance": c["scenario_stance"]}
        plans = {}
        for w in weeks:                      # weeks＝正規化後、跳脫前的原值
            p = plan_engine.build_plan(w, profwrap, pbwrap)
            p["note"] = "示範資料：示範企業（名稱虛構），用於展示引擎可移植性；觸發依據引用的週次資料為真實紀錄。"
            plans[str(w["week"])] = p
        entry = {k: v for k, v in c.items() if k not in ("playbooks", "scenario_stance")}
        entry["real"] = False
        entry["plans"] = plans
        # 覆蓋率隨企業走：同一批真實週次，換成這家的劇本組重算
        entry["pbCoverage"] = build_playbook_coverage(weeks, pbwrap, plans)
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

    # ── 依工具彙總：必須與標頭同一個口徑 ──
    # 原檔的 byTool／byModel 是 **core＋關聯** 口徑（三工具相加＝4.93 億），
    # 而標頭取 totals.core（3.80 億）。兩者並排時，評審把三個工具加一遍就對不上標頭
    # ——與門檻④擋下 W10 的是同一種病（畫面上印著可加總的數，而它加不起來）。
    # 修法不是改標頭，是自 sessions 逐筆重新彙總 core 口徑；sessions 已在原檔裡，
    # 不必重跑 token_stats.py（重跑會把統計基準日推到今天，動到整份數字）。
    _F = ("msgs", "input", "cacheCreate", "cw5m", "cw1h", "cacheRead",
          "codexCacheRead", "output", "outputUnknown", "processed", "billableInput")

    def agg(scopes):
        out = {}
        for s in d.get("sessions") or []:
            if s.get("scope") not in scopes:
                continue
            t = out.setdefault(s.get("tool") or "?", dict.fromkeys(_F, 0))
            for f in _F:
                t[f] += s.get(f) or 0
        return out

    by_tool_core = agg({"core"})

    def sum_of(tools, field):
        return sum((by_tool_core.get(t) or {}).get(field, 0) for t in tools)

    # ── 四種口徑 ──
    # 評分表問的是「開發 AI 員工／以及 AI 員工運作時」的消耗。這兩段本來就不同源，
    # 混成一個數字既無法查證也無法優化。四段各自的狀態不同，**缺的那兩段照實說缺**：
    #   ①② 有實測數字，且 ①＋② 必須恰好等於標頭（讓人加得起來）
    #   ③ 真的是 0——不是沒統計，是從未執行
    #   ④ 有真實用量但刻意不累計——本站不記錄問答內容，見 worker/scai-ask/worker.js
    BUILD, WEEKLY = ("claude-code", "codex"), ("cowork",)
    channels = [
        {"n": "① 建構這套系統", "w": "程式、網站、CI、資料管線與文件",
         "tool": "Claude Code ＋ Codex", "state": "measured",
         "msgs": sum_of(BUILD, "msgs"),
         "billableInput": sum_of(BUILD, "billableInput"),
         "output": sum_of(BUILD, "output")},
        {"n": "② 每週報告內容產出", "w": "W1–W11 的事件分析、座標判定與撰寫",
         "tool": "Cowork", "state": "partial",
         "msgs": sum_of(WEEKLY, "msgs"),
         "billableInput": sum_of(WEEKLY, "billableInput"),
         "output": None,
         "note": "稽核紀錄於回應完成前寫入，output 不可得（非 0）"},
        {"n": "③ 每週雲端管線運作", "w": "weekly.yml 自動抓取、判定、產週報",
         "tool": "GitHub Actions", "state": "never",
         "msgs": 0, "billableInput": 0, "output": 0,
         "note": "從未執行：本專案自始至終未取得 API 預算，ANTHROPIC_API_KEY 未設定，"
                 "workflow 每次依守門條件綠色跳過。"
                 "**這一格是 0，不是未統計，也不是待補。**"},
        {"n": "④ 站上 AI 問答", "w": "評審或訪客在本站提問",
         "tool": "Cloudflare Workers AI（@cf/openai/gpt-oss-20b）", "state": "nolog",
         "msgs": None, "billableInput": None, "output": None,
         "note": "每則回答都附**當次的真實用量**；跨工作階段的累計由 Worker 以 KV 記錄"
                 "——**只存次數與 token 加總，不存任何問答內容**。"
                 "取不到累計數時（離線版、後端未回應）本列顯示「不累計」。"},
    ]

    return {
        "generated": d.get("generated") or "",
        "core": slim(core),
        "all": slim(d["totals"].get("all") or core),
        "byTool": {k: slim(v) for k, v in by_tool_core.items()},   # 已對齊標頭口徑
        "byModel": {k: slim(v) for k, v in (d.get("byModel") or {}).items()
                    if (v or {}).get("billableInput")},   # 濾掉 <synthetic> 等 0 用量項
        # byModel 無法自 sessions 重算（原檔未逐 session 拆模型），仍為 core＋關聯口徑。
        # 不硬湊：把它的合計一併送出，讓模板明講「這一列是另一個口徑」。
        "byModelScope": slim(d["totals"].get("core+related") or core),
        "channels": channels,
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


def build_dept_layer(root: pathlib.Path, weeks: list, prof: dict, pb: dict, cfg: dict):
    """部門視角：這件事該誰看。

    ⚠ **只做分派，不做評價。** 指導教授 2026-08-24 明確指出我方不掌握欣銓各部門
    的現況與成熟度，因此本層**不得**產出「某部門應該改善什麼」。可做的是把外部訊號
    分派到責任範圍（分派可由公開資訊推導），以及把**既有的**劇本建議依權責歸戶。
    建議本身仍是外部推導之【推斷】，是否適用須由該部門依內部資訊判斷。

    整條鏈全部來自既有資料，沒有新編任何對應表：
        部門  ← company_profile.decision_levers 的 owner 欄
        槓桿  → playbook 的 lever 欄  → 策略（劇本）與受影響 KDF（劇本的 kdf 欄）
        劇本  ← alert_rules 的 playbook 欄 → 該部門該看的警報規則
        規則  → 每日巡邏日誌與週事件裡命中該規則的項目
    """
    levers = prof.get("decision_levers") or []
    if not levers:
        return None
    rules = load(root / "data" / "alert_rules.json")
    active = rules["ruleSets"][rules["activeCompanyType"]]
    kdf_name = {k["id"]: k["name"] for k in cfg["kdf"]}

    # owner 可能是複合（「財務／營運」），拆開——一個部門本來就會碰多條槓桿，
    # 例如「工程」同時出現在 tech／talent／quality 三條的 owner 裡。
    dept = {}
    for l in levers:
        for o in str(l.get("owner", "")).split("／"):
            o = o.strip()
            if o:
                dept.setdefault(o, []).append(l["id"])
    # 拆完後若兩個名字管的是完全相同的槓桿（策略／董事會、資訊／資安），合併回一列——
    # 內容一字不差地重複兩次只是噪音，不是資訊。
    merged = {}
    for name, lv in dept.items():
        merged.setdefault(tuple(sorted(lv)), []).append(name)
    dept = {"／".join(sorted(names)): list(key) for key, names in merged.items()}

    pb_by_lever = {}
    for p in pb["playbooks"]:
        pb_by_lever.setdefault(p.get("lever"), []).append(p)
    rules_by_pb = {}
    for r in active:
        if r.get("playbook") and r["playbook"] != "—":
            rules_by_pb.setdefault(r["playbook"], []).append(r["id"])

    latest = weeks[-1] if weeks else {}
    fired = {f["id"] for f in ((latest.get("companyPlan") or {}).get("firedPlaybooks") or [])}

    out = []
    for name in sorted(dept):
        lv = dept[name]
        plays, kdfs, rids = [], set(), set()
        for lid in lv:
            for p in pb_by_lever.get(lid, []):
                plays.append({"id": p["id"], "title": p["title"], "lever": lid,
                              "action": p.get("action", ""), "horizon": p.get("horizon", ""),
                              "metric": p.get("success_metric", ""), "stop": p.get("stop_loss", ""),
                              "fired": p["id"] in fired})
                kdfs.update(p.get("kdf") or [])
                rids.update(rules_by_pb.get(p["id"], []))
        out.append({
            "name": name,
            "levers": [{"id": l["id"], "name": l["name"], "desc": l.get("desc", ""),
                        "speed": l.get("speed", "")} for l in levers if l["id"] in lv],
            "playbooks": sorted(plays, key=lambda x: x["id"]),
            "kdf": sorted([{"id": i, "name": kdf_name.get(i, "")} for i in kdfs],
                          key=lambda x: x["id"]),
            "rules": sorted(rids),
            "firedNow": sorted(p["id"] for p in plays if p["fired"]),
            # 該部門名下有哪幾條槓桿完全沒有劇本覆蓋——誠實標出，不假裝建議完整
            "uncovered": [l["id"] for l in levers
                          if l["id"] in lv and not pb_by_lever.get(l["id"])],
        })
    uncovered = sorted({l["id"] for l in levers if not pb_by_lever.get(l["id"])})
    return {
        "week": latest.get("week"),
        "depts": sorted(out, key=lambda d: (not d["playbooks"], d["name"])),
        "leverTotal": len(levers),
        "leverCovered": len(levers) - len(uncovered),
        "uncoveredLevers": [{"id": l["id"], "name": l["name"], "owner": l.get("owner", "")}
                            for l in levers if l["id"] in uncovered],
        "_note": "分派依據為 company_profile.json 之 decision_levers.owner；"
                 "策略即既有劇本，依 playbook.lever 歸戶。本層只做分派，不評價各部門現況。",
    }


def build_daily_layer(root: pathlib.Path):
    """每日巡邏的站上呈現。

    核心是把「**有沒有跑**」與「**有沒有警報**」分開——這正是收據制存在的理由，
    也是金庫〈零掃描的假全綠〉那條教訓的落地。四種日子必須可分辨：

      有收據＋有日誌  → 跑了，而且有發現
      有收據＋無日誌  → 跑了，零警報（GREEN 不落檔）  ← 沒有收據時，這種日子
                        會跟「根本沒跑」長得一模一樣
      無收據＋有日誌  → 收據制上線前的人工巡邏（2026-08-22 之前）
      兩者皆無        → 那天沒跑

    日誌有兩種形狀：歷史淨化匯出版（含 summary、無 matched）與 bot 產生版
    （含 matched、無 summary）。兩種都吃，缺哪個欄位就不顯示哪個。
    """
    rec_dir, dw_dir = root / "logs" / "receipts", root / "logs" / "daily_watch"
    if not dw_dir.is_dir() and not rec_dir.is_dir():
        return None

    rec = {}
    for p in sorted(rec_dir.glob("*.json")) if rec_dir.is_dir() else []:
        try:
            rec[p.stem] = load(p)
        except Exception:
            continue
    logs = {}
    for p in sorted(dw_dir.glob("*.json")) if dw_dir.is_dir() else []:
        try:
            logs[p.stem] = load(p)
        except Exception:
            continue

    all_days = sorted(set(rec) | set(logs))
    if not all_days:
        return None
    receipt_from = min(rec) if rec else ""

    days = []
    for d in all_days:
        r, g = rec.get(d), logs.get(d) or {}
        items = []
        for it in (g.get("items") or []):
            items.append({k: it[k] for k in
                          ("title", "source", "date", "url", "tier", "ruleId", "summary",
                           "alerted", "misfire")
                          if it.get(k) is not None})
        days.append({
            "d": d,
            # auto＝有收據（收據只由 Actions 寫）；manual＝收據制上線前的人工巡邏
            "how": "auto" if r else "manual",
            "status": (r or {}).get("status", ""),
            "mode": (r or {}).get("mode", ""),
            "scanned": (r or {}).get("scanned"),
            # 排除數要上站：站上寫「掃描 N 則」，若其中有幾則被丟掉而不講，
            # N 與實際判級的則數就對不起來。
            "excluded": (r or {}).get("excluded", 0),
            "at": ((r or {}).get("startedAt") or "")[11:16],
            "red": g.get("redCount", 0) if g else (r or {}).get("red", 0),
            "yellow": g.get("yellowCount", 0) if g else (r or {}).get("yellow", 0),
            "hasLog": bool(g),
            "items": items,
        })

    # 缺口：首末日之間沒有任何紀錄的日子。誠實列出，不假裝連續。
    first = datetime.date.fromisoformat(all_days[0])
    last = datetime.date.fromisoformat(all_days[-1])
    have = set(all_days)
    gaps = []
    cur = first
    while cur <= last:
        s = cur.isoformat()
        if s not in have:
            gaps.append(s)
        cur += datetime.timedelta(days=1)

    return {
        "receiptFrom": receipt_from,
        "days": days,
        "gaps": gaps,
        "span": [all_days[0], all_days[-1]],
        "autoDays": sum(1 for x in days if x["how"] == "auto"),
        "silentButRan": sum(1 for x in days if x["how"] == "auto" and not x["hasLog"]),
    }


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


def build_playbook_coverage(weeks: list, pb: dict, plans: dict | None = None):
    """劇本覆蓋率：每條在已發佈週次中觸發過幾次，未觸發者列出卡在哪個條件。

    plans 為 None 時取 weeks[].companyPlan（欣銓的正本紀錄）；示範企業則帶入
    build_companies 已用 plan_engine 逐週重算好的 {週次: plan}。原本本函式寫死
    companyPlan，導致切換企業時 §13 會變、覆蓋率卻永遠是欣銓的 PB-01…PB-08。

    刻意於建置時計算而非寫死——新增週次後數字自動跟上，不會出現「網站說 11 週、
    資料已有 12 週」的過期宣稱。

    「從未觸發」有兩種，性質完全不同，必須分開呈現：
      · 條件真的沒發生（如 Spring 擴張窗口要 X 轉正，而十一週全碎裂）→ 正確休眠
      · 條件自相矛盾、永不可能成立 → 設計缺陷
    後者由 playbook.json 的 _designNote 人工標註；本函式只負責算出「幾次、卡在哪」。
    """
    fired = {p["id"]: [] for p in pb["playbooks"]}
    for w in weeks:
        plan = plans.get(str(w["week"])) if plans is not None else w.get("companyPlan")
        for f in ((plan or {}).get("firedPlaybooks") or []):
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

    # ── 判定支撐：這一週的判斷有多少可查證的東西撐著 ──
    # 讀數面板原本有一列「判定信心」，但 weeks.json 從來沒有 confidence 欄位，
    # 十一週一路顯示「—」——介面承諾了資料沒交付的東西。
    #
    # 補法刻意**不是**補一個高／中／低等級：那要嘛是新判斷（對已發佈的十一週而言
    # 就是後見之明，違反 append-only 的精神），要嘛是憑空的量表。改為列出**既有紀錄
    # 本身就有的事實**——事件數、附連結數、決策軌跡筆數，以及兩個減分項（補記事件、
    # 資料不足標記）。這不是新的宣稱，是把已經在檔案裡的東西數出來。
    def _tagged(items, tag):
        """帶某標記的**條目數**。不可用全檔字串計數——同一則補記事件的標記會同時
        出現在標題、摘要與決策軌跡，W11 實測全檔命中 3 次但實際只有 1 則。"""
        return sum(1 for x in (items or [])
                   if tag in json.dumps(x, ensure_ascii=False))

    # 週次區間轉 ISO：§05 每日巡邏要標出「選到的這一週」落在時間軸的哪一段。
    # range 形如 "2026/06/11–06/17"（迄日省略年份），跨年時迄日年份加一。
    for w in weeks:
        m = re.match(r"(\d{4})/(\d{2})/(\d{2})\D+(\d{2})/(\d{2})", str(w.get("range") or ""))
        if m:
            y, m1, d1, m2, d2 = m.groups()
            y2 = int(y) + (1 if (m2, d2) < (m1, d1) else 0)
            w["span"] = [f"{y}-{m1}-{d1}", f"{y2}-{m2}-{d2}"]

    for w in weeks:
        ev = w.get("events") or []
        dt = w.get("decisionTrace") or []
        w["support"] = {
            "events": len(ev),
            "linked": sum(1 for e in ev if (e or {}).get("url")),
            "trace": len(dt),
            # 補記事件的標記依 2026-08-18 裁定加在 decisionTrace 的 event 欄，
            # 故以軌跡層為準（W10=3、W11=1，與週報紀錄相符）。
            "backfilled": _tagged(dt, "【補記事件"),
            "lack": (_tagged(ev, "【資料不足】") + _tagged(dt, "【資料不足】")
                     + _tagged(w.get("riskRadar"), "【資料不足】")),
        }

    # 風險雷達的事後結果：獨立檔於此合併，weeks.json 不動（append-only）。
    # 與 coverage 同一模式——衍生／後補的顯示值一律不寫回正本。
    oc_path = root / "data" / "risk_outcomes.json"
    risk_judged = ""
    if oc_path.exists():
        _ocdoc = load(oc_path)
        risk_judged = _ocdoc.get("_judged", "")
        oc = _ocdoc["outcomes"]
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

    # 判斷理由的白話層：簡略檢視用，詳細檢視仍顯示原文。同 risk_outcomes 模式，
    # 獨立檔於此合併，weeks.json 不動（已發佈週次不因可讀性回頭重寫）。
    pr_path = root / "data" / "plain_reasons.json"
    if pr_path.exists():
        pr = load(pr_path)["reasons"]
        used = set()
        for w in weeks:
            for ti, t in enumerate(w.get("decisionTrace") or []):
                for k in t.get("kdfChanges") or []:
                    hit = pr.get(f'W{w["week"]}|{ti}|{k["id"]}')
                    if not hit:
                        continue
                    used.add(f'W{w["week"]}|{ti}|{k["id"]}')
                    # 白話版是照原文改寫的；原文一旦變動，改寫就可能已不成立。
                    # 兩者不符即中止——寧可不上站，也不要讓對不上的白話冒充原意。
                    if hit["orig"] != k.get("reason"):
                        raise SystemExit(f'[錯誤] plain_reasons 的原文與 weeks.json 不符：'
                                         f'W{w["week"]}|{ti}|{k["id"]}')
                    k["reasonPlain"] = hit["plain"]
        orphan = sorted(set(pr) - used)
        if orphan:
            raise SystemExit(f"[錯誤] plain_reasons.json 有 {len(orphan)} 個鍵找不到對應的"
                             f"決策軌跡：{orphan[:5]}——decisionTrace 已變動，請重新產生")

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
        # 每日巡邏：日誌內容為外部新聞文字，與 weeks 同樣施用跳脫
        "dailyLayer": escape_html_deep(build_daily_layer(root)),
        # 部門視角：來源皆為自家版控檔（profile／playbook／alert_rules），不施跳脫
        "deptLayer": build_dept_layer(root, weeks, prof, pb, cfg),
        # 風險回測的評判截止日：晚於此日產出的週次尚未評判，回測面板據此說明而非留白
        "riskJudged": risk_judged,
        # 事前預測與否證條件。人工撰寫之版控檔，同 playbook／kdf_config 不施跳脫。
        # 檔案缺席時面板整區不顯示——寧可不講，不講半套。
        "predictions": (load(root / "data" / "predictions.json")
                        if (root / "data" / "predictions.json").exists() else None),
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
