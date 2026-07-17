"""培训速递 — AI 提炼：材料（粘贴文字 + 图片 + PDF）→ 结构化草稿

原则「宁缺毋滥」：材料撑不起的分区留空，让参训人口述补充，不许 AI 编。
「参训人点评」永不由 AI 生成。
JSON 健壮性三件套照 app/expo/ai_pipeline.py 同口径：
围栏清洗 → 502/503 快速重试（504/超时不重试）→ 解析失败纠错重试。
"""

import base64
import io
import json
import logging
import re
import time
from pathlib import Path

from sqlalchemy.orm import Session

from app.training import file_service
from app.training.models import TrainingDigest, TrainingDigestFile
from app.training.service import MAX_HIGHLIGHTS, MAX_SUMMARY_CHARS

logger = logging.getLogger("commission")

DRAFT_PRESET = "training_digest_draft"

MAX_IMAGES = 6
MAX_PDFS = 3
MAX_PDF_CHARS = 15000
MAX_LIST_ITEMS = 6

# 可应用点的岗位候选词表（AI 只许从中选，前端同一份）
ROLE_OPTIONS = ["业务/销售", "电商运营", "设计", "生产", "管理层", "AI/技术", "全员"]

_CHAT_RETRY_STATUS = {502, 503}
_CHAT_MAX_ATTEMPTS = 3


class DraftMaterialError(ValueError):
    """材料不足以起草时抛出（中文提示直达前端）。"""


def _parse_json(content: str) -> dict:
    text = (content or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise ValueError(f"AI 返回内容无法解析为 JSON: {text[:200]}")


def _chat_with_transient_retry(db: Session, preset_name: str, messages: list) -> dict:
    import urllib.error

    from app.ai.service import chat

    last_exc: Exception | None = None
    for attempt in range(1, _CHAT_MAX_ATTEMPTS + 1):
        try:
            return chat(db=db, preset_name=preset_name, messages=messages, caller_module="training")
        except urllib.error.HTTPError as exc:
            if exc.code not in _CHAT_RETRY_STATUS:
                raise
            last_exc = exc
        if attempt < _CHAT_MAX_ATTEMPTS:
            msg = f"[training] {preset_name} transient {getattr(last_exc, 'code', '?')}, retry {attempt}"
            logger.warning(msg)
            print(msg, flush=True)
            time.sleep(1.5 * attempt)
    raise last_exc


def _chat_json(db: Session, preset_name: str, messages: list, retries: int = 1) -> dict:
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        result = _chat_with_transient_retry(db, preset_name, messages)
        content = result.get("content", "")
        try:
            return _parse_json(content)
        except (ValueError, json.JSONDecodeError) as exc:
            last_exc = exc
            msg = f"[training] draft json parse failed attempt={attempt} err={exc}"
            logger.warning(msg)
            print(msg, flush=True)
            messages = messages + [
                {"role": "assistant", "content": content},
                {"role": "user", "content": (
                    f"你的输出不是合法 JSON（解析错误：{exc}）。请重新输出：只输出一个严格合法的 "
                    "JSON 对象，不要任何解释文字或代码围栏；字符串值内部禁止英文双引号，"
                    "需要引用时用中文引号「」。"
                )},
            ]
    raise ValueError(f"AI 草稿 JSON 解析重试后仍失败: {last_exc}")


def _prep_image_bytes(path: Path) -> tuple[bytes, str]:
    """送模型前压缩：最长边 1280 + JPEG q85；失败回退原始字节（与 expo 口径一致）。"""
    raw = path.read_bytes()
    try:
        from PIL import Image

        im = Image.open(io.BytesIO(raw))
        im = im.convert("RGB")
        im.thumbnail((1280, 1280))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        return buf.getvalue(), "image/jpeg"
    except Exception:  # noqa: BLE001
        suffix = path.suffix.lower()
        ct = "image/jpeg" if suffix in (".jpg", ".jpeg") else f"image/{suffix.lstrip('.') or 'png'}"
        return raw, ct


def _extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        chunks: list[str] = []
        total = 0
        for pg in reader.pages:
            t = (pg.extract_text() or "").strip()
            if not t:
                continue
            chunks.append(t)
            total += len(t)
            if total >= MAX_PDF_CHARS:
                break
        return "\n".join(chunks)[:MAX_PDF_CHARS]
    except Exception as e:  # noqa: BLE001
        logger.warning("training pdf extract failed %s: %s", path.name, e)
        print(f"[training] pdf extract failed {path.name}: {e}", flush=True)
        return ""


def _collect_materials(db: Session, digest: TrainingDigest, text_materials: str) -> tuple[str, list[Path]]:
    files = (
        db.query(TrainingDigestFile)
        .filter(TrainingDigestFile.digest_id == digest.id)
        .order_by(TrainingDigestFile.id)
        .all()
    )
    image_paths: list[Path] = []
    pdf_blocks: list[str] = []
    for f in files:
        ext = Path(f.file_name).suffix.lower()
        try:
            abs_path = file_service.resolve_private_path(f.storage_path)
        except file_service.FileValidationError:
            continue
        if not abs_path.is_file():
            continue
        if ext in file_service.IMAGE_EXTS and len(image_paths) < MAX_IMAGES:
            image_paths.append(abs_path)
        elif ext in file_service.PDF_EXTS and len(pdf_blocks) < MAX_PDFS:
            text = _extract_pdf_text(abs_path)
            if text:
                pdf_blocks.append(f"【PDF 材料：{f.file_name}】\n{text}")

    parts: list[str] = []
    pasted = (text_materials or "").strip()
    if pasted:
        parts.append(f"【参训人粘贴的文字材料】\n{pasted}")
    parts.extend(pdf_blocks)
    return "\n\n".join(parts), image_paths


def generate_draft(db: Session, digest: TrainingDigest, text_materials: str) -> dict:
    """返回草稿 dict：{summary, highlights, new_insights, applications, methods}。不含 review。"""
    material_text, image_paths = _collect_materials(db, digest, text_materials)
    if not material_text and not image_paths:
        raise DraftMaterialError("没有可提炼的材料：请先粘贴文字笔记，或上传现场照片 / PDF 资料")

    meta = (
        f"培训名称：{digest.title}\n"
        f"主办机构：{digest.org or '未知'}\n"
        f"讲师：{digest.lecturer or '未知'}\n"
        f"培训日期：{digest.trained_at}\n"
        f"标签：{'、'.join(digest.tags_json or []) or '无'}"
    )
    prompt = f"【培训基本信息】\n{meta}\n\n{material_text or '（无文字材料，仅有现场照片，请从照片中的 PPT/板书提取信息）'}"

    if image_paths:
        content: list[dict] = [{"type": "text", "text": prompt}]
        for p in image_paths:
            data, ct = _prep_image_bytes(p)
            b64 = base64.b64encode(data).decode()
            content.append({"type": "image_url", "image_url": {"url": f"data:{ct};base64,{b64}"}})
        messages = [{"role": "user", "content": content}]
    else:
        messages = [{"role": "user", "content": prompt}]

    parsed = _chat_json(db, DRAFT_PRESET, messages, retries=1)
    return _sanitize_draft(parsed)


def _s(v, limit: int = 500) -> str:
    return str(v).strip()[:limit] if isinstance(v, (str, int, float)) else ""


def _sanitize_draft(parsed: dict) -> dict:
    """AI 返回的结构化字段不能直接信任（cerebrum 2026-06-11）：clamp 形状、裁长度、滤空条目。"""
    # 先过滤脏条目再截断，AI 噪音不许吃掉有效名额
    highlights = []
    for item in parsed.get("highlights") or []:
        if not isinstance(item, dict):
            continue
        title = _s(item.get("title"), 100)
        if title:
            highlights.append({"title": title, "detail": _s(item.get("detail"), 800)})
    highlights = highlights[:MAX_HIGHLIGHTS]

    new_insights = [_s(x, 300) for x in (parsed.get("new_insights") or []) if _s(x)][:MAX_LIST_ITEMS]

    applications = []
    for item in parsed.get("applications") or []:
        if not isinstance(item, dict):
            continue
        point = _s(item.get("point"), 300)
        if not point:
            continue
        roles = [r for r in (item.get("roles") or []) if isinstance(r, str) and r in ROLE_OPTIONS]
        applications.append({"point": point, "roles": roles, "first_step": _s(item.get("first_step"), 300)})
    applications = applications[:MAX_LIST_ITEMS]

    methods = []
    for item in parsed.get("methods") or []:
        if not isinstance(item, dict):
            continue
        name = _s(item.get("name"), 100)
        if name:
            methods.append({"name": name, "steps": _s(item.get("steps"), 800)})
    methods = methods[:MAX_LIST_ITEMS]

    return {
        "summary": _s(parsed.get("summary"), MAX_SUMMARY_CHARS),
        "highlights": highlights,
        "new_insights": new_insights,
        "applications": applications,
        "methods": methods,
    }
