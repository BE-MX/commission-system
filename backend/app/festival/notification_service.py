"""采购节事件图片、榜单截图与钉钉群可靠投递。"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import random
import subprocess
import tempfile
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path, PureWindowsPath
from urllib.parse import urlencode

import anyio
import httpx
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.dingtalk.webhook import DingTalkWebhookError, WebhookSender
from app.festival import service
from app.festival.models import FestivalEvent, FestivalState

logger = logging.getLogger("festival.notification")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_UPLOAD_ROOT = _REPO_ROOT / "uploads" / "festival" / "dingtalk"
_BOARD_PAGES = (
    ("个人新签积分榜", "xinqian.html", "new-sign", "new-sign"),
    ("首返复购双榜", "fugou.html", "repurchase", "repurchase"),
    ("团队人均积分榜", "tuandui.html", "teams", "teams"),
    ("阵营新签 PK 榜", "zhenying.html", "camps", "camps"),
)
_BRAND_YELLOW = "#FDD956"
_BRAND_BLACK = "#080303"
_TEAM_LOGOS = {
    "专治不服": "zhuanzhibufu",
    "多财多亿": "duocaiduoyi",
    "稻乐偲": "daolesi",
    "星星之火": "xingxingzhihuo",
    "行则将至": "xingzejiangzhi",
    "乘风": "chengfeng",
    "无名": "wuming",
}
# 新签/大单来袭/超级大单/名次上升四类高光事件：奶油底黄色系极光 + 彩色烟花。
_AURORA_EVENT_TYPES = {
    "first_sign", "new_sign_order", "big_deal", "super_deal",
    "rank_up_sign", "rank_up_first", "rank_up_re", "rank_up_team",
}
_AURORA_LABELS = {"首单新签", "新签喜报", "大单来袭", "超级大单"}
_AURORA_BASE_TOP = (255, 251, 245)
_AURORA_BASE_BOTTOM = (253, 242, 222)
_AURORA_BANDS = ((255, 240, 200), (255, 228, 150), (255, 219, 118), (255, 236, 180))
_FIREWORK_GOLD = (242, 165, 32)
_FIREWORK_WHITE = (255, 252, 244)


def _draw_firework(draw: ImageDraw.ImageDraw, center: tuple[int, int], radius: int) -> None:
    """绘制与黄黑主题一致的静态烟花线稿，避开正文区域。"""
    cx, cy = center
    for idx in range(12):
        angle = math.radians(idx * 30 - 90)
        inner = radius * 0.38
        x1 = cx + math.cos(angle) * inner
        y1 = cy + math.sin(angle) * inner
        x2 = cx + math.cos(angle) * radius
        y2 = cy + math.sin(angle) * radius
        draw.line((x1, y1, x2, y2), fill=_BRAND_BLACK, width=4)
        dot_x = cx + math.cos(angle) * (radius + 10)
        dot_y = cy + math.sin(angle) * (radius + 10)
        draw.ellipse((dot_x - 3, dot_y - 3, dot_x + 3, dot_y + 3), fill=_BRAND_BLACK)
    draw.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), fill=_BRAND_BLACK)


def _draw_sparkle(draw: ImageDraw.ImageDraw, center: tuple[int, int], size: int,
                  fill: str | tuple[int, int, int] = _BRAND_BLACK) -> None:
    """绘制四角星光，使用小面积实心色保持缩略图下仍清晰。"""
    cx, cy = center
    inner = max(2, round(size * 0.22))
    draw.polygon([
        (cx, cy - size), (cx + inner, cy - inner),
        (cx + size, cy), (cx + inner, cy + inner),
        (cx, cy + size), (cx - inner, cy + inner),
        (cx - size, cy), (cx - inner, cy - inner),
    ], fill=fill)


def _draw_flower(draw: ImageDraw.ImageDraw, center: tuple[int, int]) -> None:
    """绘制简洁花朵与枝叶，填补右下角但不侵入正文。"""
    cx, cy = center
    for idx in range(8):
        angle = math.radians(idx * 45)
        px = cx + math.cos(angle) * 23
        py = cy + math.sin(angle) * 23
        draw.ellipse((px - 11, py - 15, px + 11, py + 15),
                     fill=_BRAND_YELLOW, outline=_BRAND_BLACK, width=3)
    draw.ellipse((cx - 10, cy - 10, cx + 10, cy + 10), fill=_BRAND_BLACK)
    draw.line((cx, cy + 34, cx - 8, cy + 78), fill=_BRAND_BLACK, width=4)
    draw.polygon([(cx - 5, cy + 54), (cx - 31, cy + 45), (cx - 13, cy + 67)],
                 fill=_BRAND_BLACK)
    draw.polygon([(cx - 8, cy + 68), (cx + 18, cy + 59), (cx - 4, cy + 79)],
                 fill=_BRAND_BLACK)


def _is_aurora_event(event: dict) -> bool:
    """新签/大单来袭/超级大单/名次上升类事件使用极光主题。"""
    if event.get("event_type") in _AURORA_EVENT_TYPES:
        return True
    label = str(event.get("label") or "")
    return label in _AURORA_LABELS or "名次上升" in label


def _aurora_background(width: int, height: int) -> Image.Image:
    """奶油底上铺浅金/暖黄极光色块并整体柔化，四类高光事件共用同色系。"""
    base = Image.new("RGB", (width, height))
    base_draw = ImageDraw.Draw(base)
    for y in range(height):
        ratio = y / (height - 1)
        color = tuple(round(top + (bottom - top) * ratio)
                      for top, bottom in zip(_AURORA_BASE_TOP, _AURORA_BASE_BOTTOM))
        base_draw.line((0, y, width, y), fill=color)
    base_draw.ellipse((-260, 60, 520, 640), fill=_AURORA_BANDS[0])
    base_draw.ellipse((620, -220, 1520, 260), fill=_AURORA_BANDS[1])
    base_draw.ellipse((840, 220, 1580, 780), fill=_AURORA_BANDS[2])
    base_draw.ellipse((240, 300, 920, 980), fill=_AURORA_BANDS[3])
    return base.filter(ImageFilter.GaussianBlur(130))


def _draw_gold_firework(layer: Image.Image, center: tuple[int, int],
                        radius: int, seed: int = 0) -> None:
    """在透明图层上画一朵烟花：金色为主、白色点缀，火花细长、外端衰减微垂，
    末端带亮点，中心留白色高温核——模拟真实礼花弹而非卡通星芒。"""
    rng = random.Random(seed)
    cx, cy = center
    draw = ImageDraw.Draw(layer)
    for _ in range(max(28, int(radius * 1.7))):
        angle = rng.uniform(0.0, math.tau)
        reach = radius * rng.uniform(0.45, 1.0)
        r, g, b = _FIREWORK_GOLD if rng.random() < 0.75 else _FIREWORK_WHITE
        gain = rng.uniform(0.7, 1.0)
        color = (round(r * gain), round(g * gain), round(b * gain))
        start = radius * 0.10
        x0 = cx + math.cos(angle) * start
        y0 = cy + math.sin(angle) * start
        xm = cx + math.cos(angle) * reach * 0.55
        ym = cy + math.sin(angle) * reach * 0.55
        x1 = cx + math.cos(angle) * reach
        y1 = cy + math.sin(angle) * reach + reach * 0.10  # 重力微垂
        width = 2 if reach > radius * 0.8 else 1
        draw.line((x0, y0, xm, ym), fill=color + (235,), width=width)
        draw.line((xm, ym, x1, y1), fill=color + (115,), width=1)
        draw.ellipse((x1 - 1.6, y1 - 1.6, x1 + 1.6, y1 + 1.6), fill=(r, g, b, 200))
    core = max(3, radius // 8)
    draw.ellipse((cx - core, cy - core, cx + core, cy + core), fill=(255, 252, 240, 235))


def _display_font(size: int):
    """主题字艺术字体：优先仓库内置华康海报体，缺失时依次回退其他美术字/常规粗体。"""
    candidates = [
        _REPO_ROOT / "backend" / "assets" / "fonts" / "huakang-haibao-w12.ttf",
        Path("C:/Users/windb/AppData/Local/Microsoft/Windows/Fonts/华康海报体W12.TTF"),
        Path("C:/Windows/Fonts/STHUPO.TTF"),
        Path("C:/Windows/Fonts/FZYTK.TTF"),
        Path("C:/Windows/Fonts/STXINWEI.TTF"),
    ]
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    return _font(size, bold=True)


def _draw_headline(image: Image.Image, text: str) -> None:
    """主题字：琥珀美术字 + 整体斜切 + 投影 + 奶白描边，制造冲击力。"""
    font = _display_font(88)
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    layer_draw = ImageDraw.Draw(layer)
    layer_draw.text((85, 57), text, font=font, fill=(61, 34, 8, 110))
    layer_draw.text((78, 50), text, font=font, fill=(194, 65, 12, 255),
                    stroke_width=2, stroke_fill=(255, 247, 232, 255))
    slanted = layer.transform(image.size, Image.Transform.AFFINE,
                              (1, -0.10, 0, 0, 1, 0), resample=Image.BICUBIC)
    image.alpha_composite(slanted)


def _font(size: int, bold: bool = False):
    settings = get_settings()
    candidates = []
    if bold:
        candidates.extend([
            Path("C:/Windows/Fonts/msyhbd.ttc"),
            Path("C:/Windows/Fonts/simhei.ttf"),
        ])
    candidates.extend([
        Path(settings.PDF_CJK_FONT_PATH),
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simsun.ttc"),
    ])
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    raise RuntimeError("采购节图片生成缺少中文字体，请配置 PDF_CJK_FONT_PATH")


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int,
          max_lines: int = 2) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in text:
        probe = current + char
        if current and draw.textlength(probe, font=font) > max_width:
            lines.append(current)
            current = char
            if len(lines) == max_lines:
                break
        else:
            current = probe
    if len(lines) < max_lines and current:
        lines.append(current)
    if len(lines) == max_lines and "".join(lines) != text:
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > max_width:
            last = last[:-1]
        lines[-1] = last + "…"
    return lines


def _event_token(dedup_key: str) -> str:
    settings = get_settings()
    secret = (
        (settings.FESTIVAL_SCREEN_KEYS or "").split(",")[0].strip()
        or settings.FESTIVAL_DINGTALK_WEBHOOK_SECRET
        or settings.JWT_SECRET_KEY
    )
    return hmac.new(secret.encode("utf-8"), dedup_key.encode("utf-8"), hashlib.sha256).hexdigest()[:24]


def _public_url(path: Path) -> str:
    rel = path.resolve().relative_to(_REPO_ROOT.resolve()).as_posix()
    return f"{get_settings().SHORT_LINK_BASE_URL.rstrip('/')}/{rel}"


def render_event_image(event: dict) -> Path:
    """把与大屏一致的事件内容渲染成 16:9 PNG，供钉钉内联显示。"""
    width, height = 1200, 675
    aurora = _is_aurora_event(event)
    if aurora:
        image = _aurora_background(width, height)
        ink, sub_ink, pill_ink, amount_ink = "#3F2A17", "#6B4A2E", "#FFF6EA", "#C2410C"
    else:
        image = Image.new("RGB", (width, height), _BRAND_YELLOW)
        ink, sub_ink, pill_ink, amount_ink = _BRAND_BLACK, "#332600", _BRAND_YELLOW, _BRAND_BLACK
    if aurora:
        fireworks = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        _draw_gold_firework(fireworks, (710, 118), 72, seed=11)
        _draw_gold_firework(fireworks, (930, 490), 52, seed=27)
        _draw_gold_firework(fireworks, (1065, 468), 40, seed=43)
        glow = fireworks.filter(ImageFilter.GaussianBlur(5))
        composed = Image.alpha_composite(image.convert("RGBA"), glow)
        composed = Image.alpha_composite(composed, fireworks)
        _draw_headline(composed, str(event.get("label") or "高光事件"))
        image = composed.convert("RGB")
    draw = ImageDraw.Draw(image)
    # 品牌图的核心识别来自纯黄底 + 黑色字标；装饰保持克制，避免抢事件正文。
    # 新签/大单/名次类高光事件切换为奶油底黄色系极光 + 金白烟花。
    draw.ellipse((1120, -210, 1420, 90), outline=ink, width=22)
    if aurora:
        _draw_sparkle(draw, (510, 455), 14, fill=_FIREWORK_GOLD)
        _draw_sparkle(draw, (810, 185), 10, fill=(214, 138, 20))
        _draw_sparkle(draw, (1080, 365), 12, fill=_FIREWORK_GOLD)
    else:
        _draw_firework(draw, (690, 104), 42)
        _draw_firework(draw, (920, 486), 30)
        _draw_sparkle(draw, (510, 455), 14)
        _draw_sparkle(draw, (810, 185), 10)
        _draw_sparkle(draw, (1080, 365), 12)
        _draw_flower(draw, (1060, 470))
    draw.text((900, 54), "leShine Hair®", font=_font(28, bold=True), fill=ink)

    draw.rounded_rectangle((44, 38, width - 44, height - 38), radius=34,
                           outline=ink, width=5)
    if not aurora:
        draw.rounded_rectangle((78, 70, 390, 126), radius=28, fill=ink)
        draw.ellipse((106, 92, 120, 106), fill=pill_ink)
        draw.text((132, 80), str(event.get("label") or "高光事件"),
                  font=_font(25, bold=True), fill=pill_ink)

    subject_name = str(event.get("subject_name") or "")
    assets_root = _REPO_ROOT / "frontend" / "public" / "festival" / "assets"
    subject_image_path = None
    if event.get("subject_type") == "person":
        subject_image_path = assets_root / "avatars" / f"{event.get('subject_id')}.png"
    elif event.get("subject_type") == "team":
        logo_key = _TEAM_LOGOS.get(subject_name)
        if logo_key:
            subject_image_path = assets_root / "team-logos" / f"{logo_key}.png"
    text_x = 118
    if subject_image_path and subject_image_path.is_file():
        subject_image = Image.open(subject_image_path).convert("RGB")
        subject_image = ImageOps.fit(subject_image, (150, 150))
        mask = Image.new("L", (150, 150), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 149, 149), fill=255)
        image.paste(subject_image, (82, 176), mask)
        draw.ellipse((78, 172, 236, 330), outline=ink, width=6)
        text_x = 278

    name_font = _font(68, bold=True)
    draw.text((text_x, 176), subject_name, font=name_font, fill=ink)
    detail = str(event.get("detail") or "")
    detail_font = _font(34)
    for idx, line in enumerate(_wrap(draw, detail, detail_font, width - text_x - 100)):
        draw.text((text_x, 275 + idx * 52), line, font=detail_font, fill=sub_ink)

    amount = event.get("amount")
    if amount:
        draw.text((82, 445), f"${float(amount):,.0f}", font=_font(66, bold=True), fill=amount_ink)
    created = event.get("created_at")
    if isinstance(created, datetime):
        created_text = created.strftime("%Y-%m-%d %H:%M")
    else:
        created_text = str(created or datetime.now().strftime("%Y-%m-%d %H:%M"))
    draw.text((82, 565), f"2026 莱莎采购节  ·  {created_text}",
              font=_font(24), fill=ink)

    token = _event_token(str(event["dedup_key"]))
    output = _UPLOAD_ROOT / "events" / f"{token}.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "PNG", optimize=True)
    return output


def _browser_executable() -> Path | PureWindowsPath:
    configured = get_settings().FESTIVAL_BROWSER_EXECUTABLE.strip()
    candidates = [Path(configured)] if configured and "edge" not in configured.lower() else []
    candidates.extend([
        PureWindowsPath("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        PureWindowsPath("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
    ])
    for path in candidates:
        probe = path if isinstance(path, Path) else Path(str(path))
        if probe.is_file():
            return path
    raise RuntimeError("采购节截图未找到 Google Chrome，请配置 FESTIVAL_BROWSER_EXECUTABLE")


def _screenshot_command(browser: Path, profile: str, output: Path, url: str) -> list[str]:
    """构造稳定帧截图命令：禁用动效，避免异步取数后截到 count-up 中间值。"""
    return [
        str(browser), "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--disable-crash-reporter", "--disable-extensions",
        "--no-first-run", f"--user-data-dir={profile}", "--window-size=1920,1080",
        "--force-prefers-reduced-motion", "--virtual-time-budget=6000",
        f"--screenshot={output}", url,
    ]


def _compress_board_screenshot(source: Path, output: Path) -> None:
    """把浏览器原始 1920×1080 PNG 转为适合钉钉查看的 1600×900 JPEG。"""
    with Image.open(source) as screenshot:
        screenshot = screenshot.convert("RGB")
        if screenshot.width > 1600:
            height = round(screenshot.height * 1600 / screenshot.width)
            screenshot = screenshot.resize((1600, height), Image.Resampling.LANCZOS)
        screenshot.save(
            output, "JPEG", quality=82, optimize=True, progressive=True, subsampling=0,
        )


def capture_board_screenshots(target_date: date) -> list[dict]:
    settings = get_settings()
    screen_key = (settings.FESTIVAL_SCREEN_KEYS or "").split(",")[0].strip()
    if not screen_key:
        raise RuntimeError("FESTIVAL_SCREEN_KEYS 未配置，无法拍摄受保护榜单")
    browser = _browser_executable()
    date_token = _event_token(f"daily:{target_date.isoformat()}")
    output_dir = _UPLOAD_ROOT / "daily" / date_token
    output_dir.mkdir(parents=True, exist_ok=True)
    result = []
    base_url = settings.FESTIVAL_SCREENSHOT_BASE_URL.rstrip("/")
    with httpx.Client(timeout=12, follow_redirects=True) as client:
        for title, page, _slug, endpoint in _BOARD_PAGES:
            query = {"key": screen_key, "stay": "1"}
            try:
                page_response = client.get(f"{base_url}/festival/{page}", params=query)
                api_response = client.get(
                    f"{base_url}/api/public/festival/{endpoint}", params={"key": screen_key},
                )
            except httpx.HTTPError:
                # 不把带访问 key 的完整 URL 写入任务日志或钉钉告警群。
                raise RuntimeError(f"{title}截图预检连接失败，请检查 FESTIVAL_SCREENSHOT_BASE_URL") from None
            try:
                payload = api_response.json()
            except ValueError:
                payload = None
            data = payload.get("data", payload) if isinstance(payload, dict) else None
            if (page_response.status_code != 200
                    or "/api/public/festival/" not in page_response.text
                    or api_response.status_code != 200
                    or not isinstance(data, dict)
                    or not data.get("as_of")):
                raise RuntimeError(
                    f"{title}截图预检失败（页面 {page_response.status_code} / "
                    f"数据 {api_response.status_code}），请检查截图入口与 FESTIVAL_SCREEN_KEYS"
                )
    for title, page, slug, _endpoint in _BOARD_PAGES:
        source = output_dir / f"{slug}-source.png"
        output = output_dir / f"{slug}.jpg"
        query = urlencode({"key": screen_key, "stay": "1", "popup": "0"})
        url = f"{base_url}/festival/{page}?{query}"
        with tempfile.TemporaryDirectory(prefix=f"ark-festival-{slug}-") as profile:
            try:
                proc = subprocess.run(
                    _screenshot_command(browser, profile, source, url),
                    capture_output=True, text=True, timeout=40,
                )
            except (OSError, subprocess.TimeoutExpired):
                # TimeoutExpired 会携带含 key 的完整命令，必须在进入任务日志前截断。
                raise RuntimeError(f"{title}截图进程失败，请检查浏览器安装与服务状态") from None
            if proc.returncode != 0 or not source.is_file() or source.stat().st_size < 10_000:
                raise RuntimeError(f"{title}截图失败（浏览器退出码 {proc.returncode}）")
        try:
            _compress_board_screenshot(source, output)
        finally:
            source.unlink(missing_ok=True)
        if not output.is_file() or output.stat().st_size < 10_000:
            raise RuntimeError(f"{title}截图压缩失败")
        result.append({"title": title, "path": output, "url": _public_url(output)})
    return result


def _event_dict(row: FestivalEvent) -> dict:
    from app.festival.events_service import EVENT_META
    return {
        "id": row.id,
        "event_type": row.event_type,
        "level": row.level,
        "label": EVENT_META.get(row.event_type, {}).get("label", row.event_type),
        "subject_type": row.subject_type,
        "subject_id": row.subject_id,
        "subject_name": row.subject_name,
        "amount": float(row.amount) if row.amount is not None else None,
        "detail": row.detail,
        "dedup_key": row.dedup_key,
        "created_at": row.created_at,
    }


def _detect_and_load_pending() -> list[dict]:
    now = datetime.now()
    stale = now - timedelta(minutes=15)
    with SessionLocal() as db:
        service.get_headline_payload(db, None, None)
        rows = (db.query(FestivalEvent)
                .filter(FestivalEvent.dingtalk_sent_at.is_(None))
                .filter(or_(FestivalEvent.dingtalk_next_retry_at.is_(None),
                            FestivalEvent.dingtalk_next_retry_at <= now))
                .filter(or_(FestivalEvent.dingtalk_claimed_at.is_(None),
                            FestivalEvent.dingtalk_claimed_at <= stale))
                .order_by(FestivalEvent.id.asc()).limit(30).all())
        return [_event_dict(row) for row in rows]


def _claim_event_delivery(event_id: int) -> bool:
    now = datetime.now()
    stale = now - timedelta(minutes=15)
    with SessionLocal() as db:
        updated = (db.query(FestivalEvent)
                   .filter(FestivalEvent.id == event_id)
                   .filter(FestivalEvent.dingtalk_sent_at.is_(None))
                   .filter(or_(FestivalEvent.dingtalk_next_retry_at.is_(None),
                               FestivalEvent.dingtalk_next_retry_at <= now))
                   .filter(or_(FestivalEvent.dingtalk_claimed_at.is_(None),
                               FestivalEvent.dingtalk_claimed_at <= stale))
                   .update({FestivalEvent.dingtalk_claimed_at: now},
                           synchronize_session=False))
        db.commit()
        return updated == 1


def _mark_event_delivery(event_id: int, error: str | None = None) -> None:
    with SessionLocal() as db:
        row = db.get(FestivalEvent, event_id)
        if not row:
            return
        row.dingtalk_attempts = int(row.dingtalk_attempts or 0) + 1
        row.dingtalk_claimed_at = None
        row.dingtalk_last_error = error[:500] if error else None
        if error is None:
            row.dingtalk_sent_at = datetime.now()
            row.dingtalk_next_retry_at = None
        else:
            delay_minutes = min(30, 2 ** min(row.dingtalk_attempts - 1, 5))
            row.dingtalk_next_retry_at = datetime.now() + timedelta(minutes=delay_minutes)
        db.commit()


def _festival_sender() -> WebhookSender | None:
    settings = get_settings()
    if not settings.FESTIVAL_DINGTALK_WEBHOOK_URL:
        return None
    return WebhookSender(
        webhook_url=settings.FESTIVAL_DINGTALK_WEBHOOK_URL,
        webhook_secret=settings.FESTIVAL_DINGTALK_WEBHOOK_SECRET,
    )


async def monitor_festival_events() -> dict:
    """每分钟检测事件并逐条投递；成功后才落 sent_at，失败自动留待下轮重试。"""
    pending = await anyio.to_thread.run_sync(_detect_and_load_pending)
    sender = _festival_sender()
    if sender is None:
        return {"pending": len(pending), "sent": 0, "disabled": True}
    sent = 0
    errors = []
    for event in pending:
        if not await anyio.to_thread.run_sync(_claim_event_delivery, event["id"]):
            continue
        try:
            image_path = await anyio.to_thread.run_sync(render_event_image, event)
            image_url = _public_url(image_path)
            text = (f"![{event['label']}]({image_url})\n\n"
                    f"**{event['subject_name']}** · {event.get('detail') or event['label']}")
            await sender.send_markdown(f"采购节 · {event['label']}", text)
            await anyio.to_thread.run_sync(_mark_event_delivery, event["id"], None)
            sent += 1
        except Exception as exc:
            if isinstance(exc, DingTalkWebhookError) and exc.delivery_uncertain:
                # 实测钉钉可能已把消息投递到群，却返回“系统繁忙”。此时自动重试会重复轰炸；
                # 按已投递收口并留警告日志，其他明确失败仍走退避重试。
                await anyio.to_thread.run_sync(_mark_event_delivery, event["id"], None)
                logger.warning("采购节事件钉钉响应不确定，按已投递收口 event=%s code=%s",
                               event["id"], exc.errcode)
                sent += 1
                continue
            error = str(exc)
            errors.append(f"event={event['id']} {error}")
            await anyio.to_thread.run_sync(_mark_event_delivery, event["id"], error)
            logger.exception("采购节事件钉钉投递失败 event=%s", event["id"])
            print(f"[festival] 钉钉投递失败 event={event['id']}: {error}", flush=True)
    if errors:
        raise RuntimeError("; ".join(errors))
    return {"pending": len(pending), "sent": sent, "disabled": False}


def _daily_claim(target_date: date) -> bool:
    key = f"delivery:daily:{target_date.isoformat()}"
    with SessionLocal() as db:
        try:
            db.add(FestivalState(
                state_key=key,
                value_json=json.dumps({"status": "sending", "claimed_at": datetime.now().isoformat()}),
            ))
            db.commit()
            return True
        except IntegrityError:
            db.rollback()
            row = db.get(FestivalState, key)
            if not row:
                return False
            claim = {}
            try:
                claim = json.loads(row.value_json)
                claimed_at = datetime.fromisoformat(claim.get("claimed_at", ""))
                if not isinstance(claim, dict):
                    raise ValueError("claim JSON must be an object")
            except (AttributeError, TypeError, ValueError):
                claim = {}
                claimed_at = datetime.min
            if claim.get("status") == "sent" or claimed_at > datetime.now() - timedelta(minutes=15):
                return False
            # 进程在发送中途退出时不会执行 _daily_finish；15 分钟后释放僵尸 claim。
            row.value_json = json.dumps({
                "status": "sending", "claimed_at": datetime.now().isoformat(),
            })
            db.commit()
            return True


def _daily_finish(target_date: date, success: bool) -> None:
    key = f"delivery:daily:{target_date.isoformat()}"
    with SessionLocal() as db:
        row = db.get(FestivalState, key)
        if not row:
            return
        if success:
            row.value_json = json.dumps({"status": "sent", "sent_at": datetime.now().isoformat()})
        else:
            db.delete(row)  # 释放 claim，下一分钟恢复任务可重试
        db.commit()


def _daily_target_date(now: datetime, allow_today: bool = False) -> date | None:
    """返回最早待补发日报日期；首次启用只从最近一个已到点日期建基线。"""
    latest_due = (now.date() if allow_today or now.time() >= dt_time(17, 30)
                  else now.date() - timedelta(days=1))
    activity_start = date.fromisoformat(service.ACTIVITY_GMV_WINDOW[0])
    activity_end = date.fromisoformat(service.ACTIVITY_GMV_WINDOW[1])
    if latest_due < activity_start:
        return None
    latest_due = min(latest_due, activity_end)
    baseline_key = "delivery:daily:baseline"
    with SessionLocal() as db:
        baseline = db.get(FestivalState, baseline_key)
        if baseline is None:
            # 首次启用从“启用当天”开始。上午启动不能把昨天误当成待补发历史；
            # 活动结束后首次启用也不补发已经收官的日报。
            if now.date() > activity_end:
                return None
            first_enabled_date = max(now.date(), activity_start)
            try:
                baseline = FestivalState(
                    state_key=baseline_key,
                    value_json=json.dumps({"start_date": first_enabled_date.isoformat()}),
                )
                db.add(baseline)
                db.commit()
            except IntegrityError:
                db.rollback()
                baseline = db.get(FestivalState, baseline_key)
        try:
            baseline_value = json.loads(baseline.value_json) if baseline else {}
            first_date = date.fromisoformat(baseline_value["start_date"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            # 损坏的基线不能触发历史倒灌，安全地从当前最近应发日期恢复。
            first_date = latest_due

        candidate = max(first_date, activity_start)
        while candidate <= latest_due:
            row = db.get(FestivalState, f"delivery:daily:{candidate.isoformat()}")
            status = None
            if row:
                try:
                    value = json.loads(row.value_json)
                    status = value.get("status") if isinstance(value, dict) else None
                except (TypeError, json.JSONDecodeError):
                    pass
            if status != "sent":
                return candidate
            candidate += timedelta(days=1)
    return None


def _daily_snapshot(target_date: date) -> dict:
    with SessionLocal() as db:
        headline = service.get_headline_payload(db, None, None)
        day = target_date.isoformat()
        return {
            "date": day,
            "as_of": headline["as_of"],
            "today_new": service.get_company_new_total(db, day, day),
            "today_gmv": service.get_gmv_total(db, day, day),
            "summary": headline["summary"],
            "sign_top3": headline["sign_top3"],
            "first_top2": headline["first_top2"],
            "amount_top2": headline["amount_top2"],
            "teams_top3": headline["teams_top3"],
        }


def build_daily_markdown(snapshot: dict, screenshots: list[dict]) -> str:
    summary = snapshot["summary"]
    sign = "、".join(f"{r['name']} {r['new_points']:g}分" for r in snapshot["sign_top3"]) or "暂无"
    first = "、".join(f"{r['name']} {r['first_count']}个" for r in snapshot["first_top2"]) or "暂无"
    repurchase = "、".join(f"{r['name']} ${r['re_amount']:,.0f}" for r in snapshot["amount_top2"]) or "暂无"
    teams = "、".join(f"{r['name']} {r['avg']:.1f}分" for r in snapshot["teams_top3"]) or "暂无"
    lines = [
        f"## 采购节每日战报 · {snapshot['date']}",
        f"> 数据截至 {snapshot['as_of']}",
        "",
        f"- 今日新签：**{snapshot['today_new']} 个**",
        f"- 今日 GMV：**${snapshot['today_gmv']:,.0f}**",
        f"- 公司新签：**{summary['new_total']}/{summary['new_target']}**",
        f"- 公司 GMV：**${summary['gmv_total']:,.0f}/${summary['gmv_target']:,.0f}**",
        f"- 新签前三：{sign}",
        f"- 首返前二：{first}",
        f"- 复购前二：{repurchase}",
        f"- 团队前三：{teams}",
    ]
    for shot in screenshots:
        lines.extend(["", f"### {shot['title']}", f"![{shot['title']}]({shot['url']})"])
    return "\n".join(lines)


async def send_daily_report_if_due(*, force: bool = False,
                                   now: datetime | None = None) -> dict:
    now = now or datetime.now()
    sender = _festival_sender()
    if sender is None:
        return {"sent": False, "reason": "disabled"}
    target_date = await anyio.to_thread.run_sync(_daily_target_date, now, force)
    if target_date is None:
        return {"sent": False, "reason": "not_due_or_complete"}
    if not await anyio.to_thread.run_sync(_daily_claim, target_date):
        return {"sent": False, "reason": "already_claimed"}
    try:
        snapshot = await anyio.to_thread.run_sync(_daily_snapshot, target_date)
        screenshots = await anyio.to_thread.run_sync(capture_board_screenshots, target_date)
        markdown = build_daily_markdown(snapshot, screenshots)
        await sender.send_markdown(f"采购节每日战报 · {target_date.isoformat()}", markdown)
        await anyio.to_thread.run_sync(_daily_finish, target_date, True)
        return {"sent": True, "screenshots": len(screenshots)}
    except DingTalkWebhookError as exc:
        if exc.delivery_uncertain:
            await anyio.to_thread.run_sync(_daily_finish, target_date, True)
            logger.warning("采购节日报钉钉响应不确定，按已投递收口 date=%s code=%s",
                           target_date, exc.errcode)
            return {
                "sent": True, "screenshots": len(screenshots),
                "delivery_uncertain": True,
            }
        await anyio.to_thread.run_sync(_daily_finish, target_date, False)
        raise
    except Exception:
        await anyio.to_thread.run_sync(_daily_finish, target_date, False)
        raise


async def monitor_festival_and_recover_daily() -> dict:
    """分钟任务：事件主链路 + 17:30 后日报失败/停机恢复。"""
    event_error = None
    try:
        result = await monitor_festival_events()
    except Exception as exc:
        # 事件消息失败不能阻断 17:30 日报恢复，两条投递链路独立推进。
        event_error = exc
        result = {"error": str(exc)}
    try:
        daily = await send_daily_report_if_due()
    except Exception as exc:
        if event_error:
            raise RuntimeError(f"事件投递失败: {event_error}; 日报投递失败: {exc}") from exc
        raise
    if event_error:
        raise event_error
    return {"events": result, "daily": daily}
