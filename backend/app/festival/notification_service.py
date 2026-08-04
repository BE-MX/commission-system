"""采购节事件图片、榜单截图与钉钉群可靠投递。"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import subprocess
import tempfile
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from urllib.parse import urlencode

import anyio
import httpx
from PIL import Image, ImageDraw, ImageFont, ImageOps
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.dingtalk.webhook import WebhookSender
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
    level = str(event.get("level") or "L3")
    image = Image.new("RGB", (width, height), "#100B14")
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / height
        start = (34, 12, 25) if level == "L4" else (15, 20, 43)
        end = (9, 8, 20)
        color = tuple(round(start[i] * (1 - ratio) + end[i] * ratio) for i in range(3))
        draw.line((0, y, width, y), fill=color)

    accent = "#FFBE3B" if level == "L4" else "#47D7FF"
    draw.rounded_rectangle((44, 38, width - 44, height - 38), radius=34,
                           fill="#171421", outline=accent, width=3)
    draw.rounded_rectangle((78, 70, 350, 122), radius=26, fill=accent)
    draw.ellipse((105, 91, 119, 105), fill="#171421")
    draw.text((132, 80), str(event.get("label") or "高光事件"),
              font=_font(25, bold=True), fill="#171421")

    subject_name = str(event.get("subject_name") or "")
    avatar_path = (_REPO_ROOT / "frontend" / "public" / "festival" / "assets" /
                   "avatars" / f"{event.get('subject_id')}.png")
    text_x = 118
    if event.get("subject_type") == "person" and avatar_path.is_file():
        avatar = Image.open(avatar_path).convert("RGB")
        avatar = ImageOps.fit(avatar, (150, 150))
        mask = Image.new("L", (150, 150), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 149, 149), fill=255)
        image.paste(avatar, (82, 176), mask)
        draw.ellipse((78, 172, 236, 330), outline=accent, width=5)
        text_x = 278

    name_font = _font(68, bold=True)
    draw.text((text_x, 176), subject_name, font=name_font, fill="#FFF8E8")
    detail = str(event.get("detail") or "")
    detail_font = _font(34)
    for idx, line in enumerate(_wrap(draw, detail, detail_font, width - text_x - 100)):
        draw.text((text_x, 275 + idx * 52), line, font=detail_font, fill="#D8D2DD")

    amount = event.get("amount")
    if amount:
        draw.text((82, 445), f"${float(amount):,.0f}", font=_font(66, bold=True), fill=accent)
    created = event.get("created_at")
    if isinstance(created, datetime):
        created_text = created.strftime("%Y-%m-%d %H:%M")
    else:
        created_text = str(created or datetime.now().strftime("%Y-%m-%d %H:%M"))
    draw.text((82, 565), f"2026 莱莎采购节  ·  {created_text}",
              font=_font(24), fill="#938C9B")
    draw.text((width - 215, 565), level, font=_font(28, bold=True), fill=accent)

    token = _event_token(str(event["dedup_key"]))
    output = _UPLOAD_ROOT / "events" / f"{token}.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "PNG", optimize=True)
    return output


def _browser_executable() -> Path:
    configured = get_settings().FESTIVAL_BROWSER_EXECUTABLE.strip()
    candidates = [Path(configured)] if configured else []
    candidates.extend([
        Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
        Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
    ])
    for path in candidates:
        if path.is_file():
            return path
    raise RuntimeError("采购节截图未找到 Edge/Chrome，请配置 FESTIVAL_BROWSER_EXECUTABLE")


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
    with tempfile.TemporaryDirectory(prefix="ark-festival-browser-") as profile:
        for title, page, slug, _endpoint in _BOARD_PAGES:
            output = output_dir / f"{slug}.png"
            query = urlencode({"key": screen_key, "stay": "1"})
            url = f"{base_url}/festival/{page}?{query}"
            try:
                proc = subprocess.run([
                    str(browser), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--no-first-run", f"--user-data-dir={profile}", "--window-size=1920,1080",
                    "--virtual-time-budget=6000", f"--screenshot={output}", url,
                ], capture_output=True, text=True, timeout=40)
            except (OSError, subprocess.TimeoutExpired):
                # TimeoutExpired 会携带含 key 的完整命令，必须在进入任务日志前截断。
                raise RuntimeError(f"{title}截图进程失败，请检查浏览器安装与服务状态") from None
            if proc.returncode != 0 or not output.is_file() or output.stat().st_size < 10_000:
                raise RuntimeError(f"{title}截图失败（浏览器退出码 {proc.returncode}）")
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
    target_date = now.date()
    if not force and now.time() < dt_time(17, 30):
        return {"sent": False, "reason": "not_due"}
    sender = _festival_sender()
    if sender is None:
        return {"sent": False, "reason": "disabled"}
    if not await anyio.to_thread.run_sync(_daily_claim, target_date):
        return {"sent": False, "reason": "already_claimed"}
    try:
        snapshot = await anyio.to_thread.run_sync(_daily_snapshot, target_date)
        screenshots = await anyio.to_thread.run_sync(capture_board_screenshots, target_date)
        markdown = build_daily_markdown(snapshot, screenshots)
        await sender.send_markdown(f"采购节每日战报 · {target_date.isoformat()}", markdown)
        await anyio.to_thread.run_sync(_daily_finish, target_date, True)
        return {"sent": True, "screenshots": len(screenshots)}
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
