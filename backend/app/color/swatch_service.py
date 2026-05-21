"""色板图生成服务 — 复用 AI 接入模块"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.color.calc_service import (
    DELTA_E_ACCEPTABLE,
    MAX_RETRIES,
    build_swatch_prompt,
    verify_swatch_color,
)
from app.color.models import ColorBlend, ColorPalette, ColorSwatchImage

logger = logging.getLogger("color.swatch")

# 存储路径
SWATCH_STORAGE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "uploads", "swatches")


def _ensure_dir():
    os.makedirs(SWATCH_STORAGE_DIR, exist_ok=True)


def get_swatch(db: Session, swatch_id: int) -> Optional[ColorSwatchImage]:
    return db.query(ColorSwatchImage).filter(ColorSwatchImage.id == swatch_id).first()


def list_swatches(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    palette_id: Optional[int] = None,
    blend_id: Optional[int] = None,
) -> dict:
    q = db.query(ColorSwatchImage)
    if status:
        q = q.filter(ColorSwatchImage.status == status)
    if palette_id:
        q = q.filter(ColorSwatchImage.palette_id == palette_id)
    if blend_id:
        q = q.filter(ColorSwatchImage.blend_id == blend_id)

    total = q.count()
    items = (
        q.order_by(ColorSwatchImage.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"total": total, "items": items}


def create_swatch_task(db: Session, data: dict) -> ColorSwatchImage:
    """创建色板图生成任务记录"""
    color_id = data.get("color_id")
    blend_id = data.get("blend_id")
    style = data.get("style", "swatch_card")

    # 确定目标色
    target_hex = None
    color_name = "Unknown"
    if color_id:
        palette = db.query(ColorPalette).filter(ColorPalette.id == color_id).first()
        if palette:
            target_hex = palette.hex_code
            color_name = palette.display_name
    elif blend_id:
        blend = db.query(ColorBlend).filter(ColorBlend.id == blend_id).first()
        if blend:
            target_hex = blend.computed_hex
            color_name = blend.display_name

    if not target_hex:
        raise HTTPException(status_code=400, detail="无法确定目标色号")

    prompt = build_swatch_prompt(target_hex, color_name, style)

    swatch = ColorSwatchImage(
        palette_id=color_id,
        blend_id=blend_id,
        prompt=prompt,
        model_used="gpt-image-2",  # Phase 1 默认
        image_path="",  # 生成后填充
        target_hex=target_hex,
        status="pending",
    )
    db.add(swatch)
    db.commit()
    db.refresh(swatch)
    return swatch


async def generate_swatch_image(
    db: Session,
    swatch_id: int,
    max_retries: int = MAX_RETRIES,
) -> ColorSwatchImage:
    """
    执行色板图生成（后台线程调用 AI）。
    生成 → 色差校验 → 不通过则重试（最多3次）。
    """
    swatch = get_swatch(db, swatch_id)
    if not swatch:
        raise HTTPException(status_code=404, detail="任务不存在")

    swatch.status = "generating"
    db.commit()

    try:
        # 调用 AI 生成图片
        # 注意：这里用 run_in_executor 在线程池执行，函数内自建 Session
        image_path = await _call_ai_image_generation(swatch)

        if not image_path or not os.path.exists(image_path):
            raise Exception("AI 图片生成失败")

        swatch.image_path = image_path
        swatch.image_url = f"/uploads/swatches/{os.path.basename(image_path)}"

        # 色差校验
        verify_result = verify_swatch_color(image_path, swatch.target_hex)
        swatch.actual_hex = verify_result["actual_hex"]
        swatch.delta_e = verify_result["delta_e"]
        swatch.pass_check = 1 if verify_result["pass_check"] else 0

        if verify_result["pass_check"]:
            swatch.status = "completed"
        elif swatch.retry_count < max_retries:
            swatch.retry_count += 1
            swatch.status = "pending"  # 标记为待重试
            # 触发重生成
            logger.info(f"Swatch {swatch_id} ΔE={verify_result['delta_e']} 未通过，第{swatch.retry_count}次重试")
            # 这里由调用方决定是否继续重试
        else:
            swatch.status = "rejected"
            logger.warning(f"Swatch {swatch_id} 超过最大重试次数，标记为 rejected")

        db.commit()
        return swatch

    except Exception as e:
        logger.exception(f"Swatch generation failed: {e}")
        swatch.status = "failed"
        db.commit()
        raise


async def _call_ai_image_generation(swatch: ColorSwatchImage) -> str:
    """
    调用 AI 生成图片。
    Phase 1: 使用 GPT-Image-2 (通过 app.ai.service.chat)。
    返回本地文件路径。
    """
    import time
    import uuid

    from app.ai.service import chat
    from app.core.database import SessionLocal

    _ensure_dir()

    # 由于 chat() 需要 db session，在线程内自建
    def _generate():
        db = SessionLocal()
        try:
            # 构建 messages（GPT-Image 格式）
            # 注意：不同 provider 的图片生成 API 不同
            # 这里假设通过预设的 AI Preset 调用
            result = chat(
                db=db,
                preset_name="swatch_image_generation",
                messages=[
                    {"role": "user", "content": swatch.prompt}
                ],
                caller_module="color",
            )
            # result 中应包含图片 URL 或 base64
            # 这里简化处理：返回图片内容
            content = result.get("content", "")
            # 实际实现需要根据 AI provider 的响应格式调整
            # 如果是 URL，下载保存；如果是 base64，解码保存
            return content
        finally:
            db.close()

    # 在线程池中执行
    loop = asyncio.get_event_loop()
    content = await loop.run_in_executor(None, _generate)

    # 保存图片（简化：假设 content 是图片二进制或 URL）
    # 实际实现需要根据 AI 响应格式调整
    filename = f"swatch_{swatch.id}_{uuid.uuid4().hex[:8]}_{int(time.time())}.png"
    filepath = os.path.join(SWATCH_STORAGE_DIR, filename)

    # TODO: 实际保存逻辑（下载URL或解码base64）
    # 这里先创建空文件占位
    with open(filepath, "wb") as f:
        f.write(b"")  # 占位

    return filepath


def batch_generate_swatch(
    db: Session,
    color_ids: list[int],
    style: str = "swatch_card",
) -> list[ColorSwatchImage]:
    """批量创建生成任务"""
    tasks = []
    for color_id in color_ids:
        task = create_swatch_task(db, {"color_id": color_id, "style": style})
        tasks.append(task)
    return tasks


def verify_swatch_task(db: Session, swatch_id: int) -> dict:
    """手动触发色差校验"""
    swatch = get_swatch(db, swatch_id)
    if not swatch:
        raise HTTPException(status_code=404, detail="任务不存在")

    if not swatch.image_path or not os.path.exists(swatch.image_path):
        raise HTTPException(status_code=400, detail="图片尚未生成")

    result = verify_swatch_color(swatch.image_path, swatch.target_hex)
    swatch.actual_hex = result["actual_hex"]
    swatch.delta_e = result["delta_e"]
    swatch.pass_check = 1 if result["pass_check"] else 0
    db.commit()

    return result
