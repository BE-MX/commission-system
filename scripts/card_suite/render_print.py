"""Render print PDFs (4 cards + 1 poster) via system Chrome headless.

Card: 94x58mm per page incl. 2mm bleed (trim 90x54). Poster: 600x847mm incl.
3mm bleed (trim A1 594x841). Physical size comes from CSS @page; Chrome
headless honors it with --no-pdf-header-footer.
"""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ROOT, "assets")
OUT_ASSETS = os.path.join(ROOT, "out", "assets")
OUT_HTML = os.path.join(ROOT, "out", "html")
# 可选 argv[1] 指定 out/ 下的输出子目录（默认 print）——旧 PDF 被阅读器锁住时换目录出新版
OUT_PRINT = os.path.join(ROOT, "out", sys.argv[1] if len(sys.argv) > 1 else "print")
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

for d in (OUT_HTML, OUT_PRINT):
    os.makedirs(d, exist_ok=True)


def file_uri(path: str) -> str:
    return "file:///" + os.path.abspath(path).replace("\\", "/")


def fill(template: str, mapping: dict) -> str:
    for key, value in mapping.items():
        template = template.replace("{{" + key + "}}", value)
    if "{{" in template:
        raise ValueError("unfilled placeholder remains: " + template[template.index("{{"):][:60])
    return template


def chrome_pdf(html_path: str, pdf_path: str) -> None:
    # 渲染前删旧产物：chrome 失败时旧文件会骗过存在性检查，产出"看似成功的陈旧 PDF"
    if os.path.exists(pdf_path):
        os.remove(pdf_path)
    cmd = [
        CHROME,
        "--headless",
        "--disable-gpu",
        "--no-pdf-header-footer",
        "--virtual-time-budget=4000",
        f"--print-to-pdf={pdf_path}",
        file_uri(html_path),
    ]
    # encoding 显式 utf-8：Windows 默认 GBK 解码 chrome stderr 会炸 reader 线程
    res = subprocess.run(cmd, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=120)
    if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) < 1000:
        print(res.stdout)
        print(res.stderr)
        raise RuntimeError(f"chrome failed for {html_path}")


def main():
    with open(os.path.join(ROOT, "data.json"), encoding="utf-8") as f:
        data = json.load(f)
    with open(os.path.join(OUT_ASSETS, "brand.json"), encoding="utf-8") as f:
        brand = json.load(f)

    with open(os.path.join(ROOT, "card_template.html"), encoding="utf-8") as f:
        card_tpl = f.read()

    common = {
        "BRAND_YELLOW": brand["brand_yellow"],
        "LOGO_BLACK_URI": file_uri(os.path.join(OUT_ASSETS, "logo_black.png")),
    }

    for person in data["people"]:
        wa_line = ""
        if person.get("whatsapp"):
            wa_line = f'<div class="wa"><span class="lbl">WA</span>{person["whatsapp"]}</div>'
        html = fill(card_tpl, {
            **common,
            "NAME": person["name"],
            "TITLE": person["title"],
            "EMAIL": person["email"],
            "WA_LINE": wa_line,
            "AVATAR_URI": file_uri(os.path.join(ASSETS, person["avatar"])),
            "QR_URI": file_uri(os.path.join(OUT_ASSETS, f"qr_{person['slug']}.png")),
        })
        html_path = os.path.join(OUT_HTML, f"card_{person['slug']}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        pdf_path = os.path.join(OUT_PRINT, f"card_{person['slug']}.pdf")
        chrome_pdf(html_path, pdf_path)
        print("PDF", pdf_path, os.path.getsize(pdf_path), "bytes")

    with open(os.path.join(ROOT, "poster_template.html"), encoding="utf-8") as f:
        poster_tpl = f.read()
    # 海报二维码预留 Janny 的（用户指定）
    html = fill(poster_tpl, {
        **common,
        "QR_URI": file_uri(os.path.join(OUT_ASSETS, "qr_janny.png")),
    })
    html_path = os.path.join(OUT_HTML, "poster_a1.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    pdf_path = os.path.join(OUT_PRINT, "poster_a1.pdf")
    chrome_pdf(html_path, pdf_path)
    print("PDF", pdf_path, os.path.getsize(pdf_path), "bytes")


if __name__ == "__main__":
    sys.exit(main())
