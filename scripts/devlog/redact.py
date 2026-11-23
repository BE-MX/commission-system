# scripts/devlog/redact.py
"""标题去敏：命中即打码。P0 只处理 commit 首行（项目约定英文意图描述）；人名/客户名词典在 P1。"""
import re
import hashlib

RULES = [
    (re.compile(r"(?i)\b(password|passwd|token|api[_-]?key|secret)\s*[:=]\s*[^\s,;]+"), "[密钥]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[邮箱]"),
    (re.compile(r"https?://\S+"), "[链接]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), "[密钥]"),
    (re.compile(r"\b[A-Za-z0-9_-]{32,}\b"), "[密钥]"),
    (re.compile(r"(?:\$|¥|￥|USD|CNY|RMB)\s?\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?\s?(?:USD|CNY|RMB|美元|元)"), "[金额]"),
    (re.compile(r"\+\d[\d -]{8,}\d|\b1[3-9]\d{9}\b"), "[号码]"),
    (re.compile(r"\b\d{6,}\b"), "[编号]"),
]
MAX_TITLE = 40


def safe_identifier(value: str, limit: int = 120) -> str:
    """Keep normal branch identifiers; hash unsafe/private refs instead of sending raw text."""
    if (len(value) <= limit and re.fullmatch(r"[A-Za-z0-9._/@+-]+", value)
            and not any(pattern.search(value) for pattern, _ in RULES)):
        return value
    return "private-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def redact_title(text: str) -> str:
    value = " ".join(text.split())
    for pattern, mask in RULES:
        value = pattern.sub(mask, value)
    if len(value) > MAX_TITLE:
        value = value[:MAX_TITLE - 1] + "…"
    return value or "未命名改动"
