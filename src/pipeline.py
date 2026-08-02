"""
pipeline.py — 推理層核心
Step A  Claude Sonnet  : 事件擷取與結構化      → events.json
Step B  Claude Opus    : 情境判定 + KDF 權重    → scenario.json / weights.json
Step C  Gemini         : 獨立情境判定（交叉驗證）→ cross_check.json
Step D  合併與治理標記  : 一致→通過；不一致→【建議查證】降信心
Step E  更新儀表板 WEEKS（append-only）＋ 產出 report.md
全程記錄各模型 token 用量 → token_usage.json（對應評審 20% Token 說明）
"""
import json, os, re, datetime, pathlib
import anthropic
from google import genai
import plan_engine  # 公司規畫層（提案書 Step 5）：情境 × 企業畫像 → 觸發式劇本

ROOT = pathlib.Path(__file__).resolve().parent.parent

SONNET = "claude-sonnet-5"
OPUS   = "claude-opus-4-8"
GEMINI = "gemini-2.5-pro"   # Google 系列，合規；如有新版可改此常數

KDF_LIST = [  # 凍結正本＝憲法 v2.0／提案書 1–25 編號（data/kdf_config.json），順序嚴禁變更
    "標準化","智慧財產權保護","技術策略聯盟","次世代技術量產","掌握主流及替代產品（AI晶片）",
    "先進技術研發","量子及材料技術突破","垂直整合能力","標準化趨勢","領導公司策略",
    "新興競爭者形成","市場競爭力","市場穩定成長","掌握未來市場（Meta/6G）","相關產業發展",
    "經濟情勢","全球供應鏈重組","研發減免稅賦","管制政策發展","穩定供水與供電",
    "開放人才引進","開放境外投資／保護主義","自由貿易協定","外交因素（境外投資保護）","注重環保（ESG）",
]

AXES_DEF = ("X 軸=地緣與供應鏈聚合程度（−1 碎裂 Fragmentation ↔ +1 聚合 Integration）；"
            "Y 軸=產業營運資源與政策充沛度（−1 匱乏 Scarcity ↔ +1 充沛 Ample）")
SCENARIOS_DEF = ("四象限：X+Y+ 情境一：全球共榮的盛夏(Spring) / X−Y+ 情境二：溫室裡的舞者(Crossroads) / "
                 "X+Y− 情境三：孤島韌性突圍(Adaptation) / X−Y− 情境四：末日求生戰役(Inferno)")

token_log = {}   # {step: {model, input_tokens, output_tokens}}

# ---------------------------------------------------------------- utilities
def latest_week_dir() -> pathlib.Path:
    dirs = sorted((ROOT / "weekly").glob("W*"), key=lambda p: int(p.name[1:]))
    return dirs[-1]

def parse_json_block(text: str) -> dict:
    """容錯解析：剝除 ```json 圍欄後取第一個 JSON 物件"""
    text = re.sub(r"```(?:json)?|```", "", text).strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"模型未回傳 JSON:\n{text[:300]}")
    return json.loads(m.group(0))

def call_claude(client, model: str, step: str, system: str, user: str, max_tokens=4000) -> dict:
    resp = client.messages.create(
        model=model, max_tokens=max_tokens,
        system=system, messages=[{"role": "user", "content": user}],
    )
    token_log[step] = {"model": model,
                       "input_tokens": resp.usage.input_tokens,
                       "output_tokens": resp.usage.output_tokens}
    return parse_json_block(resp.content[0].text)

# ---------------------------------------------------------------- Step A
def extract_events(client, raw: dict) -> dict:
    system = ("你是半導體產業事件擷取器。從候選新聞中挑出對台灣半導體(測試/前段)產業有實質影響的事件，"
              "每則保留可追溯來源。只回傳 JSON，不得有其他文字。絕對禁止虛構事件或來源(P1)。")
    user = f"""候選清單(週次 {raw['week']}，範圍 {raw['range']})：
{json.dumps(raw['items'], ensure_ascii=False)}

輸出 JSON schema：
{{"week":"{raw['week']}","events":[{{"title":"...","summary":"80字內繁中摘要",
"category":"地緣政治|供應鏈|政策|需求|大廠動態|能源天災",
"xImpact":"↑|↓|→","yImpact":"↑|↓|→","source":"媒體名","date":"YYYY-MM-DD","url":"..."}}]}}
（{AXES_DEF}）
挑選 3–6 則最重要事件；查無充分資料的欄位留空，不得填補。"""
    return call_claude(client, SONNET, "A_事件擷取(Sonnet)", system, user, 4000)

# ---------------------------------------------------------------- Step B
def reason_scenario(client, events: dict, prev_week: dict | None) -> dict:
    prev = json.dumps(prev_week, ensure_ascii=False) if prev_week else "無（本週為基準比較起點）"
    system = ("你是 SCAI-Agent 首席情境分析師。依四象限情境框架與 25 項 KDF 動態權重進行本週判定。"
              f"{AXES_DEF}。{SCENARIOS_DEF}。權重 0–100，中性=50。"
              "所有判斷屬【推斷】，只回傳 JSON。KDF 順序嚴格依給定清單（提案書 1–25 編號正本），嚴禁增刪改序。"
              "每則事件必須留下 decisionTrace（Observability 憲法要求，省略即違規）；"
              "另須輸出 H+6 風險雷達（憲法 LAYER 10-2：未來六個月 3–5 項，以欣銓／測試廠視角）。")
    user = f"""本週事件：
{json.dumps(events, ensure_ascii=False)}

上週資料（對比基準）：
{prev}

KDF 固定順序清單（id 1–25）：
{json.dumps(KDF_LIST, ensure_ascii=False)}

輸出 JSON schema：
{{"week":"{events['week']}",
 "xy":{{"x":0.0,"y":0.0}},
 "scenario":"情境N：中文名稱","scenarioEn":"Spring|Crossroads|Adaptation|Inferno",
 "scenarioDesc":"60字內判定理由（結論先行）",
 "boundary_note":"若貼近象限邊界的說明，否則空字串",
 "weights":[25個整數，順序=KDF清單],
 "top_movers":[{{"kdf":"...","delta":"+N或-N","reason":"..."}}],
 "decisionTrace":[{{"event":"事件標題","keywords":["關鍵字"],"xDelta":0.0,"yDelta":0.0,
   "kdfChanges":[{{"id":1,"name":"KDF名稱","from":50,"to":55,"reason":"..."}}]}}],
 "riskRadar":[{{"risk":"風險描述（3–5 項）","signal":"觸發/領先訊號","kdf":7,"mitigation":"規避動作"}}],
 "reasoning":"120字內推理鏈摘要"}}"""
    return call_claude(client, OPUS, "B_情境推理(Opus)", system, user, 6000)

# ---------------------------------------------------------------- Step C
def cross_check_gemini(events: dict) -> dict:
    g = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prompt = f"""你是獨立的半導體情境判定審查員。僅依下列事件，獨立判定本週落在哪一象限。
{AXES_DEF}。
{SCENARIOS_DEF}。
事件：{json.dumps(events, ensure_ascii=False)}
只回傳 JSON：{{"xy":{{"x":0.0,"y":0.0}},"scenario":"情境N：中文名稱","rationale":"60字內理由"}}"""
    resp = g.models.generate_content(model=GEMINI, contents=prompt)
    um = resp.usage_metadata
    token_log["C_交叉驗證(Gemini)"] = {"model": GEMINI,
        "input_tokens": um.prompt_token_count, "output_tokens": um.candidates_token_count}
    return parse_json_block(resp.text)

# ---------------------------------------------------------------- Step D
def merge_verdict(opus: dict, gem: dict) -> dict:
    agree = opus["scenario"] == gem["scenario"]
    return {
        "agreement": agree,
        "confidence": "高" if agree else "低",
        "flag": "" if agree else "【建議查證】雙模型情境判定不一致，本週結論信心下修，建議人工複核",
        "opus_scenario": opus["scenario"],
        "gemini_scenario": gem["scenario"],
        "gemini_rationale": gem.get("rationale", ""),
    }

# ---------------------------------------------------------------- Step E-1
def append_dashboard(week_obj: dict):
    """data/weeks.json 為唯一真實來源(append-only)，再整批注入儀表板 HTML 的 WEEKS 陣列"""
    weeks_file = ROOT / "data" / "weeks.json"
    weeks = json.loads(weeks_file.read_text(encoding="utf-8")) if weeks_file.exists() else []
    if any(w["week"] == week_obj["week"] for w in weeks):
        print(f"[skip] {week_obj['week']} 已存在，不覆寫（append-only 鐵則）")
        return
    weeks.append(week_obj)
    weeks_file.write_text(json.dumps(weeks, ensure_ascii=False, indent=2), encoding="utf-8")

    html_file = ROOT / "dashboard" / "SCAI-Agent_週報儀表板.html"
    if html_file.exists():
        html = html_file.read_text(encoding="utf-8")
        new_arr = "const WEEKS = " + json.dumps(weeks, ensure_ascii=False) + ";"
        html2, n = re.subn(r"const WEEKS\s*=\s*\[.*?\];", new_arr, html, count=1, flags=re.S)
        if n:
            html_file.write_text(html2, encoding="utf-8")
            print("[ok] 儀表板 WEEKS 已更新")
        else:
            print("[warn] 儀表板中找不到 WEEKS 陣列，僅更新 weeks.json")

# ---------------------------------------------------------------- Step E-2
def write_report(wd: pathlib.Path, events, opus, verdict, rng, week_obj=None):
    week = opus["week"]
    dims = {   # 五大維度對 KDF 索引（0-based；憲法 v2.0：5/7/4/6/3）
        "技術與研發能力": [3, 4, 5, 6, 13],
        "企業競爭與策略能力": [2, 7, 9, 10, 11, 12, 14],
        "全球市場與供應鏈": [16, 21, 22, 23],
        "政策與營運資源環境": [15, 17, 18, 19, 20, 24],
        "制度與產業規範": [0, 1, 8],
    }
    dim_scores = {k: round(sum(opus["weights"][i] for i in v) / len(v), 1) for k, v in dims.items()}
    ev_rows = "\n".join(
        f"| {e['title'][:40]} | {e['category']} | {e['xImpact']}/{e['yImpact']} | [{e['source']} {e['date']}]({e['url']}) |"
        for e in events["events"])
    movers = "\n".join(f"- {m['kdf']}：{m['delta']}（{m['reason']}）" for m in opus.get("top_movers", []))
    flag_line = f"\n> ⚠️ {verdict['flag']}\n" if verdict["flag"] else ""
    risks_md = "\n".join(
        f"| {r.get('risk','')} | {r.get('signal','')} | #{r.get('kdf','—')} | {r.get('mitigation','')} |"
        for r in opus.get("riskRadar", [])) or "| 本週無風險雷達資料 | | | |"
    plan = (week_obj or {}).get("companyPlan")
    if plan:
        fired_md = "\n".join(f"- **[{f['id']}] {f['title']}**：{f['action']}（停損：{f['stop_loss']}）"
                             for f in plan["firedPlaybooks"]) or "本週各劇本觸發門檻均未達成。"
        plan_md = f"情境姿態：{plan['scenarioStance']}\n\n{fired_md}"
    else:
        plan_md = "（無公司規畫資料）"
    report = f"""# SCAI-Agent 週報 {week}（{rng}）

## 一、執行摘要
本週情境判定為 **{opus['scenario']}**（X={opus['xy']['x']}, Y={opus['xy']['y']}）【推斷】。
{opus['scenarioDesc']}
雙模型交叉驗證：Opus={verdict['opus_scenario']} / Gemini={verdict['gemini_scenario']}，
一致性={'✅ 一致' if verdict['agreement'] else '❌ 不一致'}，信心等級=**{verdict['confidence']}**。{flag_line}
## 二、本週重大事件與雙軸衝擊
| 事件 | 類別 | X/Y 衝擊 | 來源 |
|---|---|---|---|
{ev_rows}

## 三、情境判定推理【推斷】
{opus['reasoning']}
{('邊界說明：' + opus['boundary_note']) if opus.get('boundary_note') else ''}

## 四、KDF 權重 Top Movers【推斷】
{movers}

## 五、五大維度分數【推斷】
{chr(10).join(f'- {k}：{v}' for k, v in dim_scores.items())}

## 六、不確定項目
{verdict['flag'] or '本週雙模型判定一致，無額外查證項目。'}

## 七、H+6 風險雷達（欣銓／測試廠視角）【推斷】
| 風險 | 領先訊號 | KDF | 規避動作 |
|---|---|---|---|
{risks_md}

## 八、對欣銓的公司規畫（觸發式劇本）【推斷】
{plan_md}

---
*聲明：X/Y 座標、25 項 KDF 權重、風險雷達與公司規畫皆為分析性判斷【推斷】，非企業官方數據亦非投資建議，建議與半導體專家研判交叉驗證。*
"""
    out_dir = ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"SCAI-Agent_週報_{week}.md"
    out.write_text(report, encoding="utf-8")
    print(f"[ok] 週報 → {out}")

# ---------------------------------------------------------------- main
if __name__ == "__main__":
    wd = latest_week_dir()
    raw = json.loads((wd / "raw_items.json").read_text(encoding="utf-8"))
    ac = anthropic.Anthropic()   # 讀 ANTHROPIC_API_KEY 環境變數

    events = extract_events(ac, raw)
    (wd / "events.json").write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")

    weeks_file = ROOT / "data" / "weeks.json"
    prev = json.loads(weeks_file.read_text(encoding="utf-8"))[-1] if weeks_file.exists() else None

    opus = reason_scenario(ac, events, prev)
    (wd / "scenario.json").write_text(json.dumps(opus, ensure_ascii=False, indent=2), encoding="utf-8")

    gem = cross_check_gemini(events)
    verdict = merge_verdict(opus, gem)
    (wd / "cross_check.json").write_text(
        json.dumps({"gemini": gem, "verdict": verdict}, ensure_ascii=False, indent=2), encoding="utf-8")

    week_obj = {
        "week": opus["week"], "range": raw["range"],
        "gen": datetime.date.today().isoformat(),
        "scenario": opus["scenario"], "scenarioEn": opus.get("scenarioEn", ""),
        "scenarioDesc": opus["scenarioDesc"],
        "xy": opus["xy"], "w": opus["weights"],
        "confidence": verdict["confidence"],
        "crossCheck": {"agreement": verdict["agreement"],
                       "opus": verdict["opus_scenario"],
                       "gemini": verdict["gemini_scenario"],
                       "flag": verdict["flag"]},
        "topMovers": opus.get("top_movers", []),
        "reasoning": opus.get("reasoning", ""),
        "events": events["events"],                      # 完整事件（title/source/date/url/summary/xImpact/yImpact）
        "decisionTrace": opus.get("decisionTrace", []),  # Observability（憲法 LAYER 9，不可省略）
        "riskRadar": opus.get("riskRadar", []),          # H+6 風險雷達（憲法 LAYER 10-2）
    }

    # 公司規畫層（提案書 Step 5）：比對 X/Y、KDF、關鍵字 → 觸發式劇本 companyPlan
    prof = json.loads((ROOT / "data" / "company_profile.json").read_text(encoding="utf-8"))
    playbook = json.loads((ROOT / "data" / "playbook.json").read_text(encoding="utf-8"))
    week_obj["companyPlan"] = plan_engine.build_plan(week_obj, prof, playbook)
    print(f"[ok] 公司規畫：觸發 {len(week_obj['companyPlan']['firedPlaybooks'])} 條劇本")

    append_dashboard(week_obj)

    write_report(wd, events, opus, verdict, raw["range"], week_obj)

    (wd / "token_usage.json").write_text(
        json.dumps(token_log, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(v["input_tokens"] + v["output_tokens"] for v in token_log.values())
    print(f"[ok] 本週 token 總消耗 {total}，明細 → {wd/'token_usage.json'}")
