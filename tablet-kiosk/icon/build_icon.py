"""从品牌字标一路生成 APP 图标全套 Android 资源。

    cd backend && ./.venv/Scripts/python.exe ../tablet-kiosk/icon/build_icon.py

主体是 frontend/src/assets/leshine-logo-gold.png 里那个花体 S：按连通域原尺抠出、保留手写笔锋，
配 kiosk 页面同款黑金（墨底 + 金渐变）。产物：
  icon/source_{background,foreground}.png  432×432 母版
  icon/preview_512.png                     展示图
  app/src/main/res/mipmap-*/               五档密度的自适应三层 + legacy 回退
"""
import os

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, "..", "..", "frontend", "src", "assets", "leshine-logo-gold.png"))
RES = os.path.normpath(os.path.join(HERE, "..", "app", "src", "main", "res"))

CANVAS, SAFE = 432, 288          # 108dp / 72dp 安全区，@xxxhdpi
S_BBOX = (424, 57, 1220, 772)    # 花体 S 在字标里的位置（连通域探测所得）
S_HEIGHT = 232                   # 安全区的 ~80%；再大会顶到圆形 mask 边缘
INK, INK_2 = (12, 10, 8), (26, 22, 17)
GOLD, GOLD_HI, GOLD_MID = (212, 148, 28), (247, 227, 176), (232, 196, 121)
DENSITIES = {"mdpi": 1.0, "hdpi": 1.5, "xhdpi": 2.0, "xxhdpi": 3.0, "xxxhdpi": 4.0}


def extract_s(thicken=0):
    """抠出花体 S。字标里 S 是最大连通域，据此剔掉裁剪框蹭到的邻近字母。"""
    arr = np.array(Image.open(SRC).convert("RGBA").crop(S_BBOX))
    mask = (arr[:, :, 3] > 100).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n > 1:
        biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        arr[:, :, 3] = np.where(labels == biggest, arr[:, :, 3], 0)
    if thicken:
        # 手写体细笔画在 48dp 下会断，轻微膨胀让它结实，笔锋仍在
        arr[:, :, 3] = cv2.dilate(arr[:, :, 3], np.ones((thicken * 2 + 1,) * 2, np.uint8))
    return Image.fromarray(arr)


def recolor(s, top, bottom):
    """按 alpha 重上竖向渐变（顶浅底深，与品牌字标同向）"""
    w, h = s.size
    g = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        g.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(g.resize((w, h), Image.BILINEAR), (0, 0), s.split()[3])
    return out


def fit_h(s, target_h):
    w, h = s.size
    return s.resize((max(1, round(w * target_h / h)), target_h), Image.LANCZOS)


def paste_centered(canvas, s):
    """按 alpha 质心对齐画布中心——bbox 居中会让花体 S 明显偏左上"""
    a = np.array(s.split()[3], dtype=float)
    ys, xs = np.nonzero(a)
    w = a[ys, xs]
    canvas.paste(s, (round(CANVAS / 2 - (xs * w).sum() / w.sum()),
                     round(CANVAS / 2 - (ys * w).sum() / w.sum())), s)
    return canvas


def build_layers():
    """返回 (background, foreground)，均为 432×432 RGBA"""
    bg = Image.new("RGB", (CANVAS, CANVAS), INK)
    d = ImageDraw.Draw(bg)
    for i in range(60, 0, -1):          # 径向层次：纯平色在小尺寸下发死
        t = i / 60
        r = int(CANVAS * .78 * t)
        c = tuple(int(INK[k] + (INK_2[k] - INK[k]) * (1 - t) ** 1.6) for k in range(3))
        d.ellipse([CANVAS // 2 - r] * 2 + [CANVAS // 2 + r] * 2, fill=c)
    bg = bg.filter(ImageFilter.GaussianBlur(18)).convert("RGBA")

    fg = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    glow = paste_centered(Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0)),
                          recolor(fit_h(extract_s(5), S_HEIGHT + 6), GOLD_MID, GOLD_MID))
    glow = glow.filter(ImageFilter.GaussianBlur(14))
    glow.putalpha(glow.split()[3].point(lambda v: int(v * .22)))   # 极淡金晕，让金字从墨底浮起
    fg.alpha_composite(glow)
    paste_centered(fg, recolor(fit_h(extract_s(2), S_HEIGHT), GOLD_HI, GOLD))
    return bg, fg


def squircle(size):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * .235), fill=255)
    return m


def circle(size):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).ellipse([0, 0, size - 1, size - 1], fill=255)
    return m


def legacy_icon(full, px):
    """legacy 图标没有安全区概念：裁出中心 72dp 再回补边距，否则比自适应版本小一圈"""
    crop = round(full.width * (SAFE / CANVAS))
    off = (full.width - crop) // 2
    core = full.crop((off, off, off + crop, off + crop))
    canvas = Image.new("RGBA", (round(crop * 1.18),) * 2, full.getpixel((4, 4)))
    canvas.alpha_composite(core, ((canvas.width - crop) // 2,) * 2)
    return canvas.resize((px, px), Image.LANCZOS)


def main():
    bg, fg = build_layers()
    bg.save(os.path.join(HERE, "source_background.png"))
    fg.save(os.path.join(HERE, "source_foreground.png"))

    full = bg.copy()
    full.alpha_composite(fg)
    full.resize((512, 512), Image.LANCZOS).convert("RGB").save(os.path.join(HERE, "preview_512.png"))

    # Android 13+ 主题图标：只要形状，去掉金晕（单色下会糊成脏边）
    a = np.array(fg)[:, :, 3]
    a = np.where(a > 150, 255, 0).astype(np.uint8)
    mono = Image.fromarray(np.dstack([np.full_like(a, 255)] * 3 + [a]), "RGBA")

    for name, scale in DENSITIES.items():
        d = os.path.join(RES, f"mipmap-{name}")
        os.makedirs(d, exist_ok=True)
        ap, lg = round(108 * scale), round(48 * scale)
        fg.resize((ap, ap), Image.LANCZOS).save(os.path.join(d, "ic_launcher_foreground.png"))
        bg.resize((ap, ap), Image.LANCZOS).convert("RGB").save(os.path.join(d, "ic_launcher_background.png"))
        mono.resize((ap, ap), Image.LANCZOS).save(os.path.join(d, "ic_launcher_monochrome.png"))
        base = legacy_icon(full, lg)
        for fname, mask in (("ic_launcher.png", squircle(lg)), ("ic_launcher_round.png", circle(lg))):
            out = Image.new("RGBA", (lg, lg), (0, 0, 0, 0))
            out.paste(base, (0, 0), mask)
            out.save(os.path.join(d, fname))
        print(f"mipmap-{name}: adaptive {ap}px, legacy {lg}px")
    print("done ->", RES)


if __name__ == "__main__":
    main()
