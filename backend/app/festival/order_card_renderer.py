"""Dynamic order cards on the approved champagne-glass material plate."""

from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from app.core.time import beijing_now

_MATERIAL = Path(__file__).resolve().parents[2] / "assets" / "festival" / "order-glass.png"


def _fit_font(text, factory, size, width):
    font = factory(size)
    while size > 22 and font.getlength(text) > width:
        size -= 2
        font = factory(size)
    return font


def _engrave(image, position, text, font, *, display=False):
    """Shallow inset edges and a bronze gradient keep lettering part of the glass."""
    x, y = position
    edge = ImageDraw.Draw(image)
    edge.text((x + 1, y + 2), text, font=font, anchor="lt", fill=(255, 249, 224, 245))
    edge.text((x - 1, y - 1), text, font=font, anchor="lt", fill=(86, 48, 14, 200))
    mask = Image.new("L", image.size)
    ImageDraw.Draw(mask).text(position, text, font=font, anchor="lt", fill=255)
    ink = Image.new("RGBA", image.size)
    draw = ImageDraw.Draw(ink)
    top, bottom = ((126, 66, 13), (188, 121, 33)) if display else ((76, 44, 18), (115, 70, 31))
    for row in range(image.height):
        ratio = max(0, min(1, (row - y) / max(1, font.size)))
        color = tuple(round(a + (b - a) * ratio) for a, b in zip(top, bottom))
        draw.line((0, row, image.width, row), fill=(*color, 255))
    ink.putalpha(mask)
    image.alpha_composite(ink)


def render_order_card(event, assets_root, font, display_font, wrap):
    """No sale data is baked into the plate; every field is rendered at delivery."""
    with Image.open(_MATERIAL) as plate:
        image = plate.convert("RGBA").resize((1200, 675), Image.Resampling.LANCZOS)
    headline = str(event.get("label") or "订单喜报")
    _engrave(image, (96, 83), headline,
             _fit_font(headline, display_font, 88, 580), display=True)
    _engrave(image, (893, 74), "leShine Hair®", font(27, bold=True))

    avatar = assets_root / "avatars" / f"{event.get('subject_id')}.png"
    text_x = 96
    if event.get("subject_type") == "person" and avatar.is_file():
        draw = ImageDraw.Draw(image)
        draw.ellipse((91, 190, 347, 446), fill=(126, 88, 31, 230))
        draw.ellipse((93, 192, 345, 444), fill=(251, 226, 169, 245))
        draw.ellipse((96, 195, 342, 441), fill=(255, 249, 226, 250))
        draw.ellipse((100, 199, 338, 437), fill=(171, 125, 52, 230))
        with Image.open(avatar) as source:
            portrait = ImageOps.fit(source.convert("RGBA"), (232, 232),
                                    method=Image.Resampling.LANCZOS)
        mask = Image.new("L", (696, 696))
        ImageDraw.Draw(mask).ellipse((0, 0, 695, 695), fill=255)
        mask = mask.resize((232, 232), Image.Resampling.LANCZOS)
        # Preserve transparent pixels in avatars instead of replacing them with black.
        from PIL import ImageChops
        portrait.putalpha(ImageChops.multiply(portrait.getchannel("A"), mask))
        image.alpha_composite(portrait, (103, 202))
        text_x = 367
    name = str(event.get("subject_name") or "业务员")
    name_font = _fit_font(name, lambda size: font(size, bold=True), 62, 405)
    name = wrap(ImageDraw.Draw(image), name, name_font, 405, max_lines=1)[0]
    _engrave(image, (text_x, 247), name, name_font)

    details = str(event.get("detail") or "").splitlines()
    customer = details[0] if details else ""
    for idx, line in enumerate(wrap(ImageDraw.Draw(image), customer, font(29), 405)):
        _engrave(image, (text_x, 337 + idx * 38), line, font(29))
    amount = event.get("amount")
    amount_text = f"${float(amount):,.0f}" if amount is not None else (
        details[1] if len(details) > 1 else "")
    if amount_text:
        _engrave(image, (96, 460), amount_text,
                 _fit_font(amount_text, lambda size: font(size, bold=True), 84, 565),
                 display=True)
    created = event.get("created_at")
    created_text = (created.strftime("%Y-%m-%d %H:%M") if isinstance(created, datetime)
                    else str(created or beijing_now().strftime("%Y-%m-%d %H:%M")))
    _engrave(image, (98, 565), f"方舟订单 · {created_text}", font(25))
    return image
