"""Derive logo variants + brand color from assets/LOGO.webp.

LOGO.webp is black script glyphs on a flat brand-yellow background.
Outputs (out/assets/):
  logo_black.png   glyphs in near-black, transparent bg  (for light surfaces)
  logo_yellow.png  glyphs in brand yellow, transparent bg (for dark surfaces)
  logo_white.png   glyphs in white, transparent bg
  brand.json       {"brand_yellow": "#xxxxxx"}
Alpha is derived from inverted luminance so anti-aliased edges survive.
"""

import json
import os

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ROOT, "assets")
OUT = os.path.join(ROOT, "out", "assets")
os.makedirs(OUT, exist_ok=True)


def main():
    img = Image.open(os.path.join(ASSETS, "LOGO.webp")).convert("RGB")
    arr = np.asarray(img).astype(np.float32)
    lum = arr.mean(axis=2)

    bg_mask = lum > 160  # flat yellow background pixels
    bg_rgb = np.clip(arr[bg_mask].mean(axis=0).round(), 0, 255).astype(int)
    brand_hex = "#%02x%02x%02x" % tuple(bg_rgb)

    l_bg = float(lum[bg_mask].mean())
    l_min = float(lum.min())
    alpha = np.clip((l_bg - lum) / max(l_bg - l_min, 1.0), 0.0, 1.0)

    # crop to glyph bbox with a small pad so layout maths are tight
    ys, xs = np.where(alpha > 0.04)
    pad = 12
    y0, y1 = max(ys.min() - pad, 0), min(ys.max() + pad, alpha.shape[0])
    x0, x1 = max(xs.min() - pad, 0), min(xs.max() + pad, alpha.shape[1])
    alpha = alpha[y0:y1, x0:x1]

    def colorize(rgb, name):
        h, w = alpha.shape
        out = np.zeros((h, w, 4), dtype=np.uint8)
        out[..., 0], out[..., 1], out[..., 2] = rgb
        out[..., 3] = (alpha * 255).astype(np.uint8)
        Image.fromarray(out).save(os.path.join(OUT, name))

    colorize((17, 17, 17), "logo_black.png")
    colorize(tuple(int(v) for v in bg_rgb), "logo_yellow.png")
    colorize((255, 255, 255), "logo_white.png")

    with open(os.path.join(OUT, "brand.json"), "w", encoding="utf-8") as f:
        json.dump({"brand_yellow": brand_hex}, f)
    print("brand yellow:", brand_hex, "| logo bbox:", alpha.shape)


if __name__ == "__main__":
    main()
