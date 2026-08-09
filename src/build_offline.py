#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SCAI-Agent｜決賽斷網備援產生器

產出 docs/index_offline.html：與線上版同一份模板、同一份資料，但**零外部請求**——
Chart.js、拉丁字體（Space Grotesk／IBM Plex Mono 的 latin 子集）、圖片全部內嵌。
中文字體無法內嵌（Noto Sans TC 全字集數 MB），改用系統 CJK 字體堆疊。

用法：
    python src/build_offline.py            # 需網路：首次下載字體到 src/_fontcache/
    python src/build_offline.py --no-net    # 無網路：字體快取不存在時退回系統字體

字體授權：Space Grotesk 與 IBM Plex Mono 均為 SIL Open Font License 1.1，允許內嵌。
"""
import base64, json, pathlib, re, sys, urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import sitedata

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "src" / "_fontcache"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
GF_CSS = ("https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@700"
          "&family=IBM+Plex+Mono:wght@400;500;600&display=swap")
NO_NET = "--no-net" in sys.argv


def load(p):
    return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def b64_data_uri(data: bytes, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


def build_font_css() -> str:
    """取 Google Fonts 的 latin 子集 @font-face，woff2 內嵌為 data URI。"""
    CACHE.mkdir(exist_ok=True)
    css_path = CACHE / "gf.css"
    if not css_path.exists():
        if NO_NET:
            return ""
        css_path.write_bytes(fetch(GF_CSS))
    css = css_path.read_text(encoding="utf-8")

    out, kept = [], []
    # 每個 @font-face 前面有 /* subset */ 註解，只保留 latin
    for m in re.finditer(r"/\*\s*([a-z0-9\-\[\]]+)\s*\*/\s*(@font-face\s*\{.+?\})", css, re.S):
        subset, block = m.group(1), m.group(2)
        if subset != "latin":
            continue
        url_m = re.search(r"url\((https://fonts\.gstatic\.com/[^)]+\.woff2)\)", block)
        if not url_m:
            continue
        url = url_m.group(1)
        local = CACHE / (re.sub(r"\W+", "_", url.rsplit("/", 2)[-2] + "_" + url.rsplit("/", 1)[-1]))
        if not local.exists():
            if NO_NET:
                continue
            local.write_bytes(fetch(url))
        fam = re.search(r"font-family:\s*'([^']+)'", block).group(1)
        wt = re.search(r"font-weight:\s*(\d+)", block)
        kept.append(f"{fam} {wt.group(1) if wt else '400'}")
        block = block.replace(url, b64_data_uri(local.read_bytes(), "font/woff2"))
        # 內嵌字體不需 unicode-range 限制（只有 latin 一組），但保留無害
        out.append(block)
    if out:
        print(f"[字體] 內嵌 {len(out)} 組 latin 子集：{'、'.join(kept)}")
    else:
        print("[字體] 未內嵌（無快取且 --no-net）→ 拉丁字型退回系統字體")
    return "\n".join(out)


def main():
    # ── 資料（與 build_site.py 共用 sitedata.build_payload，不再各自複製）──
    weeks = sitedata.build_payload(ROOT)["weeks"]
    data_js = sitedata.payload_js(ROOT)

    html = (ROOT / "src" / "site_template.html").read_text(encoding="utf-8")
    assets = ROOT / "docs" / "assets"

    def must(old, new, tag):
        nonlocal html
        if html.count(old) != 1:
            sys.exit(f"[錯誤] 錨點 {tag} 命中 {html.count(old)} 次（需 1 次）——模板已變動，請更新本腳本")
        html = html.replace(old, new)

    # ── 1. 移除 Google Fonts 外部請求，改內嵌 latin 子集 ──
    must('<link rel="preconnect" href="https://fonts.googleapis.com">\n'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n',
         "", "preconnect")
    link_m = re.search(r'<link href="https://fonts\.googleapis\.com/css2[^"]+" rel="stylesheet">', html)
    if not link_m:
        sys.exit("[錯誤] 找不到 Google Fonts <link>")
    font_notice = (
        "/* 內嵌字體（latin 子集）授權聲明\n"
        "   Space Grotesk — Copyright (c) 2020 Florian Karsten\n"
        "   IBM Plex Mono  — Copyright (c) 2017 IBM Corp.\n"
        "   兩者皆採 SIL Open Font License 1.1：https://scripts.sil.org/OFL\n"
        "   OFL 允許嵌入於文件；本檔為決賽斷網備援，中文字體因體積過大未內嵌，改用系統 CJK 字體。*/\n")
    html = html.replace(link_m.group(0),
                        "<style>" + font_notice + build_font_css() + "</style>")

    # ── 2. 中文改用系統 CJK 字體堆疊（Noto Sans TC 無法內嵌）──
    must('font-family:"Noto Sans TC",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;',
         'font-family:"Noto Sans TC","Microsoft JhengHei UI","Microsoft JhengHei",'
         '"PingFang TC","Hiragino Sans CNS","Heiti TC",-apple-system,BlinkMacSystemFont,'
         '"Segoe UI",sans-serif;', "cjk stack")

    # ── 3. Chart.js 內嵌（連同 CDN 失敗時的本地備援 script 一併移除）──
    chart_js = (assets / "chart.umd.min.js").read_text(encoding="utf-8")
    must('<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>\n'
         '<script>window.Chart||document.write(\'<script src="assets/chart.umd.min.js"><\\/script>\')</script>',
         "<script>/* Chart.js 4.4.1（內嵌，MIT）*/\n" + chart_js + "\n</script>", "chartjs")

    # ── 4. 圖片內嵌為 data URI ──
    for name in ("scai-logo-light-bg.png", "scai-logo-dark-bg.png", "scai-header-pattern.png"):
        f = assets / name
        if not f.exists():
            sys.exit(f"[錯誤] 缺少素材 {f}")
        uri = b64_data_uri(f.read_bytes(), "image/png")
        n = html.count(f"assets/{name}")
        if n == 0:
            sys.exit(f"[錯誤] 模板未引用 {name}")
        html = html.replace(f"assets/{name}", uri)
        print(f"[圖片] {name} 內嵌 {n} 處（{f.stat().st_size // 1024} KB）")

    # ── 5. 標題標示離線版，避免 Demo 時混淆 ──
    must("<title>SCAI-Agent｜半導體前瞻戰略情報</title>",
         "<title>SCAI-Agent｜半導體前瞻戰略情報（離線版）</title>", "title")

    # ── 6. 注入資料 ──
    if "/*__DATA__*/" not in html:
        sys.exit("[錯誤] 佔位符遺失")
    # 離線旗標：助理面板據此關閉 AI endpoint。斷網備援的意義就是零外部請求，
    # 不能因為助理接了後端就在離線檔裡偷偷發 fetch。
    html = html.replace("/*__DATA__*/",
                        "window.__SCAI_OFFLINE__=true;const DATA=" + data_js + ";")

    # 連 endpoint 字串本身也一併清掉：執行期旗標已足夠，但離線檔裡不留任何外部端點
    # 才經得起「打開原始碼檢查」——與零外部資源驗收同一個標準。
    ep_pat = re.compile(r"(endpoint:\s*)'https?://[^']*'")
    n_ep = len(ep_pat.findall(html))
    if n_ep != 1:
        sys.exit(f"[錯誤] SCAI_AI_CONFIG.endpoint 命中 {n_ep} 次（需 1 次）——模板已變動，請更新本腳本")
    html = ep_pat.sub(r"\1''", html)
    print("[離線] AI endpoint 已清空並置入離線旗標（助理僅提供規則式回答）")

    # ── 7. 零外部請求驗收 ──
    # 舊版只擋 src=，漏掉 <link href>、CSS url()、@import、srcset 等同樣會發出
    # 請求的形式——模板日後改動就會無聲溜過。此處列舉所有「載入資源」的引用方式；
    # <a href="https://…"> 是內容連結不是資源請求，刻意不納入。
    RESOURCE_PATTERNS = [
        ("src",      r'\bsrc\s*=\s*["\']https?://[^"\']+'),
        ("srcset",   r'\bsrcset\s*=\s*["\'][^"\']*https?://[^"\']*'),
        ("link",     r'<link\b[^>]*\bhref\s*=\s*["\']https?://[^"\']+'),
        ("css-url",  r'url\(\s*["\']?https?://[^)]+'),
        ("@import",  r'@import\s+(?:url\()?\s*["\']?https?://[^;]+'),
        ("poster",   r'\bposter\s*=\s*["\']https?://[^"\']+'),
        ("data-src", r'\bdata-src\s*=\s*["\']https?://[^"\']+'),
    ]
    res_leak = []
    for tag, pat in RESOURCE_PATTERNS:
        for m in re.findall(pat, html, re.I):
            res_leak.append(f"[{tag}] {m[:100]}")
    if res_leak:
        sys.exit("[錯誤] 仍有外部資源請求（共 %d 處）：\n       %s"
                 % (len(res_leak), "\n       ".join(res_leak[:5])))

    content_links = re.findall(r'<a\b[^>]*\bhref\s*=\s*["\']https?://[^"\']+', html, re.I)

    out = ROOT / "docs" / "index_offline.html"
    out.write_text(html, encoding="utf-8")
    print(f"[完成] {out}（{len(weeks)} 週，{len(html) // 1024} KB）")
    print(f"[驗收] 外部資源請求 0 個（已檢查 {len(RESOURCE_PATTERNS)} 種引用形式："
          f"{'、'.join(t for t, _ in RESOURCE_PATTERNS)}）；"
          f"保留 {len(content_links)} 條內容連結（離線時不可點但需存在）")


if __name__ == "__main__":
    main()
