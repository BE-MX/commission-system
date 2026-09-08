"""内贸订单 Excel 导出。"""

from datetime import date, datetime
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.page import PageMargins

from app.domestic.constants import PRODUCT_TYPES
from app.domestic.balance_service import money
from app.domestic.export_image_service import add_cell_images, needs_image_appendix, wrapped_text_lines


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
_LONG_TEXT_THRESHOLD = 80
_TEXT_FIELDS = (
    ("hairstyle", "发型"),
    ("color", "颜色"),
    ("style_requirement", "发型要求"),
    ("remark", "备注"),
)


def _safe_text(value) -> str:
    text = "" if value is None else str(value).strip()
    if text.startswith(("=", "+", "-", "@")):
        return f"'{text}"
    return text


def _safe_raw_text(value) -> str:
    text = "" if value is None else str(value)
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


def _print_chunks(
    text: str, width: int = 100, max_lines: int = 18, max_chars: int = 600,
) -> list[str]:
    chars_per_line = max(6, int(width * 1.4))
    pieces = []
    for line in text.splitlines(keepends=True) or [text]:
        pieces.extend(
            line[index:index + chars_per_line]
            for index in range(0, len(line), chars_per_line)
        )
    chunks = []
    current = ""
    for piece in pieces:
        candidate = current + piece
        if current and (
            len(candidate) > max_chars or _wrapped_lines(candidate, width) > max_lines
        ):
            chunks.append(current)
            current = piece
        else:
            current = candidate
    if current or not chunks:
        chunks.append(current)
    return chunks


def _add_full_requirements_sheet(wb: Workbook, detail: dict) -> None:
    rows = []
    for item in detail.get("items") or []:
        for key, label in _TEXT_FIELDS:
            if detail.get("order_kind") == "production" and key in ("hairstyle", "style_requirement"):
                continue
            text = str(item.get(key) or "").strip()
            columns = _PRODUCTION_COLUMNS if detail.get("order_kind") == "production" else _BUSINESS_COLUMNS
            width = next((width for field, _, width in columns if field == key), 22)
            image_overflow = item.get(_IMAGE_FIELDS[key]) and needs_image_appendix(text, width)
            if len(text) > _LONG_TEXT_THRESHOLD or image_overflow:
                for index, chunk in enumerate(_print_chunks(text)):
                    chunk_label = label if index == 0 else f"{label}（续）"
                    rows.append((_display(item.get("line_code")), chunk_label, _safe_raw_text(chunk)))
    order_remark = str(detail.get("remark") or "").strip()
    if len(order_remark) > _LONG_TEXT_THRESHOLD:
        for index, chunk in enumerate(_print_chunks(order_remark)):
            label = "订单备注" if index == 0 else "订单备注（续）"
            rows.append(("订单", label, _safe_raw_text(chunk)))
    if not rows:
        return

    ws = wb.create_sheet("完整要求")
    for col, value in enumerate(("明细号", "字段", "完整内容"), start=1):
        cell = ws.cell(1, col, value)
        cell.font = Font(name=_FONT_NAME, size=12, bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = _BORDER
    for row_idx, (line_code, label, content) in enumerate(rows, start=2):
        for col, value in enumerate((line_code, label, content), start=1):
            cell = ws.cell(row_idx, col, value)
            cell.font = Font(name=_FONT_NAME, size=11)
            cell.alignment = Alignment(
                horizontal="left" if col == 3 else "center",
                vertical="top",
                wrap_text=True,
            )
            cell.border = _BORDER
        ws.row_dimensions[row_idx].height = min(
            409, max(45, _wrapped_lines(content, 100) * 15 + 15)
        )
    ws.column_dimensions["A"].width = 10
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 100
    ws.row_dimensions[1].height = 28
    ws.freeze_panes = "A2"
    ws.print_title_rows = "1:1"
    ws.print_area = f"A1:C{len(rows) + 1}"
    ws.page_setup.orientation = "portrait"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins = PageMargins(left=0.35, right=0.35, top=0.5, bottom=0.5)


def _item_values(item: dict) -> dict:
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
    return values


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


def build_order_workbook(detail: dict, applicant_name: str = "") -> BytesIO:
    """Generate an A4 requisition with historical finance and embedded references."""
    production = detail.get("order_kind") == "production"
    columns = _PRODUCTION_COLUMNS if production else _BUSINESS_COLUMNS
    last_column = get_column_letter(len(columns))
    header_row = 4 if production else 5
    first_item_row = header_row + 1
    title = "内贸生产备货单" if production else "内贸订单领货单"
    wb = Workbook()
    ws = wb.active
    ws.title = title
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
        purpose = f"客户：{customer_label}（毛坯生产至入库）" if customer_label else "用途：公司毛坯备货（确认下单至入库）"
        ws["A3"] = f"{purpose}     审批人签字：____________________"
    else:
        ws.merge_cells(f"A4:{last_column}4")
        ws["A4"] = _finance_text(detail)
    for row in range(2, header_row):
        cell = ws.cell(row, 1)
        cell.font = Font(name=_FONT_NAME, size=12, bold=True)
        cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        cell.border = _BORDER
        ws.row_dimensions[row].height = 38
    for col, (_, label, width) in enumerate(columns, start=1):
        cell = ws.cell(header_row, col, label)
        cell.font = Font(name=_FONT_NAME, size=11, bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = _BORDER
        ws.column_dimensions[get_column_letter(col)].width = width

    items = detail.get("items") or []
    for row_idx, item in enumerate(items, start=first_item_row):
        values = _item_values(item)
        lines = max(_wrapped_lines(values.get(key), width) for key, _, width in columns)
        ws.row_dimensions[row_idx].height = min(300, max(75, lines * 15 + 15))
        for col, (key, _, width) in enumerate(columns, start=1):
            cell = ws.cell(row_idx, col, values.get(key))
            cell.font = Font(name=_FONT_NAME, size=11)
            cell.alignment = Alignment(horizontal="right" if key in _MONEY_FIELDS else "center",
                                       vertical="center", wrap_text=True)
            cell.border = _BORDER
            if key in _MONEY_FIELDS:
                cell.number_format = '#,##0.00;[Red]-#,##0.00;0.00'
            if key in _IMAGE_FIELDS:
                add_cell_images(ws, row_idx, col, item.get(_IMAGE_FIELDS[key]) or [], width)

    notes_row = first_item_row + len(items) + 1
    ws.merge_cells(start_row=notes_row, start_column=1, end_row=notes_row, end_column=len(columns))
    notes = "注意事项：\n！出库数量留空，由出库人员填写。\n！领货与签字流程按内贸部门现行规定执行。"
    if not production:
        notes += "\n！金额单位为人民币元；小计 =（优惠后单价 + 手工费）× 数量。余额取本订单扣款/调整记录，不随后续充值变化。"
    if detail.get("remark"):
        notes += f"\n订单备注：{_safe_text(detail['remark'])}"
    ws.cell(notes_row, 1, notes)
    ws.cell(notes_row, 1).font = Font(name=_FONT_NAME, size=11, bold=True)
    ws.cell(notes_row, 1).alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
    ws.cell(notes_row, 1).border = _BORDER
    ws.row_dimensions[1].height = 32
    ws.row_dimensions[header_row].height = 42
    ws.row_dimensions[notes_row].height = min(240, max(75, _wrapped_lines(notes, sum(c[2] for c in columns)) * 15 + 15))
    ws.freeze_panes = f"A{first_item_row}"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins = PageMargins(left=0.24, right=0.24, top=0.35, bottom=0.35)
    ws.print_title_rows = f"1:{header_row}"
    ws.print_area = f"A1:{last_column}{notes_row}"
    _add_full_requirements_sheet(wb, detail)
    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)
    return stream
