"""Private A4 inspection PDF, using the existing Pillow/CJK font pipeline."""
from io import BytesIO
import logging
from types import SimpleNamespace

from fastapi import HTTPException
from PIL import Image, ImageDraw, ImageOps
from pypdf import PdfWriter

from app.auth.models import ArkUser
from app.core.config import get_settings
from app.core.storage import transfers
from app.invoice.pdf_font import load_configured_cjk_font
from app.shipping_inspection import constants as C, file_service, outbound_service
from app.shipping_inspection.models import ShippingInspection, ShippingInspectionPhoto

logger = logging.getLogger(__name__)


class InspectionPages:
    """150 dpi A4 pages; wrap every field and flush pages to avoid retaining rasters."""
    width, height, margin = 1240, 1754, 72

    def __init__(self, title):
        self.writer = PdfWriter()
        self.writer.add_metadata({"/Title": title})
        self.font = load_configured_cjk_font(get_settings().PDF_CJK_FONT_PATH, 24)
        self.page = None
        self.number = 0
        self.new_page()

    def flush(self):
        if self.page is None:
            return
        self.draw.text((self.margin, self.height - 54), f"莱莎方舟 · 发货验货单    {self.number}", font=self.font, fill="black")
        with BytesIO() as buf:
            self.page.save(buf, format="PDF", resolution=150)
            buf.seek(0)
            self.writer.append(buf)
        self.page.close()
        self.page = None

    def new_page(self):
        self.flush()
        self.number += 1
        self.page = Image.new("RGB", (self.width, self.height), "white")
        self.draw = ImageDraw.Draw(self.page)
        self.y = self.margin

    def space(self, height):
        if self.y + height > self.height - self.margin:
            self.new_page()

    def text(self, value):
        for paragraph in str(value or "—").splitlines() or ["—"]:
            line = ""
            for char in paragraph:
                if line and self.draw.textlength(line + char, font=self.font) > self.width - 2 * self.margin:
                    self.line(line)
                    line = ""
                line += char
            self.line(line)
        self.y += 8

    def line(self, line):
        self.space(36)
        self.draw.text((self.margin, self.y), line, font=self.font, fill="black")
        self.y += 36

    def photo(self, path):
        self.space(560)
        with Image.open(path) as source:
            photo = ImageOps.exif_transpose(source).convert("RGB")
        try:
            photo.thumbnail((self.width - 2 * self.margin, 520))
            self.page.paste(photo, (self.margin, self.y))
            self.y += photo.height + 24
        finally:
            photo.close()

    def finish(self):
        self.flush()
        try:
            with BytesIO() as buf:
                self.writer.write(buf)
                return buf.getvalue()
        finally:
            self.writer.close()


def export_inspection_pdf(db, inspection_id, edit_version=None):
    # Lock the submitted version while reading photos/rendering; recall/upload use this same row lock.
    inspection = db.query(ShippingInspection).filter_by(id=inspection_id).populate_existing().with_for_update().first()
    if inspection is None:
        raise HTTPException(404, "验货单不存在")
    if inspection.status != C.STATUS_SUBMITTED or (edit_version is not None and inspection.edit_version != edit_version):
        raise HTTPException(409, "验货单已撤回或更新，请从最新通知或验货单列表下载")
    doc = None
    try:
        # Unlike the history drawer, an export must not silently omit failed item/photo reads.
        items = outbound_service.list_outbound_items(db, inspection.outbound_record_id)
        photos = db.query(ShippingInspectionPhoto).filter_by(
            inspection_id=inspection.id, media_type="image",
        ).order_by(ShippingInspectionPhoto.sort, ShippingInspectionPhoto.id).populate_existing().with_for_update().all()
        submitter = db.get(ArkUser, inspection.submitted_by) if inspection.submitted_by else None
        submitter = SimpleNamespace(real_name=submitter.real_name) if submitter else None
        photos = [SimpleNamespace(file_path=p.file_path, item_id=p.item_id,
                  storage=transfers.snapshot(db, 'shipping-inspection', p.file_path)) for p in photos]
        inspection = SimpleNamespace(**{name: getattr(inspection, name) for name in
            ('id', 'outbound_no', 'customer_name', 'submitted_at', 'remark', 'edit_version')})
        db.rollback()  # Network reads and PDF rendering must not retain row locks.
        doc = InspectionPages(f"验货单-{inspection.outbound_no}")
        doc.text("发货验货单")
        doc.text(f"出库单号：{inspection.outbound_no}")
        doc.text(f"客户名称：{inspection.customer_name or '—'}")
        doc.text(f"提交人：{submitter.real_name if submitter else '—'}")
        doc.text(f"提交时间：{inspection.submitted_at or '—'}")
        doc.text(f"检验备注：{inspection.remark or '无'}")
        doc.text("出库明细")
        names = {}
        for index, item in enumerate(items, 1):
            label = f"{index}. {item.get('product_name') or '—'}"
            names[str(item['item_id'])] = label
            doc.text(label)
            doc.text(f"规格：{item.get('spec') or '—'}  SKU：{item.get('sku') or '—'}  数量：{item.get('qty')} {item.get('unit') or ''}")
        doc.text(f"验货照片（{len(photos)} 张；视频不进入 PDF）")
        for index, photo in enumerate(photos, 1):
            doc.space(640)
            doc.text(f"照片 {index} · {names.get(str(photo.item_id), '整单照片')}")
            with transfers.materialize('shipping-inspection', photo.file_path, photo.storage) as path:
                doc.photo(path)
        current = db.query(ShippingInspection).filter_by(id=inspection.id).populate_existing().first()
        if current is None or current.status != C.STATUS_SUBMITTED or current.edit_version != inspection.edit_version:
            raise HTTPException(409, '验货单已撤回或更新，请重新下载')
        return doc.finish(), inspection.outbound_no
    except HTTPException as exc:
        if exc.status_code == 409:
            raise
        logger.warning('Inspection PDF dependency unavailable inspection=%s status=%s', inspection_id, exc.status_code)
        print(f'[SHIPPING] PDF dependency unavailable inspection={inspection_id} status={exc.status_code}', flush=True)
        raise HTTPException(503, '验货单原件暂时不可用，请等待云同步或联系管理员') from exc
    except Exception as exc:
        logger.warning("Inspection PDF failed: inspection=%s type=%s", inspection_id, type(exc).__name__)
        print(f"[SHIPPING] PDF failed: inspection={inspection_id} type={type(exc).__name__}", flush=True)
        raise HTTPException(503, "验货单 PDF 暂时生成失败，请稍后重试或联系管理员检查明细、照片及字体") from exc
    finally:
        if doc is not None:
            if doc.page is not None:
                doc.page.close()
            doc.writer.close()
