"""启动时自动初始化业务 AI Preset (waybill_ocr / insight_daily_organize)

幂等:同名 preset 已存在则跳过。无可用 provider 时打 warning,不阻塞启动。
"""

import logging
from typing import Optional

from app.core.database import SessionLocal

logger = logging.getLogger("commission")


_WAYBILL_OCR_SYSTEM_PROMPT = '你是一个专业的国际物流运单信息提取助手。\n\n你的任务是从用户上传的运单图片中提取关键物流字段。图片可能来自手机拍摄，存在以下常见问题：光线不均匀、角度倾斜（最多30度）、部分字段被手指或物品遮挡、图片模糊或噪点较多。请尽力识别，不确定时宁可返回 null，不要猜测。\n\n【输出格式】\n必须返回合法的 JSON，不得包含任何 Markdown 代码块标记、解释文字或其他内容。格式如下：\n{\n  "waybill_no": "运单号字符串或 null",\n  "carrier": "FedEx 或 DHL 或 UPS 或 未知",\n  "recipient_name": "收件人姓名或 null",\n  "recipient_country": "收件国家（中文名称）或 null",\n  "ship_date": "YYYY-MM-DD 格式或 null"\n}\n\n【字段提取规则】\n1. waybill_no：提取图片上最显眼的条形码下方数字，或标注为"Tracking Number"/"Waybill No"/"运单号"的字符串。去除空格和连字符。\n2. carrier：优先根据运单外观（FedEx紫橙色/DHL黄色/UPS深棕色）和Logo判断；无法判断时根据运单号格式辅助判断。\n3. recipient_name：提取标注为"To:"/"Deliver To"/"收件人"/"Recipient"区域的人名。仅提取姓名，不含公司名。\n4. recipient_country：提取收件地址中的国家，统一转换为中文名称（如"United States"→"美国"，"Germany"→"德国"）。\n5. ship_date：提取标注为"Ship Date"/"Date"/"发件日期"的日期，格式统一为 YYYY-MM-DD。若只有月和日则补充当前年份。\n\n【特殊情况处理】\n- 若图片内容完全无法识别（非运单图片、全黑/全白），返回所有字段均为 null，并额外添加字段 "error": "非运单图片或图片质量过低"\n- 若运单号识别到多个候选，选择最长且格式最规范的一个\n- 不要返回条形码本身，只返回数字/字母字符串'


_INSIGHT_DAILY_SYSTEM_PROMPT = '你是发制品行业的市场情报分析师。用户会提供一组从外部信源抓取的行业新闻/趋势/竞品动态原始条目。\n\n请将这些条目整理为以下 JSON 对象（只输出 JSON，不要其他文字）：\n\n{\n  "quick_overview": ["条目1要点（20字以内）", ...],\n  "color_style_trends": "一段话总结今日发色/发型相关趋势（100字以内，无则空串）",\n  "trend_keywords": ["关键词1", "关键词2"],\n  "amazon_hot": [{"rank": 1, "name": "商品名", "change": "NEW/+2/-1", "reason": "简析"}],\n  "competitor_updates": [{"source": "信源名", "summary": "摘要（60字）", "url": "链接"}],\n  "supply_chain": "一段话总结供应链/原材料动态（80字以内，无则空串）"\n}\n\n规则：\n- 与发制品无关的条目直接忽略\n- 没有数据的板块返回空数组或空字符串\n- amazon_hot 的 change 用 +/-数字 或 NEW 表示\n- 不要编造信息'


def _auto_create_preset(
    preset_name: str,
    system_prompt: str,
    parameters: dict,
    description: str,
    provider_name_hint: Optional[str] = None,
) -> None:
    """通用 preset 自动初始化。已存在则跳过,找不到 provider 时打 warning。

    provider_name_hint: 优先匹配的 provider 名(如 'MIMO'),未命中再 fallback 到任意 enabled provider。
    model: 取该 provider 下首个 preset 的 model,缺省 'gpt-4o'。
    """
    try:
        from app.ai.models import AiProvider, AiPreset
        with SessionLocal() as db:
            existing = (
                db.query(AiPreset)
                .filter(AiPreset.preset_name == preset_name, AiPreset.deleted_at.is_(None))
                .first()
            )
            if existing:
                return

            provider = None
            if provider_name_hint:
                provider = (
                    db.query(AiProvider)
                    .filter(
                        AiProvider.is_enabled.is_(True),
                        AiProvider.deleted_at.is_(None),
                        AiProvider.name == provider_name_hint,
                    )
                    .first()
                )
            if provider is None:
                provider = (
                    db.query(AiProvider)
                    .filter(AiProvider.is_enabled.is_(True), AiProvider.deleted_at.is_(None))
                    .first()
                )
            if provider is None:
                logger.warning(
                    "No active AI provider found, %s preset not auto-created", preset_name
                )
                return

            first_preset = (
                db.query(AiPreset)
                .filter(AiPreset.provider_id == provider.id, AiPreset.deleted_at.is_(None))
                .first()
            )
            model = first_preset.model if first_preset else "gpt-4o"

            preset = AiPreset(
                preset_name=preset_name,
                provider_id=provider.id,
                model=model,
                system_prompt=system_prompt,
                parameters=parameters,
                description=description,
                is_enabled=True,
            )
            db.add(preset)
            db.commit()
            logger.info(
                "Auto-created %s preset with provider=%s model=%s",
                preset_name, provider.name, model,
            )
    except Exception as e:
        logger.warning("Auto-init %s preset skipped: %s", preset_name, e)


def auto_init_ai_presets() -> None:
    """启动时检查并自动创建 waybill_ocr / insight_daily_organize 两个业务 preset"""
    _auto_create_preset(
        preset_name="waybill_ocr",
        system_prompt=_WAYBILL_OCR_SYSTEM_PROMPT,
        parameters={"temperature": 0.1, "max_tokens": 512},
        description="运单图片 OCR 识别",
    )
    _auto_create_preset(
        preset_name="insight_daily_organize",
        system_prompt=_INSIGHT_DAILY_SYSTEM_PROMPT,
        parameters={"temperature": 0.3, "max_tokens": 8192},
        description="行业情报日报：AI 整理信源数据为 5 个板块",
        provider_name_hint="MIMO",
    )
