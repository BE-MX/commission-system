"""Invoice export helpers."""

from io import BytesIO
from html import escape

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from app.invoice.models import Invoice


def build_invoice_workbook(invoice: Invoice) -> BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "Invoice"

    ws.merge_cells("A1:J1")
    ws["A1"] = "COMMERCIAL INVOICE"
    ws["A1"].font = Font(size=18, bold=True)
    ws["A1"].alignment = Alignment(horizontal="center")

    ws["A3"] = "Invoice No."
    ws["B3"] = invoice.invoice_no
    ws["A4"] = "Date"
    ws["B4"] = invoice.invoice_date
    ws["A5"] = "Customer"
    ws["B5"] = invoice.customer_name
    ws["A6"] = "Currency"
    ws["B6"] = invoice.currency

    headers = [
        "Product_name", "Product", "Net Weight Grams", "Curl", "Model",
        "Color", "Length", "Quantity", "Price/Piece", "TotalPrice",
    ]
    start_row = 8
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=start_row, column=col, value=header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="2F5597")
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row_idx, item in enumerate(invoice.items, start=start_row + 1):
        values = [
            item.product_name,
            item.product_display,
            item.net_weight_grams,
            item.curl,
            item.model,
            item.color,
            item.length,
            item.quantity,
            float(item.price_per_piece or 0),
            float(item.total_price or 0),
        ]
        for col, value in enumerate(values, start=1):
            ws.cell(row=row_idx, column=col, value=value)

    total_row = start_row + len(invoice.items) + 1
    ws.cell(row=total_row, column=9, value="Total")
    ws.cell(row=total_row, column=10, value=float(invoice.total_amount or 0))
    ws.cell(row=total_row, column=9).font = Font(bold=True)
    ws.cell(row=total_row, column=10).font = Font(bold=True)

    thin = Side(style="thin", color="D9E2F3")
    for row in ws.iter_rows(min_row=start_row, max_row=total_row, min_col=1, max_col=10):
        for cell in row:
            cell.border = Border(top=thin, right=thin, bottom=thin, left=thin)
            cell.alignment = Alignment(vertical="center", wrap_text=True)

    widths = [28, 18, 18, 12, 14, 14, 12, 12, 14, 14]
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + idx)].width = width

    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)
    return stream


def build_print_html(invoice: Invoice) -> str:
    rows = []
    for item in invoice.items:
        rows.append(f"""
        <tr>
          <td>{escape(item.product_name or "")}</td>
          <td>{escape(item.product_display or "")}</td>
          <td>{escape(item.net_weight_grams or "")}</td>
          <td>{escape(item.curl or "")}</td>
          <td>{escape(item.model or "")}</td>
          <td>{escape(item.color or "")}</td>
          <td>{escape(item.length or "")}</td>
          <td class="num">{item.quantity}</td>
          <td class="num">{item.price_per_piece or ""}</td>
          <td class="num">{item.total_price or ""}</td>
        </tr>
        """)
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>{escape(invoice.invoice_no)} Invoice</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 32px; color: #1f2937; }}
    h1 {{ text-align: center; letter-spacing: 0; }}
    .meta {{ display: grid; grid-template-columns: 140px 1fr; gap: 8px; margin: 24px 0; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
    th {{ background: #2f5597; color: white; }}
    th, td {{ border: 1px solid #d9e2f3; padding: 8px; text-align: left; }}
    .num {{ text-align: right; }}
    .total {{ margin-top: 16px; text-align: right; font-weight: 700; }}
    @media print {{ button {{ display: none; }} }}
  </style>
</head>
<body>
  <button onclick="window.print()">Print / Save as PDF</button>
  <h1>COMMERCIAL INVOICE</h1>
  <div class="meta">
    <strong>Invoice No.</strong><span>{escape(invoice.invoice_no)}</span>
    <strong>Date</strong><span>{invoice.invoice_date}</span>
    <strong>Customer</strong><span>{escape(invoice.customer_name or "")}</span>
    <strong>Currency</strong><span>{escape(invoice.currency or "")}</span>
  </div>
  <table>
    <thead>
      <tr>
        <th>Product_name</th><th>Product</th><th>Net Weight Grams</th><th>Curl</th><th>Model</th>
        <th>Color</th><th>Length</th><th>Quantity</th><th>Price/Piece</th><th>TotalPrice</th>
      </tr>
    </thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  <div class="total">Total: {invoice.currency} {invoice.total_amount}</div>
</body>
</html>"""


def build_invoice_pdf(invoice: Invoice) -> BytesIO:
    lines = [
        ("COMMERCIAL INVOICE", 220, 800, 18),
        (f"Invoice No.: {invoice.invoice_no}", 50, 760, 11),
        (f"Date: {invoice.invoice_date}", 50, 742, 11),
        (f"Customer: {invoice.customer_name}", 50, 724, 11),
        (f"Currency: {invoice.currency}", 50, 706, 11),
        ("Product | Model | Color | Length | Qty | Price | Total", 50, 668, 9),
    ]
    y = 650
    for item in invoice.items[:28]:
        product = (item.product_display or item.product_name or "")[:24]
        row = (
            f"{product} | {item.model} | {item.color} | {item.length} | "
            f"{item.quantity} | {item.price_per_piece or ''} | {item.total_price or ''}"
        )
        lines.append((row[:105], 50, y, 8))
        y -= 16
    lines.append((f"Total: {invoice.currency} {invoice.total_amount}", 390, max(y - 12, 72), 12))

    content = ["BT"]
    for text, x, y_pos, size in lines:
        content.append(f"/F1 {size} Tf")
        content.append(f"1 0 0 1 {x} {y_pos} Tm")
        content.append(f"({_pdf_escape(text)}) Tj")
    content.append("ET")
    content_bytes = "\n".join(content).encode("latin-1", errors="replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content_bytes)).encode("ascii") + b" >>\nstream\n" + content_bytes + b"\nendstream",
    ]
    return _write_pdf(objects)


def _pdf_escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _write_pdf(objects: list[bytes]) -> BytesIO:
    stream = BytesIO()
    stream.write(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(stream.tell())
        stream.write(f"{index} 0 obj\n".encode("ascii"))
        stream.write(obj)
        stream.write(b"\nendobj\n")
    xref_offset = stream.tell()
    stream.write(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    stream.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        stream.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    stream.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode("ascii")
    )
    stream.seek(0)
    return stream
