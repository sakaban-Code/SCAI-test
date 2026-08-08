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
import pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import sitedata

ROOT = pathlib.Path(__file__).resolve().parent.parent

def main():
    payload = sitedata.build_payload(ROOT)
    weeks = payload["weeks"]
    data_js = sitedata.payload_js(ROOT)

    tpl = (ROOT / "src" / "site_template.html").read_text(encoding="utf-8")
    if tpl.count("/*__DATA__*/") != 1:
        sys.exit(f"[錯誤] 模板中的 /*__DATA__*/ 標記出現 {tpl.count('/*__DATA__*/')} 次（需 1 次）")
    html = tpl.replace("/*__DATA__*/", "const DATA=" + data_js + ";")
    out_dir = ROOT / "docs"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    print(f"[完成] {out}（{len(weeks)} 週資料，{len(html)//1024} KB）")

if __name__ == "__main__":
    main()
