"""Configured CJK font loading and startup/deploy preflight for invoice PDFs."""

import logging
from pathlib import Path

from PIL import ImageFont

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)
_CJK_PROBE = "魔术贴"


def load_configured_cjk_font(path_value: str, size: int):
    path = Path(path_value).expanduser()
    if not path.is_file():
        raise RuntimeError(
            f"PDF_CJK_FONT_PATH 指向的字体不存在: {path}；"
            "请在 backend/.env 配置现有的中文 .ttf/.ttc 字体后重启"
        )
    try:
        font = ImageFont.truetype(str(path), size)
    except OSError as exc:
        message = (
            f"PDF_CJK_FONT_PATH 无法加载为字体: {path}；"
            "请改为有效的中文 .ttf/.ttc 文件"
        )
        logger.warning("%s: %s", message, exc)
        print(f"[invoice] {message}: {exc}", flush=True)
        raise RuntimeError(message) from exc

    glyphs = {
        (font.getbbox(char), bytes(font.getmask(char)))
        for char in _CJK_PROBE
    }
    if len(glyphs) != len(_CJK_PROBE):
        raise RuntimeError(
            f"PDF_CJK_FONT_PATH 字体不包含完整中文字符({_CJK_PROBE}): {path}；"
            "请配置微软雅黑、思源黑体等完整中文字体"
        )
    return font


def validate_configured_cjk_font(settings: Settings | None = None) -> Path:
    current = settings or get_settings()
    path = Path(current.PDF_CJK_FONT_PATH).expanduser()
    load_configured_cjk_font(str(path), 36)
    return path


def main() -> int:
    path = validate_configured_cjk_font()
    print(f"invoice PDF CJK font OK: {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
