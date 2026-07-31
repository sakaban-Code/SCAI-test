"""
fetch.py — 抓取層（純搜尋 API + RSS，不使用任何模型生成，符合競賽模型限制）
產出: weekly/{WEEK}/raw_items.json  （候選事件原始清單，含 URL/日期/來源）
"""
import json, os, datetime, pathlib
import feedparser
from tavily import TavilyClient

ROOT = pathlib.Path(__file__).resolve().parent.parent

# ---- 本週編號與日期範圍 -------------------------------------------------
def current_week_label() -> tuple[str, str]:
    """依 data/weeks.json 既有筆數遞增週次；回傳 (週標籤, 日期範圍字串)"""
    weeks_file = ROOT / "data" / "weeks.json"
    n = 1
    if weeks_file.exists():
        n = len(json.loads(weeks_file.read_text(encoding="utf-8"))) + 1
    today = datetime.date.today()
    start = today - datetime.timedelta(days=7)
    rng = f"{start:%Y/%m/%d}–{today:%Y/%m/%d}"
    return f"W{n}", rng

WEEK, DATE_RANGE = current_week_label()
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
    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    items = []
    for q in QUERIES:
        try:
            r = client.search(query=q, topic="news", days=7, max_results=5)
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
    cutoff = datetime.datetime.now() - datetime.timedelta(days=7)
    items = []
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for e in feed.entries[:20]:
                pub = e.get("published_parsed") or e.get("updated_parsed")
                if pub and datetime.datetime(*pub[:6]) < cutoff:
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
    raw = fetch_tavily() + fetch_rss()
    # 依 URL 去重
    seen, deduped = set(), []
    for it in raw:
        if it["url"] and it["url"] not in seen:
            seen.add(it["url"])
            deduped.append(it)

    payload = {"week": WEEK, "range": DATE_RANGE,
               "fetched_at": datetime.datetime.now().isoformat(),
               "items": deduped}
    (OUT_DIR / "raw_items.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] {WEEK} ({DATE_RANGE}) 抓取 {len(deduped)} 則候選事件 → {OUT_DIR/'raw_items.json'}")
