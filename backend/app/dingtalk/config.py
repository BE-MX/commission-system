"""钉钉配置管理 — 复用主 Settings"""

from app.core.config import get_settings


def get_dingtalk_settings():
    """返回主 Settings 实例（包含所有钉钉配置字段）"""
    return get_settings()
