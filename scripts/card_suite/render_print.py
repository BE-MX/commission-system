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
OUT_PRINT = os.path.join(ROOT, "out", "print")
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
    cmd = [
        CHROME,
        "--headless",
        "--disable-gpu",
        "--no-pdf-header-footer",
        "--virtual-time-budget=4000",
        f"--print-to-pdf={pdf_path}",
        file_uri(html_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
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
    avatars = [file_uri(os.path.join(ASSETS, p["avatar"])) for p in data["people"]]
    html = fill(poster_tpl, {
        **common,
        "AV1": avatars[0], "AV2": avatars[1], "AV3": avatars[2], "AV4": avatars[3],
    })
    html_path = os.path.join(OUT_HTML, "poster_a1.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    pdf_path = os.path.join(OUT_PRINT, "poster_a1.pdf")
    chrome_pdf(html_path, pdf_path)
    print("PDF", pdf_path, os.path.getsize(pdf_path), "bytes")


if __name__ == "__main__":
    sys.exit(main())
