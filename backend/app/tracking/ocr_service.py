"""运单 OCR — 多模态 AI 识别图片中的物流字段"""

import base64
import json
import logging

from app.ai.service import chat
from app.core.database import SessionLocal

logger = logging.getLogger("commission.tracking.ocr")


class OCRParseError(Exception):
    """OCR 结果解析异常,携带原始响应用于诊断。"""

    def __init__(self, message: str, raw_text: str = ""):
        self.raw_text = raw_text
        super().__init__(message)


def _extract_json(text: str) -> str:
    """从可能包含 markdown、说明文字等杂质的文本中提取最外层 JSON 对象。"""
    # 1. 去掉 markdown 代码块 (支持 ```json 等带语言标识的情况)
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # 去掉第一行(可能含语言标识)和最后的 ```
        lines = cleaned.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    # 2. 尝试找第一个 { 和最后一个 }
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return cleaned[start:end + 1]

    return cleaned


def call_ocr_sync(image_bytes: bytes, suffix: str) -> dict:
    """同步调用 AI OCR(在 run_in_executor 中执行)。

    注意:在线程池中运行,自己创建独立的数据库 Session。
    抛 OCRParseError 时调用方可拿 .raw_text 用于诊断。
    """
    b64_image = base64.b64encode(image_bytes).decode("utf-8")
    suffix_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    media_type = suffix_map.get(suffix.lower(), "image/jpeg")

    # 注意: call_service.py 会自动在 messages 前插入 preset 的 system_prompt,
    # 这里不再重复添加 system message,避免两个 system message 干扰模型。
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{b64_image}"},
                },
                {
                    "type": "text",
                    "text": (
                        "Extract shipping info from this waybill image. "
                        "Return ONLY a valid JSON object with these fields (use null if not found): "
                        '{"waybill_no": "运单号", "carrier": "承运商(DHL/FedEx/UPS/TNT/EMS/Aramex/其他)", '
                        '"recipient_name": "收件人姓名", "recipient_country": "目的国", '
                        '"ship_date": "发件日期(YYYY-MM-DD)"}. '
                        "No markdown, no explanation, no extra text — just the JSON object."
                    ),
                },
            ],
        }
    ]

    with SessionLocal() as db:
        try:
            resp = chat(db, "waybill_ocr", messages, "tracking")
        except ValueError as exc:
            # Preset 不存在等配置问题
            raise OCRParseError(f"AI 配置错误: {exc}")
        except Exception as exc:
            # 网络、API Key 错误等
            raise OCRParseError(f"AI 调用失败: {exc}")

    text = resp.get("content", "")
    logger.info("OCR raw response length=%s preview=%s", len(text), text[:200])

    # 空内容 — 通常意味着模型不支持多模态图片输入
    if not text or not text.strip():
        raise OCRParseError(
            "AI 返回内容为空，请检查 waybill_ocr 预设绑定的模型是否支持图片输入（多模态）。"
            "纯文本模型（如部分 MIMO/DeepSeek 模型）无法处理运单图片。",
            raw_text="",
        )

    # 提取 JSON
    json_str = _extract_json(text)
    logger.info("OCR extracted JSON preview=%s", json_str[:200])

    if not json_str.strip():
        raise OCRParseError(
            f"AI 返回内容中未找到 JSON 结构，原始响应: {text[:300]}",
            raw_text=text,
        )

    try:
        result = json.loads(json_str)
    except json.JSONDecodeError as exc:
        logger.error("OCR JSON 解析失败: %s | raw=%s", exc, text[:500])
        # 截取原始返回内容用于前端展示(限 200 字)
        preview = text[:200].replace("\n", " ")
        raise OCRParseError(
            f"AI 返回格式不是有效 JSON: {exc}。模型原始返回: {preview}",
            raw_text=text,
        )

    # 标准化:确保返回 dict,且包含所需字段(缺失时为 None)
    return {
        "waybill_no": result.get("waybill_no"),
        "carrier": result.get("carrier"),
        "recipient_name": result.get("recipient_name"),
        "recipient_country": result.get("recipient_country"),
        "ship_date": result.get("ship_date"),
    }
