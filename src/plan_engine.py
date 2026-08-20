#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SCAI-Agent｜規畫引擎（Plan Engine）— 雲端管線版
將產業級情境判定 × 企業畫像 → 欣銓專屬公司規畫（提案書 Step 5 強化層）。
移植自 cowork/scripts/plan_engine.py（含 v1.1 門檻修正）；觸發邏輯不變，
資料來源改為 data/weeks.json 陣列。pipeline.py 每週 import build_plan() 直接寫入 companyPlan。

用法（手動檢查）：
  python src/plan_engine.py --week 6           # 判定並印出
  python src/plan_engine.py --week 6 --write   # 寫回 data/weeks.json 該週 companyPlan
"""
import json, argparse, pathlib, re

ROOT = pathlib.Path(__file__).resolve().parent.parent

def load(p):
    return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))

def week_num(wk):
    """week 欄位相容數字（cowork 原格式）與 'W{n}' 字串（管線格式）。"""
    return int(str(wk.get("week")).lstrip("Ww"))

# 否定敘述不得觸發劇本（2026-08-18 由 cowork 側發現，2026-08-20 修）。
# W10 的 PB-07「天災與能源風險」唯一成立的條件是命中「缺水、停電、颱風、天災」，
# 而那四個詞全部來自一句報平安的話：「本週台灣新竹、龍潭、桃園園區【無】天災、
# 停電或缺水通報」。關鍵字比對讀不出否定，把「沒有發生」讀成「發生了」。
#
# 作法：以子句為單位，含否定詞的整個子句不參與關鍵字比對。刻意不做詞性分析——
# 只解這一件事，並以十週實資料回歸驗證：觸發集合僅 W10 變動（PB-07 消失），
# W8（熊本 M7.1 真地震）與 W9（颱風海豚真的來了）的 PB-07 都保留。
# W9 尤其能說明分寸：同一則事件裡「颱風海豚…竹苗山區雨量 350–500mm」留下、
# 「無半導體災損通報」剔除。
NEG = ("無", "未", "沒有")
# 「無」「未」開頭的既有名詞，不是否定詞。新增前先跑 --neg-report 確認影響。
NEG_OK = ("無晶圓廠", "無塵室", "無人", "未來")
_CLAUSE = re.compile(r"[。！？；\n，,]")


def strip_negated(text):
    """剔除含否定詞的子句。"""
    keep = []
    for cl in _CLAUSE.split(text):
        probe = cl
        for w in NEG_OK:
            probe = probe.replace(w, "")
        if any(n in probe for n in NEG):
            continue
        keep.append(cl)
    return " ".join(keep)


def week_text(wk):
    """彙整該週所有可供關鍵字比對的文字（已剔除否定子句）。"""
    parts = [wk.get("scenarioDesc", "")]
    for e in wk.get("events", []):
        parts += [e.get("title", ""), e.get("summary", "")]
    for t in wk.get("decisionTrace", []):
        parts.append(t.get("event", ""))
        parts += t.get("keywords", [])
    for r in wk.get("riskRadar", []):
        parts += [r.get("risk", ""), r.get("signal", "")]
    return strip_negated(" ".join(parts))

CMP = {
    "<=": lambda a, b: a <= b, ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b, ">": lambda a, b: a > b, "==": lambda a, b: a == b,
}

def check(cond, wk, text):
    """回傳 (是否通過, 說明)。說明前綴 ✓/✗ 標示該條件是否成立，避免 OR 型劇本把未通過條件誤讀為成立。"""
    t = cond["type"]
    if t == "axis":
        val = wk["xy"][cond["axis"]]
        ok = CMP[cond["op"]](val, cond["value"])
        return ok, f'{"✓" if ok else "✗"} {cond["axis"].upper()}={val:+.2f} {cond["op"]} {cond["value"]}'
    if t == "kdf":
        val = wk["w"][cond["id"] - 1]
        ok = CMP[cond["op"]](val, cond["value"])
        return ok, f'{"✓" if ok else "✗"} KDF#{cond["id"]}={val:g} {cond["op"]} {cond["value"]}'
    if t == "keyword":
        hit = [k for k in cond["any"] if k in text]
        return bool(hit), ("✓ 命中關鍵字：" + "、".join(hit) if hit else "✗ 無命中關鍵字")
    return False, "✗ 未知條件"

def evaluate(wk, playbook):
    text = week_text(wk)
    fired, dormant = [], []
    for pb in playbook["playbooks"]:
        trig = pb["trigger"]
        results = [check(c, wk, text) for c in trig["conditions"]]
        oks = [r[0] for r in results]
        why = "；".join(r[1] for r in results)
        ok = all(oks) if trig.get("logic", "AND") == "AND" else any(oks)
        rec = {
            "id": pb["id"], "title": pb["title"], "horizon": pb["horizon"],
            "lever": pb["lever"], "action": pb["action"], "kdf": pb["kdf"],
            "success_metric": pb["success_metric"], "stop_loss": pb["stop_loss"],
            "cost_note": pb.get("cost_note", ""), "evidence": why,
        }
        (fired if ok else dormant).append(rec)
    return fired, dormant

def build_plan(wk, profile, playbook):
    """pipeline.py 每週呼叫：回傳可直接寫入週物件的 companyPlan。"""
    fired, dormant = evaluate(wk, playbook)
    stance = profile["scenario_stance"].get(wk.get("scenarioEn"), "【資料不足】")
    return {
        "scenarioStance": stance,
        "firedPlaybooks": fired,
        "dormantPlaybooks": [{"id": d["id"], "title": d["title"], "evidence": d["evidence"]} for d in dormant],
        "note": "本規畫為【推斷】，非投資建議；企業畫像中標記【待公司確認】之欄位須經欣銓確認後方可作為決策依據。",
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--write", action="store_true", help="寫回 data/weeks.json 該週的 companyPlan")
    a = ap.parse_args()

    weeks_file = ROOT / "data" / "weeks.json"
    weeks = load(weeks_file)
    hits = [w for w in weeks if week_num(w) == a.week]
    if not hits:
        raise SystemExit(f"[err] data/weeks.json 找不到 W{a.week}")
    wk = hits[0]

    prof = load(ROOT / "data" / "company_profile.json")
    pb = load(ROOT / "data" / "playbook.json")
    plan = build_plan(wk, prof, pb)
    fired = plan["firedPlaybooks"]

    print(f'== W{week_num(wk)}（{wk["range"]}）{wk["scenario"]}　X={wk["xy"]["x"]:+.2f} Y={wk["xy"]["y"]:+.2f} ==')
    print(f'情境姿態【推斷】：{plan["scenarioStance"]}')
    print(f'觸發劇本 {len(fired)} 條：' + "、".join(f["id"] for f in fired))
    for it in fired:
        print(f'  · [{it["id"]}] {it["title"]}\n    觸發依據：{it["evidence"]}')

    if a.write:
        wk["companyPlan"] = plan
        weeks_file.write_text(json.dumps(weeks, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[已寫回] {weeks_file} → W{a.week}.companyPlan")

if __name__ == "__main__":
    main()
