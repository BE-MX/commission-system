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
ASSETS = os.path.join(ROOT, "assets")
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


def embed_avatar(img: Image.Image, avatar_path: str, scale: float = 0.30) -> Image.Image:
    """透明底白码的中央头像：透明隔离缝（露出黑卡底）+ 品牌黄描边 + 圆形头像。

    scale=头像直径占码宽比例；头像图案复杂时大尺寸可能压垮纠错，调用方按
    0.30→0.26→0.22 递减重试，取第一个能解码的档位。
    """
    with open(os.path.join(OUT, "brand.json"), encoding="utf-8") as f:
        yellow = json.load(f)["brand_yellow"]
    avatar = Image.open(avatar_path).convert("RGB")

    img = img.convert("RGBA")
    w = img.size[0]
    d = int(w * scale)
    ring = int(d * 0.07)       # 品牌黄描边
    margin = int(w * 0.016)    # 透明隔离缝（黑卡自身当静区）

    cx, cy = w // 2, img.size[1] // 2
    draw = ImageDraw.Draw(img)
    r_outer = d // 2 + ring + margin
    draw.ellipse((cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer), fill=(0, 0, 0, 0))
    r_ring = d // 2 + ring
    draw.ellipse((cx - r_ring, cy - r_ring, cx + r_ring, cy + r_ring), fill=yellow)

    side = min(avatar.size)
    avatar = avatar.crop((
        (avatar.size[0] - side) // 2, 0,  # 头像重心在上半部，从顶部裁方
        (avatar.size[0] - side) // 2 + side, side,
    )).resize((d, d), Image.LANCZOS)
    mask = Image.new("L", (d * 4, d * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, d * 4, d * 4), fill=255)
    mask = mask.resize((d, d), Image.LANCZOS)
    img.paste(avatar, (cx - d // 2, cy - d // 2), mask)
    return img


def decodes(path: str, expected: str) -> bool:
    det = cv2.QRCodeDetector()
    full = cv2.imread(path)
    for im in (full, cv2.resize(full, (300, 300), interpolation=cv2.INTER_AREA)):
        val, _, _ = det.detectAndDecode(im)
        if val != expected:
            return False
    return True


def decodes_inverted(path: str, expected: str) -> bool:
    """白码点透明底（印在黑卡上）的验证：合成黑底后反相成标准深码再解。"""
    det = cv2.QRCodeDetector()
    rgba = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if rgba is None:
        return False
    if rgba.ndim == 3 and rgba.shape[2] == 4:
        alpha = rgba[:, :, 3:4].astype("float32") / 255.0
        rgb = (rgba[:, :, :3].astype("float32") * alpha).astype("uint8")
    else:
        rgb = rgba
    inv = 255 - rgb
    for im in (inv, cv2.resize(inv, (300, 300), interpolation=cv2.INTER_AREA)):
        val, _, _ = det.detectAndDecode(im)
        if val != expected:
            return False
    return True


def verify(path: str, expected: str) -> None:
    if not decodes(path, expected):
        print(f"FAIL {path}: does not decode to {expected!r}")
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

        # WhatsApp 直聊码（码心=业务员头像）；印刷尺寸小（~10mm），box_size 保持高清
        if person.get("whatsapp"):
            wa_digits = "".join(ch for ch in person["whatsapp"] if ch.isdigit())
            wa_url = f"https://wa.me/{wa_digits}"
            wa_qr = qrcode.QRCode(error_correction=ERROR_CORRECT_H, box_size=32, border=4)
            wa_qr.add_data(wa_url)
            wa_qr.make(fit=True)
            # 白码点 + 透明底：印在黑卡上是反色码（现代手机相机/微信均支持反色扫描）
            wa_base = wa_qr.make_image(
                fill_color="#ffffff", back_color="transparent"
            ).convert("RGBA")
            wa_path = os.path.join(OUT, f"qr_wa_{person['slug']}.png")
            for scale in (0.30, 0.26, 0.22):
                embed_avatar(wa_base.copy(), os.path.join(ASSETS, person["avatar"]), scale).save(wa_path)
                if decodes_inverted(wa_path, wa_url):
                    print(f"OK  {wa_url}  -> {os.path.basename(wa_path)}  (white/transparent, avatar @{int(scale*100)}%)")
                    break
            else:
                print(f"FAIL {wa_path}: undecodable at all avatar scales")
                sys.exit(1)


if __name__ == "__main__":
    main()
