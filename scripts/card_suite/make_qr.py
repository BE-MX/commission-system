"""Generate one QR per salesperson (brand logo embedded center) and verify decode.

EC level H, quiet zone 4 modules; center logo plate covers ~6% of the code —
well inside H's ~30% damage tolerance. Each PNG is decode-verified with OpenCV
at full size AND downscaled to 300px (print/scan stress proxy). Any mismatch
fails the run — printed QR codes cannot be fixed after the fact.
Requires prep_assets.py to have produced out/assets/logo_black.png + brand.json.
"""

import json
import os
import sys

import cv2
import qrcode
from PIL import Image, ImageDraw
from qrcode.constants import ERROR_CORRECT_H

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "out", "assets")
os.makedirs(OUT, exist_ok=True)


def embed_logo(img: Image.Image) -> Image.Image:
    """QR 中央嵌品牌 logo：白色隔离底板 + 品牌黄圆角牌 + 黑 logo。"""
    with open(os.path.join(OUT, "brand.json"), encoding="utf-8") as f:
        yellow = json.load(f)["brand_yellow"]
    logo = Image.open(os.path.join(OUT, "logo_black.png")).convert("RGBA")

    img = img.convert("RGB")
    w = img.size[0]
    plate_w = int(w * 0.34)
    logo_w = int(plate_w * 0.86)
    logo_h = int(logo_w * logo.size[1] / logo.size[0])
    pad_y = int(plate_w * 0.09)
    plate_h = logo_h + pad_y * 2
    margin = int(w * 0.014)  # 白色隔离圈，把牌面和码点分开

    draw = ImageDraw.Draw(img)
    cx, cy = w // 2, img.size[1] // 2
    x0, y0 = cx - plate_w // 2, cy - plate_h // 2
    radius = int(plate_w * 0.12)
    draw.rounded_rectangle(
        (x0 - margin, y0 - margin, x0 + plate_w + margin, y0 + plate_h + margin),
        radius=radius + margin, fill="#ffffff",
    )
    draw.rounded_rectangle((x0, y0, x0 + plate_w, y0 + plate_h), radius=radius, fill=yellow)
    logo_resized = logo.resize((logo_w, logo_h), Image.LANCZOS)
    img.paste(logo_resized, (cx - logo_w // 2, cy - logo_h // 2), logo_resized)
    return img


def verify(path: str, expected: str) -> None:
    det = cv2.QRCodeDetector()
    full = cv2.imread(path)
    for label, im in (
        ("full", full),
        ("300px", cv2.resize(full, (300, 300), interpolation=cv2.INTER_AREA)),
    ):
        val, _, _ = det.detectAndDecode(im)
        if val != expected:
            print(f"FAIL {path} [{label}]: got {val!r}, want {expected!r}")
            sys.exit(1)


def main():
    with open(os.path.join(ROOT, "data.json"), encoding="utf-8") as f:
        data = json.load(f)
    for person in data["people"]:
        url = data["base_url"] + person["slug"] + "/"
        qr = qrcode.QRCode(error_correction=ERROR_CORRECT_H, box_size=32, border=4)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#111111", back_color="#ffffff").convert("RGB")
        img = embed_logo(img)
        path = os.path.join(OUT, f"qr_{person['slug']}.png")
        img.save(path)
        verify(path, url)
        print(f"OK  {url}  -> {os.path.basename(path)}  ({img.size[0]}px, logo embedded)")


if __name__ == "__main__":
    main()
