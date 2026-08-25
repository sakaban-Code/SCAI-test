#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SCAI-Agent｜開發階段 Token 用量統計

競賽評分第 3 項（20%）要求說明「開發 AI 員工／以及 AI 員工運作時」的 token 消耗。
本腳本負責**開發階段**那一半：直接讀三個工具的本機原始紀錄，全部取 usage 欄位，
不做任何估算。運作階段（weekly/W{n}/token_usage.json）為 **0**——本專案自始至終
未取得 API 預算，雲端週報管線從未執行。那是既定條件，不是待補的另一半。

────────────────────────────────────────────────────────────────────────
三個來源，三種**不同**的重複計算陷阱——這是本腳本存在的主要理由
────────────────────────────────────────────────────────────────────────
Claude Code  ~/.claude/projects/**/*.jsonl
             一次 API 回應會依內容型別拆成多行寫入（thinking 一行、text 一行），
             每行都帶**完整且相同**的 usage 與 message.id。實測本專案逐字稿
             3241 行 → 1621 則，正好 2 倍。→ 依 message.id 去重。

Cowork       %APPDATA%/Claude/local-agent-mode-sessions/**/audit.jsonl
             （macOS: ~/Library/Application Support/Claude/...）
             同格式、同去重陷阱。每行另帶 _audit_hmac 簽章與 _audit_timestamp；
             本腳本**只讀取不驗簽**（驗簽需動用 .audit-key，不在本腳本職責內）。

             ⚠ 實測發現：Cowork 的 output_tokens **不可用**。單一 session 去重後
             339 則，output 最大值僅 73、平均 23，且同 id 的重複紀錄其 output
             首末完全相同（不是串流中途快照被我們取錯）。稽核紀錄顯然在回應
             產出前就寫入，只有輸入側是完整的。→ 本腳本將 Cowork 的 output
             計為「不可得」而非 0，並在報表與 JSON 中明示筆數，不端出假數字。

Codex        ~/.codex/sessions/**/*.jsonl
             token_count 事件的 total_token_usage 是**累計值**不是增量，
             整份加總會得到天文數字。→ 取每檔最後一筆。
             實測 99 個 session、973 個事件，累計值**全程單調遞增、0 次重置**，
             故末筆即為該 session 真實總量。last_token_usage 的總和會比末筆高
             約一成（同一回合內多次呼叫重複計入），僅作為交叉檢查、不採用。
             另：Codex 的 cached_input_tokens 是 input_tokens 的**子集**
             （實測 33134 + 204 = 33338 = total），不可另外相加；
             Anthropic 的 input/cache_creation/cache_read 則是**互斥**的三份。

────────────────────────────────────────────────────────────────────────
歸屬口徑：腳本只負責算，**不替人決定哪些算 SCAI**
────────────────────────────────────────────────────────────────────────
逐字稿有純有混。本腳本掃出每個檔案的 SCAI 提及數與密度後，由人在
data/token_scope.json 裡逐檔標記 core／related／excluded，該檔進版控——
歸屬決定本身因此可被稽核。三種口徑一律同時輸出：
    core            純 SCAI 檔案，確定下界
    core + related  再加上混合檔案中判定與 SCAI 相關者
    all             全部掃到的紀錄，確定上界

隱私：docs/ 與 data/ 會進 public repo，故輸出 JSON **只含 session ID 與統計數字**，
不含檔案路徑（含使用者名稱）、不含任何對話內容。首則訊息預覽僅出現在本機主控台。

用法：
    python src/token_stats.py                    # 主控台報表
    python src/token_stats.py --init-scope       # 產生 data/token_scope.json 草稿（待人工確認）
    python src/token_stats.py --json             # 寫出 data/token_usage_dev.json
    python src/token_stats.py --json --prices data/token_prices.json   # 另附成本換算
"""
import argparse
import json
import os
import pathlib
import re
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOME = pathlib.Path.home()

SCOPE_PATH = ROOT / "data" / "token_scope.json"
OUT_PATH = ROOT / "data" / "token_usage_dev.json"

# 自動建議 scope 用的密度門檻（每 MB 的 SCAI 提及次數）。這是**建議值不是判定**，
# 產出的 scope 草稿一律標記待人工確認；真正的歸屬以 token_scope.json 為準。
DENSITY_CORE = 20.0
DENSITY_RELATED = 1.0

# 快取倍率——把四種輸入 token 折算成「輸入計價當量」用。
#
# 為什麼需要這個：長對話每一次呼叫都會重讀整段快取前綴，所以 cache_read 會累積到
# 佔總處理量九成以上。若直接把四項相加當成「總 token 用量」，數字會膨脹一個數量級
# 且完全被最便宜的那一項主導——技術上為真，實務上誤導。折算後才反映真實成本結構。
#
# 以下是**倍率不是金額**，取自各家公開的快取計價說明。做正式報告前請對照當時的
# 官方定價頁覆核，尤其 OpenAI 側的快取折扣隨模型世代調整過。
RATE = {
    "input": 1.00,
    "cacheWrite5m": 1.25,   # Anthropic：5 分鐘 TTL 寫入
    "cacheWrite1h": 2.00,   # Anthropic：1 小時 TTL 寫入
    "cacheRead": 0.10,      # Anthropic：快取讀取
    "codexCacheRead": 0.25,  # OpenAI 側快取折扣（與 Anthropic 不同，待覆核）
}


# ── 來源定位 ────────────────────────────────────────────────────────────
def claude_code_files():
    d = HOME / ".claude" / "projects"
    return sorted(d.rglob("*.jsonl")) if d.is_dir() else []


def cowork_files():
    """Cowork（local agent mode）的稽核紀錄。跨平台各找一次，找到就收。"""
    cands = []
    if os.environ.get("APPDATA"):
        cands.append(pathlib.Path(os.environ["APPDATA"]) / "Claude")
    cands.append(HOME / "Library" / "Application Support" / "Claude")
    cands.append(HOME / ".config" / "Claude")
    out = []
    for c in cands:
        d = c / "local-agent-mode-sessions"
        if d.is_dir():
            out += sorted(d.rglob("audit.jsonl"))
    return out


def codex_files():
    d = HOME / ".codex" / "sessions"
    return sorted(d.rglob("*.jsonl")) if d.is_dir() else []


def session_id(tool: str, path: pathlib.Path) -> str:
    """穩定且不含使用者名稱的 session 識別碼（會寫進 public repo）。"""
    if tool == "cowork":
        return path.parent.name.replace("local_", "")
    return path.stem


# ── 單檔掃描 ────────────────────────────────────────────────────────────
_FIELDS = ("input", "cacheCreate", "cw5m", "cw1h", "cacheRead", "codexCacheRead",
           "output", "outputUnknown")


def _blank():
    d = {"msgs": 0}
    d.update({k: 0 for k in _FIELDS})
    return d


def _add(dst, r):
    dst["msgs"] += r.get("turns", 1)
    for k in _FIELDS:
        dst[k] += r.get(k, 0)


def _first_user_text(obj):
    msg = obj.get("message") or {}
    if msg.get("role") != "user":
        return ""
    c = msg.get("content")
    if isinstance(c, str):
        return c.strip()
    if isinstance(c, list):
        for b in c:
            if isinstance(b, dict) and b.get("type") == "text":
                return (b.get("text") or "").strip()
    return ""


def scan_anthropic(path: pathlib.Path, tool: str):
    """Claude Code 與 Cowork 共用（同一份 JSONL schema）。回傳 (meta, records)。"""
    records, mentions, preview = [], 0, ""
    # Cowork 稽核紀錄在回應完成前寫入，output_tokens 不完整（見檔頭說明）
    out_ok = tool != "cowork"
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            mentions += line.lower().count("scai")

            if not preview and '"role":"user"' in line:
                try:
                    preview = _first_user_text(json.loads(line))[:56]
                except Exception:
                    pass

            if '"usage"' not in line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            msg = obj.get("message") or {}
            u = msg.get("usage")
            mid = msg.get("id")
            # 沒有 message.id 就無法去重，寧可捨棄也不冒重複計算的風險
            if not isinstance(u, dict) or not mid:
                continue
            # 快取寫入的 5m／1h 拆分影響計價當量（1.25× vs 2×）。舊格式若無此欄位，
            # 全額歸入 5m（較低倍率）——寧可低估自己的用量，不可高估。
            cc = u.get("cache_creation") if isinstance(u.get("cache_creation"), dict) else {}
            cw1h = int(cc.get("ephemeral_1h_input_tokens") or 0)
            cw5m = int(cc.get("ephemeral_5m_input_tokens") or 0)
            cw_total = int(u.get("cache_creation_input_tokens") or 0)
            if cw1h + cw5m != cw_total:
                # 以總數為準補回差額。實測有紀錄回報 total=0 卻給 1h=1542（3 筆，
                # 去重後 1 筆），此時補回值為負——**必須連 1h 一起夾**，只夾 5m 會讓
                # 成分和大於回報總量，且多出來的那截還是用最貴的 2× 計價，與下面
                # 「寧可低估不可高估」的原則相反。夾完恆有 cw5m + cw1h == cacheCreate。
                cw1h = min(cw1h, cw_total)
                cw5m = cw_total - cw1h
            records.append({
                "id": mid,
                "model": msg.get("model") or "?",
                "ts": (obj.get("timestamp") or obj.get("_audit_timestamp") or "")[:10],
                "input": int(u.get("input_tokens") or 0),
                "cacheCreate": cw_total,
                "cw5m": cw5m,
                "cw1h": cw1h,
                "cacheRead": int(u.get("cache_read_input_tokens") or 0),
                # 不可信的 output 計為「不可得」而非 0——0 會被當成真的沒產出
                "output": int(u.get("output_tokens") or 0) if out_ok else 0,
                "outputUnknown": 0 if out_ok else 1,
            })
    return {"mentions": mentions, "preview": preview, "rawLines": len(records)}, records


_MODEL_RE = re.compile(r'"model"\s*:\s*"([^"]+)"')


def scan_codex(path: pathlib.Path):
    """Codex：total_token_usage 是累計值，取最後一筆；另以 last_token_usage 交叉驗證。"""
    last_total, model, mentions, preview = None, "", 0, ""
    d_in = d_out = turns = 0
    days = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            mentions += line.lower().count("scai")
            if not model:
                m = _MODEL_RE.search(line)
                if m:
                    model = m.group(1)
            if '"token_count"' not in line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            info = ((obj.get("payload") or {}).get("info")) or {}
            tot, lst = info.get("total_token_usage"), info.get("last_token_usage")
            if isinstance(tot, dict):
                last_total = tot
                turns += 1
                ts = obj.get("timestamp") or ""
                if ts:
                    days.append(ts[:10])
            if isinstance(lst, dict):
                d_in += int(lst.get("input_tokens") or 0)
                d_out += int(lst.get("output_tokens") or 0)

    if not last_total:
        return {"mentions": mentions, "preview": preview, "rawLines": 0}, [], None

    # Codex 的 cached_input_tokens 是 input_tokens 的**子集**（實測 33134+204=33338=total），
    # 與 Anthropic 三項互斥的結構不同。此處拆成互斥兩份，後續彙總才能一視同仁。
    tot_in = int(last_total.get("input_tokens") or 0)
    cached = int(last_total.get("cached_input_tokens") or 0)
    rec = {
        "id": path.stem,                       # 每檔一筆，天然不重複
        "model": model or "?",
        "ts": (days[-1] if days else ""),
        "turns": turns,
        "input": max(tot_in - cached, 0),      # 未命中快取的部分
        "cacheCreate": 0, "cw5m": 0, "cw1h": 0,   # Codex 紀錄無快取寫入概念
        "cacheRead": 0,
        "codexCacheRead": cached,
        "output": int(last_total.get("output_tokens") or 0),
        "outputUnknown": 0,
    }
    # 交叉驗證：累計末筆 vs 增量總和。差 >2% 表示 session 中途重置或格式有變。
    drift = None
    a, b = tot_in + rec["output"], d_in + d_out
    if a and b and abs(a - b) / max(a, b) > 0.02:
        drift = {"last": a, "deltaSum": b}
    return {"mentions": mentions, "preview": preview, "rawLines": 1}, [rec], drift


# ── 全域掃描 ────────────────────────────────────────────────────────────
def scan_all():
    files, seen, cross_dup, drifts = [], set(), 0, []

    for tool, paths in (("claude-code", claude_code_files()),
                        ("cowork", cowork_files()),
                        ("codex", codex_files())):
        for p in paths:
            try:
                if tool == "codex":
                    meta, recs, drift = scan_codex(p)
                    if drift:
                        drifts.append((session_id(tool, p), drift))
                else:
                    meta, recs = scan_anthropic(p, tool)
            except OSError:
                continue

            kept = []
            for r in recs:
                # 全域去重：同一 message.id 可能跨檔重現（續跑／壓縮），一律只認第一次
                if r["id"] in seen:
                    cross_dup += 1
                    continue
                seen.add(r["id"])
                kept.append(r)

            if not kept and meta["mentions"] == 0:
                continue

            agg = _blank()
            for r in kept:
                _add(agg, r)
            mb = max(p.stat().st_size / 1024 / 1024, 0.001)
            dates = sorted({r["ts"] for r in kept if r["ts"]})
            files.append({
                "tool": tool,
                "session": session_id(tool, p),
                "path": str(p),                     # 僅供本機報表，不寫入 JSON
                "mb": round(mb, 2),
                "mentions": meta["mentions"],
                "density": round(meta["mentions"] / mb, 1),
                "preview": meta["preview"],         # 同上，僅本機
                "rawRecords": meta["rawLines"],
                "dupDropped": meta["rawLines"] - len(kept),
                "totals": agg,
                "from": dates[0] if dates else "",
                "to": dates[-1] if dates else "",
                "records": kept,                    # 供分模型／分日彙總
            })

    files.sort(key=lambda f: -enrich(f["totals"])["billableInput"])
    return files, cross_dup, drifts


# ── 歸屬 ────────────────────────────────────────────────────────────────
def suggest_scope(f):
    if f["mentions"] == 0:
        return "excluded"
    if f["density"] >= DENSITY_CORE:
        return "core"
    if f["density"] >= DENSITY_RELATED:
        return "related"
    return "excluded"


def load_scope():
    if not SCOPE_PATH.exists():
        return None
    try:
        return json.loads(SCOPE_PATH.read_text(encoding="utf-8")).get("files", {})
    except Exception as e:
        sys.exit(f"[錯誤] token_scope.json 解析失敗：{e}")


def write_scope(files):
    body = {
        "_說明": "逐檔歸屬決定。本檔進版控，使得『哪些 token 算 SCAI』這個判斷本身可被稽核。",
        "_口徑": {
            "core": "純 SCAI 工作階段，計入核心口徑（確定下界）",
            "related": "混合階段但含 SCAI 相關工作，計入 core+related 口徑",
            "excluded": "與 SCAI 無關，不計入（但仍計入 all 上界）",
        },
        "_產生方式": (f"由 src/token_stats.py --init-scope 依提及密度建議"
                      f"（≥{DENSITY_CORE}/MB→core、≥{DENSITY_RELATED}/MB→related），"
                      "**建議值需人工覆核後才具效力**"),
        "files": {
            f"{f['tool']}:{f['session']}": {
                "scope": suggest_scope(f),
                "mentions": f["mentions"],
                "density": f["density"],
                "from": f["from"], "to": f["to"],
                "confirmed": False,
            } for f in files
        },
    }
    SCOPE_PATH.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return body


# ── 彙總 ────────────────────────────────────────────────────────────────
def totals_of(files):
    agg = _blank()
    by_model, by_day, by_tool = defaultdict(_blank), defaultdict(_blank), defaultdict(_blank)
    for f in files:
        for r in f["records"]:
            _add(agg, r)
            _add(by_model[r["model"]], r)
            _add(by_tool[f["tool"]], r)
            if r["ts"]:
                _add(by_day[r["ts"]], r)
    return agg, dict(by_model), dict(by_day), dict(by_tool)


def enrich(agg):
    """補上衍生指標。

    刻意**不提供**一個叫「總 token」的單一數字：四項直接相加會被 cache_read 主導
    （實測占九成以上），技術上為真卻誤導。改為並列三個各有明確意義的量：
      processed     實際處理的 token 總量（含重讀快取），衡量工作規模
      billableInput 依快取倍率折算的輸入計價當量，反映真實成本結構
      output        產出量，另計
    快取命中率則是「如何優化」那題的主要證據。
    """
    read_in = agg["input"] + agg["cacheCreate"] + agg["cacheRead"] + agg["codexCacheRead"]
    out = dict(agg)
    out["processed"] = read_in + agg["output"]
    out["billableInput"] = round(
        agg["input"] * RATE["input"]
        + agg["cw5m"] * RATE["cacheWrite5m"]
        + agg["cw1h"] * RATE["cacheWrite1h"]
        + agg["cacheRead"] * RATE["cacheRead"]
        + agg["codexCacheRead"] * RATE["codexCacheRead"]
    )
    cached = agg["cacheRead"] + agg["codexCacheRead"]
    out["cacheHitRate"] = round(cached / read_in, 4) if read_in else None
    return out


def fmt(n):
    return f"{n:,}"


# ── 主流程 ──────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="SCAI-Agent 開發階段 token 統計")
    ap.add_argument("--init-scope", action="store_true", help="產生 data/token_scope.json 草稿")
    ap.add_argument("--json", action="store_true", help="寫出 data/token_usage_dev.json")
    ap.add_argument("--prices", help="價目表 JSON，附成本換算（未給則只報 token 數）")
    # 腳本本身不取系統時間（同輸入必得同輸出，才能重跑比對）；日期由呼叫端傳入。
    ap.add_argument("--date", default="", help="產出日期 YYYY-MM-DD，寫入 generated 欄位")
    a = ap.parse_args()

    print("[掃描] Claude Code / Cowork / Codex 本機紀錄…", flush=True)
    files, cross_dup, drifts = scan_all()
    if not files:
        sys.exit("[錯誤] 三個來源都沒掃到紀錄——請確認本機確實用過這些工具")

    if a.init_scope:
        write_scope(files)
        print(f"[產生] {SCOPE_PATH}（{len(files)} 檔，建議值待人工覆核）")
        print("       請逐項確認 scope 並把 confirmed 改為 true，再重跑本腳本。")
        return

    scope = load_scope()
    if scope is None:
        print("[提示] 尚無 data/token_scope.json —— 先跑 --init-scope 決定歸屬。")
        print("       以下暫以密度建議值分類，僅供參考。\n")
        scope = {f"{f['tool']}:{f['session']}": {"scope": suggest_scope(f)} for f in files}

    for f in files:
        rec = scope.get(f"{f['tool']}:{f['session']}")
        f["scope"] = (rec or {}).get("scope", "excluded")
        # 歸屬檔裡沒有的 session（上次覆核之後才出現的）會落到預設值 excluded，
        # 那和「人工判定與本專案無關」長得一模一樣。標出來，否則新工作會無聲地
        # 被排除在 core 之外，而且沒有任何跡象提醒該去覆核。
        f["reviewed"] = rec is not None

    unreviewed = [f for f in files if not f["reviewed"]]
    if unreviewed:
        print(f"\n[待覆核] {len(unreviewed)} 個 session 不在 {SCOPE_PATH.name} 裡，"
              f"暫以 excluded 計（不進 core）。重跑 --init-scope 會重建整份草稿，"
              f"覆核過的決定要自行併回。")

    core = [f for f in files if f["scope"] == "core"]
    related = [f for f in files if f["scope"] in ("core", "related")]

    # ── 主控台報表（含路徑與預覽，僅本機）──
    print(f"\n{'='*112}")
    print(f"逐檔明細（去重後；跨檔重複另丟棄 {cross_dup} 筆）")
    print(f"{'='*112}")
    print(f"{'工具':<12}{'session':<22}{'口徑':<10}{'SCAI':>6}{'/MB':>7}"
          f"{'則':>7}{'計價當量in':>15}{'out':>11}  期間")
    print("-" * 112)
    for f in files:
        t = enrich(f["totals"])
        print(f"{f['tool']:<12}{f['session'][:20]:<22}{f['scope']:<10}"
              f"{f['mentions']:>6}{f['density']:>7.1f}"
              f"{t['msgs']:>7}{fmt(t['billableInput']):>15}{fmt(t['output']):>11}"
              f"  {f['from']}~{f['to']}")
        if f["preview"]:
            print(f"{'':>12}└ {f['preview'][:70]}")

    if drifts:
        hi = sum(1 for _, d in drifts if d["deltaSum"] > d["last"])
        print(f"\n[交叉檢查] {len(drifts)} 個 Codex session 的增量總和與累計末筆差異 >2%"
              f"（其中 {hi} 個為增量偏高）。")
        print("           已實測 99 個 session、973 個事件，累計值 0 次下降 → 末筆即真實總量；")
        print("           增量偏高係同一回合多次呼叫重複計入，故不採用增量總和。")

    unk = sum(f["totals"]["outputUnknown"] for f in files)
    if unk:
        print(f"\n[缺漏揭露] {unk} 則（Cowork）的 output_tokens 稽核紀錄不完整，"
              f"已計為不可得而非 0；下列 output 欄位不含這些則。")

    print(f"\n{'='*112}")
    print("三種口徑（原始四項）")
    print(f"{'='*112}")
    print(f"{'口徑':<16}{'檔':>5}{'則':>7}{'新輸入':>14}{'快取寫':>14}"
          f"{'快取讀':>16}{'output':>12}{'處理總量':>16}")
    print("-" * 112)
    scopes = {}
    order = (("core（下界）", core), ("core+related", related), ("all（上界）", files))
    for label, sel in order:
        agg, *_ = totals_of(sel)
        e = enrich(agg)
        print(f"{label:<16}{len(sel):>5}{e['msgs']:>7}{fmt(e['input']):>14}"
              f"{fmt(e['cacheCreate']):>14}{fmt(e['cacheRead'] + e['codexCacheRead']):>16}"
              f"{fmt(e['output']):>12}{fmt(e['processed']):>16}")
        scopes[label.split("（")[0]] = e

    print(f"\n{'='*112}")
    print("三種口徑（依快取倍率折算——這是應該拿去報告的數字）")
    print(f"{'='*112}")
    print(f"{'口徑':<16}{'輸入計價當量':>18}{'output':>14}{'output不可得':>14}"
          f"{'快取命中率':>13}{'  未折算處理總量（勿當用量）'}")
    print("-" * 112)
    for label, sel in order:
        e = scopes[label.split("（")[0]]
        hr = f"{e['cacheHitRate']*100:.1f}%" if e["cacheHitRate"] is not None else "—"
        print(f"{label:<16}{fmt(e['billableInput']):>18}{fmt(e['output']):>14}"
              f"{fmt(e['outputUnknown']) + ' 則':>14}{hr:>13}{fmt(e['processed']):>20}")

    agg_c, by_model, by_day, by_tool = totals_of(related)
    print(f"\n{'—'*68}\ncore+related 依工具／依模型（輸入計價當量）\n{'—'*68}")
    for name, d in (("工具", by_tool), ("模型", by_model)):
        for k, v in sorted(d.items(), key=lambda kv: -enrich(kv[1])["billableInput"]):
            e = enrich(v)
            print(f"  [{name}] {k:<26}{e['msgs']:>7} 則"
                  f"{fmt(e['billableInput']):>14} in{fmt(e['output']):>11} out")

    if not a.json:
        print("\n（加 --json 可寫出 data/token_usage_dev.json 供網站與本機應用使用）")
        return

    # ── 輸出 JSON：只含 session ID 與數字，不含路徑與對話內容 ──
    prices = None
    if a.prices:
        prices = json.loads(pathlib.Path(a.prices).read_text(encoding="utf-8"))

    out = {
        "generated": a.date,      # 由呼叫端填入，腳本本身不取系統時間以維持可重現
        "generator": "src/token_stats.py",
        "stage": "development",
        "note": ("開發階段 token，取自三個工具的本機原始 usage 欄位，非估算。"
                 "運作階段用量為 0：未取得 API 預算，雲端管線從未執行。"),
        "sources": {
            "claude-code": "~/.claude/projects/**/*.jsonl",
            "cowork": "Claude 桌面版 local-agent-mode-sessions/**/audit.jsonl（每行帶 HMAC 稽核簽章）",
            "codex": "~/.codex/sessions/**/*.jsonl",
        },
        "countingRules": [
            "Claude Code／Cowork：一次回應會拆多行寫入且各帶完整 usage，依 message.id 去重",
            "Codex：total_token_usage 為累計值，取每檔末筆，並以 last_token_usage 總和交叉驗證",
            "Codex 的 cached_input_tokens 是 input_tokens 的子集，已拆成互斥兩份；Anthropic 三項本就互斥",
            "Cowork 稽核紀錄於回應完成前寫入，output_tokens 不完整（實測單一 session 339 則、"
            "最大值僅 73），已計為 outputUnknown 而非 0，output 欄位不含這些則",
            "不提供單一「總 token」數字：四項直接相加會被 cache_read 主導（占九成以上），"
            "技術上為真但誤導。應引用 billableInput（依快取倍率折算的輸入計價當量）與 output。",
            f"快取倍率：{json.dumps(RATE, ensure_ascii=False)}（倍率非金額，報告前請對照官方定價頁覆核）",
            f"跨檔重複捨棄 {cross_dup} 筆",
        ],
        "rates": RATE,
        # 已知限制。與網站 §09「期間涵蓋與已知落差」同一個標準：
        # 不利於自己的、還沒確認的，一律隨數字一起端出去，不藏在附錄。
        "caveats": [
            "快取倍率為**倍率非金額**，取自各家公開的快取計價說明。正式報告前"
            "須對照當時官方定價頁覆核——OpenAI 側的快取折扣隨模型世代調整過，"
            "本檔採 0.25× 係研判值。",
            "Cowork 的 output_tokens 稽核紀錄不完整，已計為 outputUnknown。"
            "因此 output 總量為**低估**，且低估幅度無法從本機紀錄推算。",
            "歸屬採寬口徑：專案期間內的工作階段一律計入，未逐一區分 SCAI 與"
            "其他工作。故本數字為**上界性質**，非精確歸屬。",
            "Cowork 網頁版（claude.ai）若有 SCAI 工作，本機無紀錄、未納入。",
            "本統計僅涵蓋**開發階段**；運作階段（雲端管線）為 **0**——"
            "本專案未取得 API 預算，管線從未執行，非尚未統計。",
        ],
        "scopeFile": "data/token_scope.json",
        "totals": scopes,
        "byTool": {k: enrich(v) for k, v in by_tool.items()},
        "byModel": {k: enrich(v) for k, v in by_model.items()},
        "byDay": [{"date": k, **enrich(v)} for k, v in sorted(by_day.items())],
        "sessions": [{
            "tool": f["tool"], "session": f["session"], "scope": f["scope"],
            "reviewed": f["reviewed"],      # false＝歸屬檔裡沒有，excluded 是預設值不是決定
            "mentions": f["mentions"], "from": f["from"], "to": f["to"],
            **enrich(f["totals"]),
        } for f in files],
        "prices": prices,
    }

    # 隱私硬性把關：public repo 產物不得含使用者路徑
    blob = json.dumps(out, ensure_ascii=False)
    for leak in (str(HOME), HOME.name, os.environ.get("USERNAME") or "\0"):
        if leak and leak in blob:
            sys.exit(f"[錯誤] 輸出含本機路徑或使用者名稱（{leak}）——拒絕寫出")

    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[完成] {OUT_PATH}")
    print(f"[驗收] 已確認輸出不含使用者路徑／名稱；{len(files)} 個 session、"
          f"{len(out['byDay'])} 個日期、{len(by_model)} 個模型")


if __name__ == "__main__":
    main()
