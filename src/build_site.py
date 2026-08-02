#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SCAI-Agent｜公開網站產生器 — 雲端管線版
移植自 cowork/scripts/build_site.py；資料來源改為 data/weeks.json 陣列，
輸出 docs/index.html（GitHub Pages：Settings → Pages → main ＋ /docs）。

模板 src/site_template.html 以 'W'+week 顯示週次並用 #w{n} hash 導覽，
故 week 欄位一律正規化為數字後再嵌入。

用法： python src/build_site.py
"""
import json, copy, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

def load(p):
    return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))

def main():
    weeks = copy.deepcopy(load(ROOT / "data" / "weeks.json"))
    for w in weeks:
        w["week"] = int(str(w["week"]).lstrip("Ww"))
    weeks.sort(key=lambda w: w["week"])

    cfg = load(ROOT / "data" / "kdf_config.json")
    prof = load(ROOT / "data" / "company_profile.json")
    pb = load(ROOT / "data" / "playbook.json")
    extras_path = ROOT / "data" / "kdf_definitions.json"
    extras = load(extras_path) if extras_path.exists() else {"kdfDefs": {}, "scenarioMeta": []}

    payload = {
        "weeks": weeks,
        "kdf": cfg["kdf"],
        "dims": cfg["dimensions"],
        "horizons": pb["horizons"],
        "levers": {l["id"]: l for l in prof["decision_levers"]},
        "profile": prof,
        "kdfDefs": extras.get("kdfDefs", {}),
        "scenarioMeta": extras.get("scenarioMeta", []),
    }
    data_js = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    tpl = (ROOT / "src" / "site_template.html").read_text(encoding="utf-8")
    html = tpl.replace("/*__DATA__*/", "const DATA=" + data_js + ";")
    out_dir = ROOT / "docs"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    print(f"[完成] {out}（{len(weeks)} 週資料，{len(html)//1024} KB）")

if __name__ == "__main__":
    main()
