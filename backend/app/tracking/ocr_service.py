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

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{b64_image}"},
                },
                {"type": "text", "text": "请从以下运单图片中提取物流信息，严格按照 JSON 格式返回。"},
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

    # 提取 JSON
    json_str = _extract_json(text)
    logger.info("OCR extracted JSON preview=%s", json_str[:200])

    try:
        result = json.loads(json_str)
    except json.JSONDecodeError as exc:
        logger.error("OCR JSON 解析失败: %s | raw=%s", exc, text[:500])
        raise OCRParseError(f"AI 返回格式不是有效 JSON: {exc}", raw_text=text)

    # 标准化:确保返回 dict,且包含所需字段(缺失时为 None)
    return {
        "waybill_no": result.get("waybill_no"),
        "carrier": result.get("carrier"),
        "recipient_name": result.get("recipient_name"),
        "recipient_country": result.get("recipient_country"),
        "ship_date": result.get("ship_date"),
    }
