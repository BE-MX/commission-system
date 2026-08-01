"""Bake per-salesperson static homepages into frontend/public/card/<slug>/.

Public layer is fully static (intro/FAQ baked in) so the printed QR keeps
working even if the backend is down; only passcode unlock + inquiry hit /api.
Re-run after editing data.json or page_template.html. WhatsApp button and
links section render only when data is present (deferred for now).
"""

import json
import os
import shutil
import urllib.parse

ROOT = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ROOT, "assets")
OUT_ASSETS = os.path.join(ROOT, "out", "assets")
PUBLIC = os.path.abspath(os.path.join(ROOT, "..", "..", "frontend", "public", "card"))


def fill(template: str, mapping: dict) -> str:
    for key, value in mapping.items():
        template = template.replace("{{" + key + "}}", value)
    if "{{" in template:
        raise ValueError("unfilled placeholder: " + template[template.index("{{"):][:60])
    return template


def main():
    with open(os.path.join(ROOT, "data.json"), encoding="utf-8") as f:
        data = json.load(f)
    with open(os.path.join(OUT_ASSETS, "brand.json"), encoding="utf-8") as f:
        brand = json.load(f)
    with open(os.path.join(ROOT, "page_template.html"), encoding="utf-8") as f:
        tpl = f.read()

    for person in data["people"]:
        slug = person["slug"]
        out_dir = os.path.join(PUBLIC, slug)
        os.makedirs(out_dir, exist_ok=True)

        wa_button = ""
        if person.get("whatsapp"):
            wa_digits = "".join(ch for ch in person["whatsapp"] if ch.isdigit())
            wa_button = (
                f'<a class="btn btn-ghost" href="https://wa.me/{wa_digits}">'
                f'WhatsApp {person["name"]}</a>'
            )

        links_section = ""
        if person.get("links"):
            items = "".join(
                f'<a class="btn btn-ghost" style="margin-top:10px" href="{l["url"]}">{l["label"]}</a>'
                for l in person["links"]
            )
            links_section = (
                '<section class="rise d1"><div class="sec-label">Our stores</div>'
                + items + "</section>"
            )

        html = fill(tpl, {
            "NAME": person["name"],
            "TITLE": person["title"],
            "EMAIL": person["email"],
            "SLUG": slug,
            "BRAND_YELLOW": brand["brand_yellow"],
            "BRAND_YELLOW_ENC": urllib.parse.quote(brand["brand_yellow"]),
            "WA_BUTTON": wa_button,
            "LINKS_SECTION": links_section,
        })
        with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
            f.write(html)
        shutil.copyfile(os.path.join(ASSETS, person["avatar"]), os.path.join(out_dir, "avatar.png"))
        shutil.copyfile(os.path.join(OUT_ASSETS, "logo_yellow.png"), os.path.join(out_dir, "logo.png"))
        print("baked", out_dir)


if __name__ == "__main__":
    main()
