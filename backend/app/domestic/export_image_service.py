"""Embed private domestic reference images inside their own worksheet cells."""

from io import BytesIO
import logging
from math import ceil
from unicodedata import east_asian_width

from openpyxl.drawing.image import Image as SheetImage
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, OneCellAnchor
from openpyxl.drawing.xdr import XDRPositiveSize2D
from openpyxl.styles import Alignment
from openpyxl.utils.units import pixels_to_EMU
from PIL import Image, ImageOps, UnidentifiedImageError

from app.domestic import file_service


logger = logging.getLogger(__name__)


def wrapped_text_lines(text, width: float) -> list[str]:
    """Conservative wrapping for 11pt Songti; CJK occupies two column units."""
    capacity = max(4, int(width * 0.85))
    lines = []
    for paragraph in str(text or "").splitlines() or [""]:
        line, units = "", 0
        for char in paragraph:
            size = 2 if east_asian_width(char) in ("W", "F") else 1
            if line and units + size > capacity:
                lines.append(line)
                line, units = "", 0
            line += char
            units += size
        lines.append(line)
    return lines


def needs_image_appendix(text, width: float) -> bool:
    return len(str(text or "")) > 80 or len(wrapped_text_lines(text, width)) > 4


def add_cell_images(ws, row: int, col: int, paths: list[str], width: float) -> None:
    """Fit all supplied images into a bounded grid below the cell's text.

    Excel drawings are anchored to the cell and sized within it; missing or
    invalid files are called out on the exported sheet rather than omitted.
    """
    if not paths:
        return
    images = []
    missing = 0
    for path in paths:
        try:
            source = file_service.resolve_path(path)
            with Image.open(source) as image:
                oriented = ImageOps.exif_transpose(image)
                oriented.thumbnail((720, 720))
                stream = BytesIO()
                oriented.convert("RGB").save(stream, format="PNG")
            stream.seek(0)
            images.append(SheetImage(stream))
        except (OSError, ValueError, TypeError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
            missing += 1
            message = f"Domestic export image unavailable at row {row}, column {col}: {type(exc).__name__}"
            logger.warning(message)
            print(message, flush=True)

    cell = ws.cell(row, col)
    text = str(cell.value or "")
    if needs_image_appendix(text, width):
        text = "\n".join(wrapped_text_lines(text, width)[:2]) + "\n全文见完整要求"
    if missing:
        text += f"\n{missing} 张参考图不可用，请核对原订单"
    cell.value = text or None
    cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
    if not images:
        return

    gap = 5
    cell_width = width * 7 + 5
    columns = 1 if len(images) == 1 else 2
    rows = ceil(len(images) / columns)
    text_height = len(wrapped_text_lines(text, width)) * 19 + gap if text else gap
    box_width = (cell_width - gap * (columns + 1)) / columns
    box_height = min(155, (530 - text_height - gap * (rows + 1)) / rows)
    for index, image in enumerate(images):
        scale = min(box_width / image.width, box_height / image.height, 1)
        image.width, image.height = image.width * scale, image.height * scale
        x = gap + (index % columns) * (box_width + gap) + (box_width - image.width) / 2
        y = text_height + (index // columns) * (box_height + gap)
        image.anchor = OneCellAnchor(
            _from=AnchorMarker(col=col - 1, row=row - 1, colOff=pixels_to_EMU(x), rowOff=pixels_to_EMU(y)),
            ext=XDRPositiveSize2D(pixels_to_EMU(image.width), pixels_to_EMU(image.height)),
        )
        ws.add_image(image)
    needed_points = (text_height + rows * (box_height + gap) + gap) * 0.75
    ws.row_dimensions[row].height = min(409, max(ws.row_dimensions[row].height or 75, needed_points))
