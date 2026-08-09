"""
fetch.py — 抓取層（純搜尋 API + RSS，不使用任何模型生成，符合競賽模型限制）
產出: weekly/{WEEK}/raw_items.json  （候選事件原始清單，含 URL/日期/來源）

兩種模式：
  一般週跑    python src/fetch.py
              週次＝weeks.json 筆數+1；區間起日＝上一週迄日的次日、迄日＝今天
              （錨定上一週迄日而非 today−7，否則會與前一週重疊一天）
  回補歷史週  python src/fetch.py --week 7 --start 2026-07-21 --end 2026-07-27
              指定週次與區間；Tavily 改用 start_date/end_date 搜該區間，
              **RSS 自動跳過**（feed 不保留歷史，抓到的會是近期新聞＝假證據）
"""
import argparse, json, os, datetime, pathlib, sys
# tavily／feedparser 改為延遲匯入：讓參數驗證先行，錯誤參數不必等到套件與網路就緒才報

ROOT = pathlib.Path(__file__).resolve().parent.parent

from weekcal import fmt_range, parse_range_end, last_week_entry, wnum


def resolve_window() -> tuple[str, str, datetime.date, datetime.date, bool]:
    """回傳 (週標籤, 區間字串, 起日, 迄日, 是否為回補模式)"""
    ap = argparse.ArgumentParser(description="SCAI-Agent 抓取層")
    ap.add_argument("--week", type=int, help="指定週次編號（回補用）；省略＝依 weeks.json 筆數遞增")
    ap.add_argument("--start", help="區間起日 YYYY-MM-DD（回補用，需與 --end 併用）")
    ap.add_argument("--end", help="區間迄日 YYYY-MM-DD（回補用）")
    ap.add_argument("--force", action="store_true",
                    help="略過「中間有缺漏週次」的防呆，改以最近 7 天當本週（明示接受與前期不連續）")
    a = ap.parse_args()

    if bool(a.start) != bool(a.end):
        sys.exit("[錯誤] --start 與 --end 必須成對給定")

    weeks_file = ROOT / "data" / "weeks.json"
    existing = json.loads(weeks_file.read_text(encoding="utf-8")) if weeks_file.exists() else []
    n = a.week if a.week else len(existing) + 1

    if a.week and any(str(w.get("week")).lstrip("Ww") == str(a.week) for w in existing):
        sys.exit(f"[錯誤] W{a.week} 已存在於 data/weeks.json（append-only 鐵則，不覆寫）")

    if a.start:
        s = datetime.date.fromisoformat(a.start)
        e = datetime.date.fromisoformat(a.end)
        if e < s:
            sys.exit("[錯誤] --end 早於 --start")
        if e > datetime.date.today():
            sys.exit(f"[錯誤] 迄日 {e} 尚未到來，該週資料不完整，不可回補")
        backfill = True
    else:
        e = datetime.date.today()
        backfill = False
        last = last_week_entry(existing)
        last_end = None
        if last:
            try:
                last_end = parse_range_end(last["range"])
            except ValueError:
                # 解析失敗不可靜默放行：last_end=None 會讓下面自動退回「最近 7 天」，
                # 等於未經 --force 就繞過所有錨定與防呆（fail-open）。
                if not a.force:
                    sys.exit(
                        f"[錯誤] 最後一週 {last.get('week')} 的 range 無法解析："
                        f"{last.get('range')!r}。\n"
                        f"       無法錨定本週窗口起點。請先修正 data/weeks.json，"
                        f"或加 --force 以最近 7 天強行執行。")
                last_end = None

        # 缺漏防呆：距上一週迄日超過 8 天代表中間有週次沒產出。
        # 照常週跑會把「下一個編號」貼上一整段跨越缺漏的區間，週次與日期就此永久錯位。
        if last_end and not a.force and (e - last_end).days > 8:
            gap = (e - last_end).days
            sys.exit(
                f"[錯誤] 距上一週 {last['week']}（{last['range']}，迄 {last_end}）已 {gap} 天，"
                f"中間有缺漏週次。\n"
                f"       直接週跑會把 W{n} 標成 {fmt_range(last_end + datetime.timedelta(days=1), e)}"
                f"（{gap} 天），造成週次與日期永久錯位。\n"
                f"       請先回補：python src/backfill.py            （只看計畫）\n"
                f"                 python src/backfill.py --execute  （實際回補）\n"
                f"       若確定要略過缺漏直接跑本週，加 --force。")

        # 起日錨定「上一期迄日的次日」，不是 today−7。
        # 用 today−7 會得到含頭尾 8 天、且與上一期迄日重疊一天的窗口——這正是
        # W3/W4 重疊 3 天、07/06 落空的同一個成因（窗口接的是產出日而非窗口迄日）。
        # --force 屬明示略過缺漏，維持「最近 7 天」語意並接受與前期不連續。
        if last_end and not a.force:
            s = last_end + datetime.timedelta(days=1)
            if e < s:
                sys.exit(
                    f"[錯誤] 上一週 {last['week']} 迄日為 {last_end}，本次觸發於 {e}，"
                    f"尚無可涵蓋的新區間。\n"
                    f"       請待窗口累積後再跑，或以 --start/--end 明確指定區間。")
            # 窗口未滿 7 天不得成週：提早手動跑會固化一個殘週（append-only 修不回來），
            # 且下次排程只剩更短的畸零區間——例如 08/09 手跑產出 6 天的 W9，
            # 08/10 排程就只能把 W10 標成 1 天。滿週才放行，寧可請使用者晚點跑。
            days = (e - s).days + 1
            if days < 7:
                ready = s + datetime.timedelta(days=6)
                sys.exit(
                    f"[錯誤] 窗口尚未滿一週：{fmt_range(s, e)} 僅 {days} 天。\n"
                    f"       W{n} 應涵蓋至 {ready}，請於該日或之後再跑；"
                    f"或以 --start/--end 明確指定完整區間。")
        else:
            s = e - datetime.timedelta(days=6)   # 含頭尾 7 天

    return f"W{n}", fmt_range(s, e), s, e, backfill


WEEK, DATE_RANGE, START, END, BACKFILL = resolve_window()
OUT_DIR = ROOT / "weekly" / WEEK
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---- 1. Tavily 主題式搜尋（過去 7 天） ----------------------------------
QUERIES = [
    "semiconductor export controls geopolitics",
    "semiconductor supply chain disruption materials helium tungsten",
    "TSMC Samsung SK Hynix Intel major announcement",
    "AI chip demand testing OSAT",
    "Taiwan semiconductor policy CHIPS subsidy",
    "半導體 測試 封測 出口管制",
]

def fetch_tavily() -> list[dict]:
    from tavily import TavilyClient
    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    # 一律以宣告窗口的起訖日鎖定搜尋區間。原本一般週跑用 days=7 滾動窗，
    # 與錨定後的宣告窗口會漂移：08/11 延遲觸發宣告 08/04–08/11，days=7 卻抓不到 08/04。
    window = {"start_date": START.isoformat(), "end_date": END.isoformat()}
    items = []
    for q in QUERIES:
        try:
            r = client.search(query=q, topic="news", max_results=5, **window)
            for hit in r.get("results", []):
                items.append({
                    "title":  hit.get("title", ""),
                    "url":    hit.get("url", ""),
                    "date":   hit.get("published_date", ""),
                    "snippet": (hit.get("content") or "")[:500],
                    "source": "tavily",
                    "query":  q,
                })
        except Exception as e:
            print(f"[warn] tavily query failed: {q}: {e}")
    return items

# ---- 2. RSS 權威來源 -----------------------------------------------------
RSS_FEEDS = [
    "https://www.digitimes.com.tw/rss/daily.xml",
    "https://technews.tw/feed/",
    # 可自行增補：BIS 出口管制公告、SEMI、各大廠 IR RSS
]

def fetch_rss() -> list[dict]:
    import feedparser
    items = []
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for e in feed.entries[:20]:
                # 以宣告窗口過濾（原為「現在−7 天」滾動窗，與宣告區間會漂移）。
                # 無日期的項目一律剔除：無法證明落在窗口內，與匯入門檻的時序可查證要求一致。
                pub = e.get("published_parsed") or e.get("updated_parsed")
                if not pub:
                    continue
                d = datetime.date(*pub[:3])
                if d < START or d > END:
                    continue
                items.append({
                    "title":  e.get("title", ""),
                    "url":    e.get("link", ""),
                    "date":   e.get("published", ""),
                    "snippet": (e.get("summary") or "")[:500],
                    "source": "rss",
                    "query":  feed_url,
                })
        except Exception as e:
            print(f"[warn] rss failed: {feed_url}: {e}")
    return items

# ---- 主流程 ---------------------------------------------------------------
if __name__ == "__main__":
    raw = fetch_tavily()
    if BACKFILL:
        # RSS feed 只保留最近數十筆，回補歷史週時抓到的一定是近期新聞＝假證據，故跳過
        print("[回補] 略過 RSS：feed 無歷史回溯能力，該週事件來源僅 Tavily 區間搜尋")
    else:
        raw += fetch_rss()

    # 依 URL 去重
    seen, deduped = set(), []
    for it in raw:
        if it["url"] and it["url"] not in seen:
            seen.add(it["url"])
            deduped.append(it)

    payload = {"week": WEEK, "range": DATE_RANGE,
               "fetched_at": datetime.datetime.now().isoformat(),
               "backfill": BACKFILL,
               "items": deduped}
    if BACKFILL:
        payload["sources_note"] = (
            f"本週為事後回補（抓取日 {datetime.date.today().isoformat()}，"
            f"區間 {START.isoformat()}–{END.isoformat()}）。"
            "事件來源僅 Tavily 區間搜尋；RSS 因 feed 不保留歷史而未納入，"
            "故候選事件數可能少於一般週跑。")
    (OUT_DIR / "raw_items.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    mode = "回補" if BACKFILL else "週跑"
    print(f"[ok] {WEEK}（{DATE_RANGE}｜{mode}）抓取 {len(deduped)} 則候選事件 → {OUT_DIR/'raw_items.json'}")
