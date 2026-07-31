"""Fail-fast checks for non-database runtime resources."""

import logging

from app.core.config import Settings
from app.invoice.pdf_font import validate_configured_cjk_font

logger = logging.getLogger("commission")


def check_pdf_export_resources(settings: Settings | None = None):
    return validate_configured_cjk_font(settings)


def check_expo_watermark() -> bool:
    """展会结果图水印 LOGO 是否就位。

    **刻意不 fail-fast**：LOGO 缺失只是图上少个角标，展位后端起不来才是灾难。
    但也不能沉默——缺失时的表现是「图正常出、就是没水印」，现场没人会察觉，
    所以启动期就把它喊出来，并直接给出补救动作。
    """
    from app.expo.ai_pipeline import LOGO_PATH

    if LOGO_PATH.exists():
        return True
    msg = (f"[expo] 品牌水印 LOGO 缺失：{LOGO_PATH} —— 效果图将不带水印。"
           f"该文件随代码库分发，请确认部署时已 git pull 到位")
    logger.warning(msg)
    print(msg, flush=True)
    return False
