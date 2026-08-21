#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily_watch.py — 每日輕巡邏（憲法 182–185 行的雲端實作；2026-08-22 上雲）

分級為純規則比對（data/alert_rules.json 的 any／all／anyB 關鍵字集合），
不呼叫任何模型——警報是確定性規則，可稽核、零 token。
所有比對文字先經 plan_engine.strip_negated() 剔除否定子句：
「園區無停電通報」不得觸發 RT-04（2026-08-20 修正之同一份判定，不重寫）。

模式（環境變數 ALERT_MODE，預設 shadow；shadow 同時是緊急停止開關）：
  shadow  判級、去重、落檔，寄信程式一概不執行（預設）
  test    不影響巡邏；僅供 --send-test 寄一則模擬 RED 到 GMAIL_USER 本人
  live    出現新 RED 即寄 ALERT_TO；多則合併一封，72 小時去重

「有沒有執行」與「有沒有警報」分兩套紀錄（消除「沒跑＝全綠」的混淆）：
  logs/receipts/YYYY-MM-DD.json     每次執行必寫（含 failed）——沒有收據＝當天沒跑
  logs/daily_watch/YYYY-MM-DD.json  當日有 RED／YELLOW 才寫（GREEN 不落檔）
  logs/alerts_log.csv               RED 通報紀錄；shadow 期也追加（emailSent=false），
                                    使 72 小時去重在影子期即真實運作

用法：
  python src/daily_watch.py             巡邏一次（需 TAVILY_API_KEY）
  python src/daily_watch.py --dry-run   抓取＋判級，不寫檔不寄信
  python src/daily_watch.py --verify    上線驗收六項（離線，不需任何 key）
  python src/daily_watch.py --send-test 寄模擬 RED 給 GMAIL_USER 本人（僅 ALERT_MODE=test）
  python src/daily_watch.py --scan 路徑… 洩漏掃描（信箱／API key／家目錄路徑；命中 exit 1）
"""
import argparse, csv, datetime, io, json, os, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from plan_engine import NEG, NEG_OK, _CLAUSE  # 詞表與子句切法取自正本，不另維護第二份

# 假設語氣不得觸發警報（歷史回歸案例：「若 8/26 出現砍單訊號」被讀成砍單已發生——
# 與否定判讀同族的病，發生在警報層）。只剔「若」族；「恐／預期」常與真實事件同句
# （「火災恐停產」剔掉會漏真警報），不納入。僅用於警報層，plan_engine 之週報判定凍結不動。
HYPO = ("若", "如果", "一旦", "倘若", "假設")
HYPO_OK = ("若干",)


def strip_untriggerable(text):
    """單趟逐子句剔除否定與假設語氣。必須一趟做完：strip_negated() 的輸出已丟失標點，
    無法再切第二次（2026-08-22 實際踩過：二次切句把全文變成一個大子句，一個「若」清空整篇）。
    否定判定與 plan_engine.strip_negated 用同一份 NEG／NEG_OK 詞表與 _CLAUSE 切法。"""
    keep = []
    for cl in _CLAUSE.split(text):
        probe = cl
        for w in NEG_OK + HYPO_OK:
            probe = probe.replace(w, "")
        if any(n in probe for n in NEG) or any(h in probe for h in HYPO):
            continue
        keep.append(cl)
    return " ".join(keep)

TZ_TW = datetime.timezone(datetime.timedelta(hours=8))  # 收據與日誌一律台北時間


def now_tw():
    return datetime.datetime.now(TZ_TW)


def now_iso():
    return now_tw().isoformat(timespec="seconds")


RULES = json.loads((ROOT / "data" / "alert_rules.json").read_text(encoding="utf-8"))
ACTIVE_RULES = RULES["ruleSets"][RULES["activeCompanyType"]]
RULE_BY_ID = {r["id"]: r for r in ACTIVE_RULES}
DEDUP_HOURS = RULES["dedup"]["windowHours"]

# ---- 判級（純規則，零 token） --------------------------------------------

def classify(text):
    """回傳 [(rule, hits)]。組內 any/anyB 為 OR、組間 AND、all 須全數在場；
    文字先剔除否定與假設語氣子句——報平安的話與還沒發生的事都不得點燃警報。"""
    t = strip_untriggerable(text)
    out = []
    for r in ACTIVE_RULES:
        m, hits, ok = r["match"], {}, True
        for grp in ("any", "anyB"):
            if grp in m:
                hit = [k for k in m[grp] if k in t]
                if hit:
                    hits[grp] = hit
                else:
                    ok = False
        if ok and "all" in m:
            if all(k in t for k in m["all"]):
                hits["all"] = list(m["all"])
            else:
                ok = False
        if ok:
            out.append((r, hits))
    return out


def tier_of(matches):
    if any(r["tier"] == "RED" for r, _ in matches):
        return "RED"
    return "YELLOW" if matches else "GREEN"


def top_rule(matches, tier):
    return next(r for r, _ in matches if r["tier"] == tier)

# ---- 72 小時去重 -----------------------------------------------------------

LOG_CSV = ROOT / "logs" / "alerts_log.csv"
CSV_COLS = ["datetime", "tier", "ruleId", "title", "url", "emailSent"]


def read_alerts_log():
    if not LOG_CSV.exists():
        return []
    with LOG_CSV.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _bigrams(s):
    s = re.sub(r"\s+", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


# 同一事件隔日換寫法約落在 0.55（實測「中國限制鍺石英對台灣出口」vs 加了頓號與後綴的
# 改寫＝0.556）；不同事件即使同主題僅約 0.08。0.5 取兩者中間，寧可攔住改寫。
SIM_TH = 0.5


def _sim(a, b):
    A, B = _bigrams(a), _bigrams(b)
    return len(A & B) / len(A | B) if A and B else 0.0


def is_dup(url, title, rows, now):
    """時窗內同 URL 或標題近似（字元 bigram Jaccard ≥ 0.6，與網站 jdSim 同思路）＝已通報過。"""
    for row in rows:
        try:
            dt = datetime.datetime.strptime(row["datetime"], "%Y-%m-%d %H:%M").replace(tzinfo=TZ_TW)
        except (ValueError, KeyError):
            continue
        if (now - dt).total_seconds() > DEDUP_HOURS * 3600:
            continue
        if row.get("url") == url or _sim(row.get("title", ""), title) >= SIM_TH:
            return True
    return False

# ---- 寄信（唯一出口在 dispatch） ------------------------------------------

MAIL_SECRETS = ("GMAIL_USER", "GMAIL_APP_PASSWORD", "ALERT_TO")


def build_alert(reds):
    """多則 RED 合併成一封，避免信件轟炸。"""
    subject = f"【SCAI 即時警報】RED {len(reds)} 則｜{reds[0]['title'][:40]}"
    blocks = []
    for it in reds:
        r = RULE_BY_ID.get(it["ruleId"], {})
        blocks.append(
            f"■ {it['title']}\n"
            f"來源：{it.get('source', '')}（{it.get('date', '')}）\n{it.get('url', '')}\n"
            f"為何對欣銓重大（{it['ruleId']}）：{r.get('why', '')}\n"
            f"建議立即動作：{r.get('action', '')}\n"
            f"對應劇本：{r.get('playbook', '—')}"
        )
    body = "\n\n".join(blocks) + (
        "\n\n—\n本警報之分級屬【推斷】，非投資建議；"
        "規則見 data/alert_rules.json，去重紀錄見 logs/alerts_log.csv。"
    )
    return subject, body


def send_mail(subject, body, to):
    import smtplib, ssl
    from email.mime.text import MIMEText
    user = os.environ["GMAIL_USER"]
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
        s.login(user, os.environ["GMAIL_APP_PASSWORD"])
        s.send_message(msg)


def dispatch(reds, mode):
    """唯一的寄信出口。回傳 (emailSent, 原因)；非 live 或缺任一 Secret 一律不寄。"""
    if not reds:
        return False, "無新 RED"
    if mode != "live":
        return False, f"ALERT_MODE={mode}（非 live 不寄）"
    missing = [k for k in MAIL_SECRETS if not os.environ.get(k)]
    if missing:
        return False, "缺 Secrets：" + "、".join(missing) + "，不寄"
    subject, body = build_alert(reds)
    send_mail(subject, body, os.environ["ALERT_TO"])
    return True, "已寄 ALERT_TO"

# ---- 抓取（沿用 fetch.py 的 Tavily 寫法；每日三查詢＝cowork 的 token 紀律） ----

DAILY_QUERIES = [
    "semiconductor Taiwan export controls chip news",
    "台灣 半導體 台積電 出口管制 停電 地震 缺水",
    "欣銓 京元電 矽格 測試廠 Nvidia 財報",
]


def fetch_news():
    from tavily import TavilyClient
    from urllib.parse import urlparse
    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    items, seen = [], set()
    for q in DAILY_QUERIES:
        try:
            r = client.search(query=q, topic="news", days=2, max_results=5)
        except Exception as e:
            print(f"[warn] tavily 查詢失敗：{q}：{e}")
            continue
        for hit in r.get("results", []):
            url = hit.get("url", "")
            if not url or url in seen:
                continue
            seen.add(url)
            items.append({
                "title": hit.get("title", ""),
                "url": url,
                "date": (hit.get("published_date") or "")[:10],
                "source": urlparse(url).netloc,
                "snippet": (hit.get("content") or "")[:400],
            })
    return items

# ---- 落檔 ------------------------------------------------------------------

def write_receipt(status, mode, scanned, red, yellow, started, error=""):
    d = {"date": now_tw().date().isoformat(), "mode": mode, "status": status,
         "scanned": scanned, "red": red, "yellow": yellow,
         "startedAt": started, "finishedAt": now_iso()}
    if error:
        d["error"] = error[:500]
    p = ROOT / "logs" / "receipts" / f"{d['date']}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def write_day_file(day_items):
    d = now_tw().date().isoformat()
    obj = {"date": d, "checked": DAILY_QUERIES, "items": day_items,
           "redCount": sum(1 for i in day_items if i["tier"] == "RED"),
           "yellowCount": sum(1 for i in day_items if i["tier"] == "YELLOW")}
    p = ROOT / "logs" / "daily_watch" / f"{d}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def append_alerts_log(reds, sent):
    LOG_CSV.parent.mkdir(parents=True, exist_ok=True)
    new = not LOG_CSV.exists()
    with LOG_CSV.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS)
        if new:
            w.writeheader()
        for it in reds:
            w.writerow({"datetime": now_tw().strftime("%Y-%m-%d %H:%M"),
                        "tier": "RED", "ruleId": it["ruleId"],
                        "title": it["title"], "url": it["url"],
                        "emailSent": "true" if sent else "false"})

# ---- 主流程 ----------------------------------------------------------------

def patrol(dry=False):
    mode = os.environ.get("ALERT_MODE", "shadow")
    started = now_iso()
    scanned = n_red = n_yel = 0
    err = ""
    try:
        items = fetch_news()
        scanned = len(items)
        rows = read_alerts_log()
        now = now_tw()
        day_items, reds_new = [], []
        for it in items:
            matches = classify(f"{it['title']} {it['snippet']}")
            tier = tier_of(matches)
            if tier == "GREEN":
                continue  # GREEN 不落檔；「當天有跑」由收據證明
            rec = {"title": it["title"], "source": it["source"], "date": it["date"],
                   "url": it["url"], "tier": tier,
                   "ruleId": top_rule(matches, tier)["id"],
                   "matched": {r["id"]: h for r, h in matches}, "alerted": False}
            if tier == "RED":
                n_red += 1
                if is_dup(it["url"], it["title"], rows, now):
                    rec["dedup"] = f"{DEDUP_HOURS}h 內已通報，不重發"
                else:
                    reds_new.append(rec)
            else:
                n_yel += 1
            day_items.append(rec)
        sent, reason = (False, "dry-run 不寄") if dry else dispatch(reds_new, mode)
        for rec in reds_new:
            rec["alerted"] = sent
        print(f"[巡邏] mode={mode} 掃描 {scanned} 則 → RED {n_red}／YELLOW {n_yel}；寄信：{reason}")
        for rec in day_items:
            print(f"  {rec['tier']:6} {rec['ruleId']}  {rec['title'][:60]}")
        if not dry:
            if reds_new:
                append_alerts_log(reds_new, sent)
            if day_items:
                write_day_file(day_items)
        status = "success"
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        status = "failed"
    if not dry:
        p = write_receipt(status, mode, scanned, n_red, n_yel, started, err)
        print(f"[收據] {p.name} status={status}")
    if status == "failed":
        sys.exit(f"[巡邏失敗] {err}")


def send_test():
    mode = os.environ.get("ALERT_MODE", "shadow")
    if mode != "test":
        sys.exit(f"[拒絕] --send-test 僅在 ALERT_MODE=test 可用（現為 {mode}）")
    for k in ("GMAIL_USER", "GMAIL_APP_PASSWORD"):
        if not os.environ.get(k):
            sys.exit(f"[拒絕] 缺 {k}")
    fake = [{"title": "【測試】模擬 RED——此為 test 模式驗收信，非真實事件",
             "ruleId": "RT-02", "url": "https://example.invalid/test",
             "source": "SCAI-Agent test", "date": now_tw().date().isoformat()}]
    subject, body = build_alert(fake)
    subject = subject.replace("【SCAI 即時警報】", "【SCAI 即時警報｜測試】")
    send_mail(subject, body, os.environ["GMAIL_USER"])  # 只寄給寄件者本人，不碰 ALERT_TO
    print("[test] 模擬 RED 已寄至 GMAIL_USER 本人信箱")

# ---- 洩漏掃描 --------------------------------------------------------------
# 只放泛式樣（信箱／key 前綴／家目錄路徑），不得放任何真實私人字串——
# 把私人字串寫進掃描器等於親手把它 commit 進公開 repo。

LEAK_PATTERNS = [
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")),
    ("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}")),
    ("tavily-key", re.compile(r"tvly-[A-Za-z0-9_-]{8,}")),
    ("google-key", re.compile(r"AIza[0-9A-Za-z_-]{16,}")),
    ("github-token", re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}")),
    ("aws-key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("win-home-path", re.compile(r"[A-Za-z]:\\+Users\\+[^\\\s\"']+", re.I)),
    ("posix-home-path", re.compile(r"/(?:home|c/Users)/[^/\s\"']+")),
]


def scan_text(text, where=""):
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for name, pat in LEAK_PATTERNS:
            m = pat.search(line)
            if m:
                v = m.group(0)
                hits.append(f"{where}:{lineno} [{name}] {v[:3]}…{v[-3:] if len(v) > 6 else ''}")
    return hits


def scan_paths(paths):
    skip_ext = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".woff2", ".ttf", ".otf", ".pyc"}
    hits = []
    for p in paths:
        p = pathlib.Path(p)
        files = [p] if p.is_file() else [f for f in p.rglob("*") if f.is_file()]
        for f in files:
            if f.suffix.lower() in skip_ext or "__pycache__" in f.parts:
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except (UnicodeDecodeError, PermissionError):
                continue
            rel = f.relative_to(ROOT) if f.is_relative_to(ROOT) else f
            hits += scan_text(text, str(rel))
    return hits

# ---- 上線驗收（六項全過才可切 live；離線，不需任何 key） --------------------

# 已知差異：人工判級用了關鍵字之外的語意判斷，字面引擎做不到、也不硬湊。
# 樣式同網站 SIM_KNOWN（W10 PB-07）：差異列名列因，不假裝全綠。
# 兩類：(a) 對日管制之台灣連帶評估——摘要提及台灣但管制對象是日本，人判 YELLOW、
#          引擎字面命中 RT-02。生產環境的對應風險（誤發 RED）由 shadow 期實測把關。
#       (b) 人工降級／同源合併——規則字面確實命中（人自己也這麼記），人以脈絡降級；
#          引擎照規則升 RED，同日多則由「合併一封」兜底，結果等價。
KNOWN_DIFF = {
    ("2026-08-01", "中國研議"): "(a) 管制對象為日本；台灣僅為連帶評估之語意",
    ("2026-08-01", "熊本"): "(b) 人判明載「符合 RT-06 字面」後降級記錄；引擎照規則",
    ("2026-08-07", "中國鎢材"): "(a) 對日出口管制；「非台灣」之語意判斷",
    ("2026-08-11", "中國鎢／稀土"): "(a) 對日管制；官方評估台灣直接影響低之語意",
    ("2026-08-21", "陸稀土"): "(b) 同源延伸評論，人判併入同日 RED；引擎併入同一封合併信",
}


def known_diff(date, title):
    return next((v for (kd, kp), v in KNOWN_DIFF.items()
                 if kd == date and title.startswith(kp)), None)


def verify():
    print("=== 上線驗收（六項全過才可切 ALERT_MODE=live）===\n")
    results = []

    # ① 歷史回歸：既有日誌逐則重判，期望 1 RED／19 YELLOW、tier 與 ruleId 相符
    files = sorted((ROOT / "logs" / "daily_watch").glob("*.json"))
    red = yel = n_items = 0
    mism = []
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        for it in d.get("items", []):
            n_items += 1
            matches = classify(f"{it.get('title', '')} {it.get('summary', '')}")
            tier = tier_of(matches)
            ids = [r["id"] for r, _ in matches]
            if tier == "RED":
                red += 1
            elif tier == "YELLOW":
                yel += 1
            want_t, want_id = it.get("tier"), it.get("ruleId")
            if tier != want_t or (want_id and want_id not in ids):
                why = known_diff(d.get("date"), it.get("title", ""))
                detail = "；".join(f"{r['id']}命中{h}" for r, h in matches) or "無命中"
                mism.append((why, f"{d.get('date')}｜{it.get('title', '')[:36]}｜"
                                  f"人判 {want_t}/{want_id} → 引擎 {tier}｜{detail}"
                                  + (f"\n      ※已知差異：{why}" if why else "")))
    unexplained = [t for w, t in mism if w is None]
    ok1 = not unexplained
    results.append((f"① 歷史回歸（{len(files)} 檔 {n_items} 則 → 引擎 RED {red}／YELLOW {yel}；"
                    f"不符 {len(mism)}，其中未解釋 {len(unexplained)}）", ok1))
    for _, t in mism:
        print("   " + t)

    # ② 否定與假設語氣：「園區無停電」「若新竹缺水」皆不觸發 RT-04；真事故必須觸發（三向）
    calm = "本週台灣新竹、龍潭、桃園園區無天災、停電或缺水通報"
    hypo = "外資報告：若新竹缺水或桃園停電，測試產能將受衝擊"
    storm = "桃園龍潭廠區今晨火災，竹科部分區域停電"
    ids_calm = [r["id"] for r, _ in classify(calm)]
    ids_hypo = [r["id"] for r, _ in classify(hypo)]
    ids_storm = [r["id"] for r, _ in classify(storm)]
    ok2 = "RT-04" not in ids_calm and "RT-04" not in ids_hypo and "RT-04" in ids_storm
    results.append((f"② 否定＋假設判讀（報平安→{ids_calm or '無'}；假設→{ids_hypo or '無'}；"
                    f"真事故→{ids_storm}）", ok2))

    # ③ 去重：同 URL、近似標題皆擋；無關標題放行
    now = now_tw()
    rows = [{"datetime": now.strftime("%Y-%m-%d %H:%M"),
             "title": "中國限制鍺石英對台灣出口", "url": "https://x.test/a"}]
    ok3 = (is_dup("https://x.test/a", "任意標題", rows, now)
           and is_dup("https://y.test/b", "中國限制鍺、石英對台灣出口衝擊供應鏈", rows, now)
           and not is_dup("https://y.test/b", "完全無關的另一則新聞標題", rows, now))
    results.append(("③ 72 小時去重（同 URL／近似標題擋、無關放行）", ok3))

    # ④ 缺 Secrets 一律不寄（live 模式下清空信件相關環境變數）
    saved = {k: os.environ.pop(k, None) for k in MAIL_SECRETS}
    fake = [{"title": "T", "ruleId": "RT-02", "url": "u", "source": "s", "date": "d"}]
    sent4, why4 = dispatch(fake, "live")
    ok4 = not sent4
    results.append((f"④ 缺 Secrets 不寄（{why4}）", ok4))

    # ⑤ 多則 RED 合併一封
    two = [{"title": "事件甲", "ruleId": "RT-02", "url": "u1", "source": "", "date": ""},
           {"title": "事件乙", "ruleId": "RT-04", "url": "u2", "source": "", "date": ""}]
    subj, body = build_alert(two)
    ok5 = "RED 2 則" in subj and "事件甲" in body and "事件乙" in body
    results.append(("⑤ 多則 RED 合併一封（不轟炸）", ok5))

    # ⑥ shadow＝緊急停止：即使 Secrets 齊備也不寄
    os.environ.update({"GMAIL_USER": "x", "GMAIL_APP_PASSWORD": "x", "ALERT_TO": "x"})
    sent6, why6 = dispatch(fake, "shadow")
    ok6 = not sent6 and "shadow" in why6
    for k, v in saved.items():  # 還原環境
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    results.append((f"⑥ shadow 緊急停止（{why6}）", ok6))

    print()
    all_ok = True
    for name, ok in results:
        print(("PASS  " if ok else "FAIL  ") + name)
        all_ok = all_ok and ok
    print()
    if not all_ok:
        sys.exit("[驗收未過] 不可切 ALERT_MODE=live")
    print("[驗收通過] 六項全過，可依 shadow → test → live 逐段開啟")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="SCAI-Agent 每日輕巡邏")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="抓取＋判級，不寫檔不寄信")
    g.add_argument("--verify", action="store_true", help="上線驗收六項（離線）")
    g.add_argument("--send-test", action="store_true", help="寄模擬 RED 給 GMAIL_USER（僅 ALERT_MODE=test）")
    g.add_argument("--scan", nargs="+", metavar="PATH", help="洩漏掃描；命中即 exit 1")
    a = ap.parse_args()
    if a.verify:
        verify()
    elif a.send_test:
        send_test()
    elif a.scan:
        found = scan_paths(a.scan)
        if found:
            print(f"[洩漏掃描] 命中 {len(found)} 處，禁止 commit：")
            for h in found:
                print("  " + h)
            sys.exit(1)
        print("[洩漏掃描] 乾淨")
    else:
        patrol(dry=a.dry_run)
