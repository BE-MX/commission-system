"""内贸订单 Excel 导出。"""

from datetime import date, datetime
from io import BytesIO
from itertools import zip_longest

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.page import PageMargins

from app.domestic.constants import PRODUCT_TYPES
from app.domestic.balance_service import money
from app.domestic.export_image_service import add_cell_images, text_column_width, wrapped_text_lines


# Business rows group the repeated product attributes into one readable cell,
# leaving enough A4 print width for prices and the original reference images.
_BUSINESS_COLUMNS = (
    ("line_code", "明细号", 6), ("product_type", "产品类型", 8), ("specification", "产品规格", 22),
    ("order_qty", "数量", 6), ("issued_qty", "出库数量", 7),
    ("original_price", "原价（元/件）", 9), ("discount_amount", "优惠金额（元/件）", 9),
    ("discount_price", "优惠后单价（元/件）", 10), ("labor_fee", "手工费（元/件）", 8),
    ("line_amount", "小计（元）", 11), ("hairstyle", "发型备注", 21),
    ("color", "颜色", 12), ("style_requirement", "发型要求", 23), ("remark", "备注", 16),
)
_PRODUCTION_COLUMNS = (
    ("line_code", "明细号", 9), ("product_type", "产品类型", 11), ("product_name", "产品名称", 24),
    ("craft", "工艺/尺寸", 15), ("length", "发长", 12), ("net_color", "网帽颜色", 14),
    ("size", "头套尺寸", 12), ("density", "发量", 11),
    ("order_qty", "数量", 10), ("issued_qty", "出库数量", 10), ("color", "颜色", 18), ("remark", "备注", 22),
)
_IMAGE_FIELDS = {"hairstyle": "hairstyle_images", "color": "color_images",
                 "style_requirement": "style_images", "remark": "remark_images"}
_MONEY_FIELDS = {"original_price", "discount_amount", "discount_price", "labor_fee", "line_amount"}
_FONT_NAME = "宋体"
_THIN = Side(style="thin", color="000000")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_MIN_TEXT_WIDTHS = {
    "specification": 17, "product_name": 16, "craft": 11, "length": 10, "net_color": 11,
    "size": 10, "density": 9, "hairstyle": 11, "color": 10, "style_requirement": 13, "remark": 16,
}
_MAX_TEXT_WIDTH = 52
# Keep rows below Excel's 409pt limit and allow those with images to reserve space for thumbnails.
_MAX_ROW_TEXT_LINES = 20
_MAX_TEXT_LINES_WITH_IMAGES = 14


def _safe_text(value) -> str:
    text = "" if value is None else str(value).strip()
    if text.startswith(("=", "+", "-", "@")):
        return f"'{text}"
    return text


def _display(value) -> str:
    return _safe_text(value) or "—"


def _date_text(value) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return _safe_text(value)
    if isinstance(value, datetime):
        return value.strftime("%Y/%m/%d")
    if isinstance(value, date):
        return value.strftime("%Y/%m/%d")
    return _safe_text(value)


def _wrapped_lines(value, width: int) -> int:
    return len(wrapped_text_lines(value, width))


def _text_chunks(text: str, width: float) -> list[str]:
    lines = wrapped_text_lines(text, width)
    if len(lines) > 1 and not lines[-1]:
        lines.pop()
    # Join the estimated lines without adding breaks. Excel wraps the original text.
    return [
        "".join(lines[start:start + _MAX_ROW_TEXT_LINES])
        for start in range(0, len(lines), _MAX_ROW_TEXT_LINES)
    ]


def _fit_columns(columns: tuple, item_values: list[dict]) -> tuple:
    """Reallocate spare text column width within the sheet's existing print width."""
    adjustments = []
    for key, label, width in columns:
        if key not in _MIN_TEXT_WIDTHS:
            adjustments.append(0)
            continue
        content_width = max((text_column_width(values.get(key)) for values in item_values), default=0)
        preferred = min(_MAX_TEXT_WIDTH, max(_MIN_TEXT_WIDTHS[key], text_column_width(label), content_width))
        adjustments.append(preferred - width)
    spare = -sum(change for change in adjustments if change < 0)
    needed = sum(change for change in adjustments if change > 0)
    if not spare or not needed:
        return columns
    transfer = min(spare, needed)
    return tuple(
        (key, label, width + change * transfer / (needed if change > 0 else spare))
        for (key, label, width), change in zip(columns, adjustments)
    )


def _item_values(item: dict, *, production: bool) -> dict:
    attrs = item.get("attrs") or {}
    piece = attrs.get("product_type") == "piece"
    specification = [f"工艺/尺寸：{attrs.get('craft') or '—'}", f"发长：{attrs.get('length') or '—'}"]
    if not piece:
        specification.extend(f"{label}：{attrs[key]}" for key, label in (
            ("net_color", "网帽颜色"), ("size", "尺码"), ("density", "发量"), ("hair_style_series", "发型系列"),
        ) if attrs.get(key))
    values = {**{key: _display(item.get(key)) for key in ("line_code", "product_name", *_IMAGE_FIELDS)},
              **{key: _display(attrs.get(key)) for key in ("craft", "length", "net_color", "size", "density")},
              "product_type": PRODUCT_TYPES.get(attrs.get("product_type"), "—"),
              "specification": _safe_text("\n".join(specification)),
              "order_qty": item.get("order_qty") or 0, "issued_qty": None}
    if piece:
        values.update(net_color=None, size=None, density=None)
    for key in _MONEY_FIELDS - {"discount_price"}:
        values[key] = float(money(item[key])) if item.get(key) is not None else None
    values["discount_price"] = float(money(item["unit_price"]) - money(item.get("labor_fee"))) if item.get("unit_price") is not None else None
    if item.get("status") == 3:
        values["line_code"] = f"{values['line_code']}（已终止）"
        values["line_amount"] = 0
        values["issued_qty"] = "已终止"
    if not production and item.get("guest_name"):
        values["specification"] = f"顾客：{_safe_text(item['guest_name'])}\n{values['specification']}"
    return values


def _write_item_rows(ws, first_row: int, columns: tuple, item: dict, values: dict) -> int:
    chunks = []
    for key, _, width in columns:
        value = values.get(key)
        parts = _text_chunks(value, width) if isinstance(value, str) and key != "line_code" else [value]
        if key in _IMAGE_FIELDS and item.get(_IMAGE_FIELDS[key]) and _wrapped_lines(parts[-1], width) > _MAX_TEXT_LINES_WITH_IMAGES:
            parts.append(None)
        chunks.append(parts)

    for offset, row_values in enumerate(zip_longest(*chunks)):
        row = first_row + offset
        if offset:
            row_values = (f"{_display(item.get('line_code'))}（续）", *row_values[1:])
        lines = max(_wrapped_lines(value, width) for value, (_, _, width) in zip(row_values, columns))
        ws.row_dimensions[row].height = max(75 if not offset else 30, lines * 15 + 15)
        for col, ((key, _, width), value, parts) in enumerate(zip(columns, row_values, chunks), start=1):
            cell = ws.cell(row, col, value)
            cell.font = Font(name=_FONT_NAME, size=11)
            horizontal = "right" if key in _MONEY_FIELDS else "left" if key in _IMAGE_FIELDS else "center"
            cell.alignment = Alignment(horizontal=horizontal, vertical="center", wrap_text=True)
            cell.border = _BORDER
            if isinstance(value, str):
                # A continuation may start with "=" even when the original value did not.
                cell.data_type = "s"
            if key in _MONEY_FIELDS:
                cell.number_format = '#,##0.00;[Red]-#,##0.00;0.00'
            if key in _IMAGE_FIELDS and offset == len(parts) - 1:
                add_cell_images(ws, row, col, item.get(_IMAGE_FIELDS[key]) or [], width)
    return first_row + max(map(len, chunks))


def _finance_text(detail: dict) -> str:
    snapshot = detail.get("balance_snapshot") or {}
    source = snapshot.get("source", "unavailable")
    amount = money(detail.get("total_amount"))
    if source == "unavailable":
        return f"本次订单金额：¥{amount:.2f}     扣款前/后余额：无历史扣款记录，无法核实"
    before, after = money(snapshot.get("balance_before")), money(snapshot.get("balance_after"))
    if source == "draft_preview":
        return f"草稿未扣款 · 当前余额：¥{before:.2f}     本次订单金额：¥{amount:.2f}     预计扣减后余额：¥{after:.2f}"
    if snapshot.get("transaction_type") == "order_charge":
        return f"之前余额：¥{before:.2f}     本次订单金额：¥{amount:.2f}     扣减本次订单后余额：¥{after:.2f}"
    delta = money(snapshot.get("settlement_amount"))
    action = f"实际补扣：¥{delta:.2f}" if delta >= 0 else f"实际退回：¥{-delta:.2f}"
    return (f"最近调整前余额：¥{before:.2f}     本次订单金额：¥{amount:.2f}     "
            f"{action}     调整后余额：¥{after:.2f}")


def _add_order_sheet(wb: Workbook, detail: dict, applicant_name: str, *, show_prices: bool) -> None:
    """Build each sheet independently so the no-price version contains no money cells."""
    production = detail.get("order_kind") == "production"
    columns = _PRODUCTION_COLUMNS if production else _BUSINESS_COLUMNS
    include_finance = show_prices and not production
    if not show_prices:
        columns = tuple(column for column in columns if column[0] not in _MONEY_FIELDS)
    items = detail.get("items") or []
    item_values = [_item_values(item, production=production) for item in items]
    columns = _fit_columns(columns, item_values)
    sheet_width = sum(width for _, _, width in columns)
    last_column = get_column_letter(len(columns))
    header_row = 5 if include_finance else 4
    first_item_row = header_row + 1
    title = "内贸生产备货单" if production else "内贸订单领货单"
    ws = wb.create_sheet(title if show_prices else f"{title}（无价格）")
    ws.merge_cells(f"B1:{last_column}1")
    ws["B1"] = title
    ws["B1"].font = Font(name=_FONT_NAME, size=18, bold=True)
    ws["B1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.merge_cells(f"A2:{last_column}2")
    ws["A2"] = (
        f"下单日期：{_date_text(detail.get('order_date'))}     "
        f"要求发货日期：{_date_text(detail.get('required_ship_date'))}     "
        f"客户订单号：{_safe_text(detail.get('order_no'))}     "
        f"系统单号：{_safe_text(detail.get('domestic_no'))}     "
        f"申请人：{_safe_text(applicant_name)}     "
        f"客户编码：{_safe_text(detail.get('customer_custom_code')) or '未填写'}"
    )
    ws.merge_cells(f"A3:{last_column}3")
    ws["A3"] = (
        f"客户名称：{_display(detail.get('customer_name'))}     "
        "审批人签字：____________________     "
        f"订单类别：{_safe_text(detail.get('order_category_label'))}     "
        f"订单类型：{_safe_text(detail.get('order_type_label'))}     "
        f"订单渠道：{_safe_text(detail.get('order_channel_label'))}"
    )
    if production:
        ws["A2"] = (f"下单日期：{_date_text(detail.get('order_date'))}     "
                    f"生产单号：{_safe_text(detail.get('domestic_no'))}     "
                    f"申请人：{_safe_text(applicant_name)}")
        customer_label = _safe_text(detail.get("customer_name"))
        purpose = "用途：毛坯生产至入库" if customer_label else "用途：公司毛坯备货（确认下单至入库）"
        ws["A3"] = f"客户名称：{customer_label or '公司备货'}     {purpose}     审批人签字：____________________"
    elif include_finance:
        ws.merge_cells(f"A4:{last_column}4")
        ws["A4"] = _finance_text(detail)
    for row in range(2, header_row):
        cell = ws.cell(row, 1)
        cell.font = Font(name=_FONT_NAME, size=12, bold=True)
        cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        cell.border = _BORDER
        ws.row_dimensions[row].height = max(38, _wrapped_lines(cell.value, sheet_width) * 15 + 15)
    for col, (_, label, width) in enumerate(columns, start=1):
        cell = ws.cell(header_row, col, label)
        cell.font = Font(name=_FONT_NAME, size=11, bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = _BORDER
        ws.column_dimensions[get_column_letter(col)].width = width

    next_item_row = first_item_row
    for item, values in zip(items, item_values):
        next_item_row = _write_item_rows(ws, next_item_row, columns, item, values)

    notes = "注意事项：\n！出库数量留空，由出库人员填写。\n！领货与签字流程按内贸部门现行规定执行。"
    if include_finance:
        notes += "\n！金额单位为人民币元；小计 =（优惠后单价 + 手工费）× 数量。余额取本订单扣款/调整记录，不随后续充值变化。"
    if detail.get("remark"):
        notes += f"\n订单备注：{_safe_text(detail['remark'])}"
    for row, text in enumerate(_text_chunks(notes, sheet_width), start=next_item_row + 1):
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=len(columns))
        cell = ws.cell(row, 1, text)
        cell.data_type = "s"
        cell.font = Font(name=_FONT_NAME, size=11, bold=True)
        cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
        cell.border = _BORDER
        ws.row_dimensions[row].height = max(75, _wrapped_lines(text, sheet_width) * 15 + 15)
    ws.row_dimensions[1].height = 32
    ws.row_dimensions[header_row].height = 42
    ws.freeze_panes = f"A{first_item_row}"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins = PageMargins(left=0.24, right=0.24, top=0.35, bottom=0.35)
    ws.print_title_rows = f"1:{header_row}"
    ws.print_area = f"A1:{last_column}{ws.max_row}"


def build_order_workbook(detail: dict, applicant_name: str = "") -> BytesIO:
    """Export exactly two complete views, with and without structured prices."""
    wb = Workbook()
    wb.remove(wb.active)
    _add_order_sheet(wb, detail, applicant_name, show_prices=True)
    _add_order_sheet(wb, detail, applicant_name, show_prices=False)
    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)
    return stream
