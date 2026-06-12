"""运单 OCR — 多模态 AI 识别图片中的物流字段"""

import base64
import json
import logging
import re

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


def _clean_ocr_value(value: str | None) -> str | None:
    """清洗 OCR 返回的字段值，去除模型夹带的引号、markdown、解释性尾缀。

    典型问题：
      - `"ALISHA HAYES"` → `ALISHA HAYES`（去引号）
      - `name**: "ALISHA HAYES" is clearly visible under "TO"` → `ALISHA HAYES`
      - `ALISHA HAYES"` → `ALISHA HAYES`（孤立尾部引号）
    """
    if not value or not isinstance(value, str):
        return value

    s = value.strip()

    # 去掉 markdown bold 标记
    s = re.sub(r"\*{1,2}", "", s)

    # 去掉成对引号包裹：如果整段文字被引号包裹，去掉外层引号
    # 支持递归去除多层引号，如 '"ALISHA HAYES"' → ALISHA HAYES
    while True:
        stripped = s
        for q in ['"', '“”', '‘’', "'", '"', "'"]:
            if len(q) == 2 and stripped.startswith(q[0]) and stripped.endswith(q[1]) and len(stripped) > 2:
                stripped = stripped[1:-1].strip()
                break
            elif q in ('"', "'") and stripped.startswith(q) and stripped.endswith(q) and len(stripped) > 2:
                stripped = stripped[1:-1].strip()
                break
        else:
            break
        s = stripped

    # 如果含引号包裹的名字片段，提取引号内容（如 name**: "ALISHA HAYES" is ...）
    m = re.search(r'["“]([^"”]{2,})["”]', s)
    if m:
        return m.group(1).strip()

    # 去掉末尾的解释性文本
    # 英文尾缀：如 "is clearly visible", "found in", "labeled as" 等
    s = re.sub(
        r"\s+(?:is|was|found|seen|visible|labeled|located|printed|shown|written|displayed)\b.*$",
        "",
        s,
        flags=re.IGNORECASE,
    )
    # 中文解释尾缀：如 `" - 这是收件人姓名"`、`（承运商）`、`——目的国` 等
    s = re.sub(
        r'[\s]*["""]?\s*[-—]\s+这是.{1,20}$',
        "",
        s,
    )
    s = re.sub(
        r'[\s]*["""]?\s*[（(].{1,20}[）)]$',
        "",
        s,
    )

    # 去掉残留标点和孤立引号
    s = s.strip(' *:：,;“”‘’「」"\'')
    # 去掉首尾孤立的引号字符（不成对的）
    s = re.sub(r'^["“”‘’\']+', '', s)
    s = re.sub(r'["“”‘’\']+$', '', s)
    s = s.strip()

    return s if len(s) >= 2 else value


_COUNTRY_MAP = {
    "united states": "美国", "usa": "美国", "us": "美国",
    "united kingdom": "英国", "uk": "英国", "england": "英国",
    "germany": "德国", "deutschland": "德国",
    "france": "法国", "australia": "澳大利亚",
    "canada": "加拿大", "japan": "日本", "korea": "韩国",
    "brazil": "巴西", "india": "印度", "mexico": "墨西哥",
    "italy": "意大利", "spain": "西班牙", "netherlands": "荷兰",
    "turkey": "土耳其", "saudi arabia": "沙特阿拉伯",
    "uae": "阿联酋", "united arab emirates": "阿联酋",
    "south africa": "南非", "russia": "俄罗斯",
    "thailand": "泰国", "vietnam": "越南", "malaysia": "马来西亚",
    "singapore": "新加坡", "philippines": "菲律宾",
    "indonesia": "印度尼西亚", "poland": "波兰",
    "sweden": "瑞典", "norway": "挪威", "denmark": "丹麦",
    "finland": "芬兰", "switzerland": "瑞士", "austria": "奥地利",
    "belgium": "比利时", "portugal": "葡萄牙", "ireland": "爱尔兰",
    "new zealand": "新西兰", "argentina": "阿根廷", "chile": "智利",
    "colombia": "哥伦比亚", "peru": "秘鲁", "egypt": "埃及",
    "nigeria": "尼日利亚", "kenya": "肯尼亚",
}


def _parse_reasoning_to_dict(text: str) -> dict | None:
    """从推理模型的 reasoning 自然语言中提取运单字段。

    reasoning 模型 (Step-3.7-flash / DeepSeek-R1 等) 会在 reasoning 字段中
    以自然语言列出识别结果，如：
      - 承运商是 FedEx
      - 收件人是 ALISHA HAYES
      - 国家是 United States，转换为中文是 "美国"
      - 应该是 2026-06-04
    """
    result = {
        "waybill_no": None,
        "carrier": None,
        "recipient_name": None,
        "recipient_country": None,
        "ship_date": None,
    }

    # 运单号: TRK# 后的数字 / 条形码下方数字
    m = re.search(r"TRK[#\s\n]*(\d[\d\s]{8,})", text)
    if m:
        result["waybill_no"] = m.group(1).replace(" ", "")
    if not result["waybill_no"]:
        m = re.search(r"运单号[：:]\s*(\w[\w\s-]{8,})", text)
        if m:
            result["waybill_no"] = m.group(1).replace(" ", "").replace("-", "")
    if not result["waybill_no"]:
        # 兜底: 12位纯数字序列 (常见运单号长度)
        m = re.search(r"(?<!\d)(\d{10,14})(?!\d)", text)
        if m:
            result["waybill_no"] = m.group(1)

    # 承运商
    carriers = {"fedex": "FedEx", "dhl": "DHL", "ups": "UPS", "tnt": "TNT",
                "aramex": "Aramex", "ems": "EMS", "usps": "USPS", "sf": "顺丰"}
    text_lower = text.lower()
    for key, name in carriers.items():
        if key in text_lower:
            result["carrier"] = name
            break

    # 收件人: "TO XXX" / "SHIP TO: XXX" / "Consignee: XXX" / "ATTN: XXX" / "收件人是 XXX"
    # 匹配英文名（含大小写混合、公司后缀如 LLC/LTD/INC、逗号分隔的公司名）或中文名
    _name_patterns = [
        # 优先匹配明确标签 (ATTN/CONSIGNEE 等),最后才是通用 TO
        r"(?:ATTN|ATTENTION)[:\s]+(.+?)(?:\n|\s+\d{3,}|\s+\d+\s+[A-Za-z])",
        r"(?:CONSIGNEE|RECIPIENT|DELIVER\s+TO)[:\s]+(.+?)(?:\n|\s+\d{3,}|\s+\d+\s+[A-Za-z])",
        r"(?:SHIP\s+)?TO[:\s]+(.+?)(?:\n|\s+\d{3,}|\s+\d+\s+[A-Za-z])",
        r"收件人[是：:]\s*(.+?)(?:\n|，)",
    ]
    for pat in _name_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            name = m.group(1).strip()
            # 去掉末尾可能误捕的标点和多余空格
            name = re.sub(r"[.,;:\-\s]+$", "", name)
            if len(name) >= 2:
                result["recipient_name"] = name
                break

    # 目的国: 先匹配 "转换为中文是 XXX" 的显式声明,再按国家名字典匹配
    m = re.search(r"转换为中文是\s*[\"']?(\S+?)[\"']?(?:\s|$|。|,|，)", text)
    if m:
        result["recipient_country"] = m.group(1).strip()
    if not result["recipient_country"]:
        # 按长度降序匹配,避免 "united states" 被 "united" 截断
        for eng, chn in sorted(_COUNTRY_MAP.items(), key=lambda x: -len(x[0])):
            if eng in text_lower:
                result["recipient_country"] = chn
                break

    # 发件日期: YYYY-MM-DD 格式
    m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        result["ship_date"] = m.group(1)

    # 清洗收件人姓名（推理模型也可能夹带解释文本）
    result["recipient_name"] = _clean_ocr_value(result["recipient_name"])

    # 只要至少识别出运单号或承运商就算有效
    if result["waybill_no"] or result["carrier"]:
        return result
    return None


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
                        "CRITICAL: each value must be the RAW data only — no quotes wrapping, "
                        "no explanatory text, no markdown. For example: "
                        '\"recipient_name\": \"JOHN DOE\" not \"recipient_name\": \"the name JOHN DOE is visible under TO\". '
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

    result = None

    # 尝试 JSON 解析
    if json_str.strip():
        try:
            result = json.loads(json_str)
        except json.JSONDecodeError as exc:
            logger.warning("OCR JSON 解析失败: %s", exc)

    # JSON 解析失败 — 尝试从推理模型 reasoning 文本中提取
    if result is None:
        result = _parse_reasoning_to_dict(text)
        if result:
            logger.info("OCR fallback: extracted from reasoning text")
            print(f"[OCR] reasoning fallback extracted: {result}", flush=True)

    if result is None:
        preview = text[:200].replace("\n", " ")
        raise OCRParseError(
            f"AI 返回内容中未找到运单信息。模型原始返回: {preview}",
            raw_text=text,
        )

    # 标准化:确保返回 dict,且包含所需字段(缺失时为 None)
    return {
        "waybill_no": result.get("waybill_no"),
        "carrier": result.get("carrier"),
        "recipient_name": _clean_ocr_value(result.get("recipient_name")),
        "recipient_country": result.get("recipient_country"),
        "ship_date": result.get("ship_date"),
    }
