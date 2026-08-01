"""Generate one QR per salesperson and verify every code decodes.

EC level H, quiet zone 4 modules. Each PNG is decode-verified with OpenCV at
full size AND downscaled to 300px (print/scan stress proxy). Any mismatch fails
the run — printed QR codes cannot be fixed after the fact.
"""

import json
import os
import sys

import cv2
import qrcode
from qrcode.constants import ERROR_CORRECT_H

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "out", "assets")
os.makedirs(OUT, exist_ok=True)


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
        path = os.path.join(OUT, f"qr_{person['slug']}.png")
        img.save(path)
        verify(path, url)
        print(f"OK  {url}  -> {os.path.basename(path)}  ({img.size[0]}px)")


if __name__ == "__main__":
    main()
