"""LeShine customer PI: render approved display fields only; no internal invoice exporter."""
from functools import lru_cache
from hashlib import sha256
from html import escape
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

from app.core.config import get_settings
from app.portal.errors import reject


@lru_cache(maxsize=4)
def registered_font(path):
    name = "PortalPI-"+sha256(path.encode()).hexdigest()[:12]
    try:
        pdfmetrics.registerFont(TTFont(name, path))
    except Exception:
        reject("PDF_UNAVAILABLE", "The PI document service is not configured. Please contact your account manager.", 503)
    return name


def render(snapshot):
    font = registered_font(str(get_settings().PDF_CJK_FONT_PATH))
    normal = ParagraphStyle("body", fontName=font, fontSize=9, leading=14, textColor=colors.HexColor("#292820"))
    small = ParagraphStyle("small", parent=normal, fontSize=8, leading=12)
    right = ParagraphStyle("right", parent=normal, alignment=TA_RIGHT)
    heading = ParagraphStyle("heading", parent=normal, fontSize=11, leading=17, spaceAfter=8)
    def paragraph(value, style=normal):
        return Paragraph(escape(str(value or "")).replace("\n", "<br/>"), style)
    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, leftMargin=42, rightMargin=42,
        topMargin=108, bottomMargin=62, title="LeShine Proforma Invoice", author="LeShine")
    story = [paragraph("PROFORMA INVOICE", ParagraphStyle("title", parent=heading, fontSize=21, leading=27)),
        paragraph(snapshot["invoice_no"]+"  |  "+snapshot["invoice_date"]), Spacer(1,16)]
    delivery = snapshot["delivery"]
    address = "\n".join(str(delivery.get(key) or "") for key in (
        "contact_name", "phone", "formatted_address", "address_line1", "address_line2", "city", "region", "postal_code", "country_code") if delivery.get(key))
    metadata = Table([[paragraph("BILL TO",small), paragraph("SHIP TO",small)],
        [paragraph(snapshot["customer_name"]), paragraph(address)]], colWidths=[245,266])
    metadata.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"), ("LEFTPADDING",(0,0),(-1,-1),0),
        ("BOTTOMPADDING",(0,0),(-1,-1),8)]))
    story += [metadata, Spacer(1,12), paragraph("Customer PO: "+(snapshot.get("customer_po") or "—"),small), Spacer(1,14)]
    header = snapshot.get("commercial_header") or {}
    for key, label in (("express_channel","Shipping method"),("contact_email","Customer email"),
            ("sales_user_name","Account manager"),("sales_phone","Contact phone"),
            ("sales_email","Contact email"),("packaging_quantity","Packaging quantity")):
        if header.get(key):
            story += [paragraph(label+": "+str(header[key]),small),Spacer(1,4)]
    rows = [[paragraph(value,small) for value in ("PRODUCT / YOUR REFERENCE", "QTY", "UNIT PRICE", "DISCOUNT", "AMOUNT")]]
    for item in snapshot["items"]:
        display = item["display_snapshot"]
        description = " · ".join(str(display.get(key) or "") for key in ("model_name", "color_name", "length", "weight") if display.get(key))
        if display.get("customer_sku"):
            description += "\nYour SKU: "+str(display["customer_sku"])
        if display.get("unit"):
            description += "\nUnit: "+str(display["unit"])
        rows.append([paragraph(description), paragraph(item["quantity"],right),
            paragraph(item["unit_price"],right), paragraph(item["discount_amount"],right), paragraph(item["line_amount"],right)])
    table = Table(rows, colWidths=[230,35,82,82,82], repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#ffdf52")),
        ("VALIGN",(0,0),(-1,-1),"TOP"), ("TOPPADDING",(0,0),(-1,-1),9), ("BOTTOMPADDING",(0,0),(-1,-1),9),
        ("LINEBELOW",(0,0),(-1,0),0.6,colors.HexColor("#25251f")),
        ("LINEBELOW",(0,1),(-1,-1),0.4,colors.HexColor("#e7e5dc"))]))
    story += [table, Spacer(1,18)]
    fees = snapshot["fees"]
    totals = [("Products",snapshot["product_amount"]),("Shipping",fees["shipping_amount"]),
        ("Packaging",fees["packaging_amount"]),(fees.get("surcharge_name") or "Additional charges",fees["surcharge_amount"]),
        ("TOTAL · "+snapshot["currency"],snapshot["total_amount"])]
    summary = Table([[paragraph(label),paragraph(amount,right)] for label,amount in totals], colWidths=[185,80],hAlign="RIGHT")
    summary.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
        ("BACKGROUND",(0,-1),(-1,-1),colors.HexColor("#ffdf52"))]))
    story += [KeepTogether(summary),Spacer(1,22), paragraph("PAYMENT TERMS",heading),
        paragraph(snapshot["payment_terms_snapshot"]["display_text"])]
    if snapshot.get("remark"):
        story += [Spacer(1,12),paragraph("ORDER NOTES",heading),paragraph(snapshot["remark"])]
    story += [Spacer(1,18),paragraph("This proforma invoice is not a payment receipt or an inventory reservation. Contact your account manager before arranging payment.",small)]
    def page(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#ffdf52")); canvas.rect(0,A4[1]-12,A4[0],12,fill=1,stroke=0)
        canvas.saveState()
        clip = canvas.beginPath(); clip.rect(42,A4[1]-80,130,60); canvas.clipPath(clip,stroke=0)
        canvas.drawImage(str(Path(__file__).parent/"assets"/"logo.webp"),42,A4[1]-116,width=130,height=130)
        canvas.restoreState()
        canvas.setFillColor(colors.HexColor("#151611"))
        canvas.setFont("Helvetica",9); canvas.drawRightString(A4[0]-42,A4[1]-59,"CUSTOMER ORDERING")
        canvas.setStrokeColor(colors.HexColor("#e7e5dc")); canvas.line(42,44,A4[0]-42,44)
        canvas.setFont("Helvetica",8); canvas.drawString(42,30,"LeShine  /  Proforma invoice")
        canvas.drawRightString(A4[0]-42,30,str(doc.page)); canvas.restoreState()
    document.build(story,onFirstPage=page,onLaterPages=page)
    return output.getvalue()
