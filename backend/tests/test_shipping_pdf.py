"""PDF boundaries with isolated SQLite and private temporary files."""
from io import BytesIO
from pypdf import PdfReader
from PIL import Image
from app.shipping_inspection import pdf_service, file_service, service
from tests.test_shipping_inspection import _pc_client, storage, product_display_source, outbound_scope_seed
from tests.test_shipping_inspection_scope import scoped_inspections, READ


def test_pdf_scope_and_version(db, scoped_inspections):
    sales, records, photos = scoped_inspections
    Image.new('RGB', (600, 400), 'blue').save(file_service.resolve_path(photos[0].file_path), format='JPEG')
    url = f'/api/shipping-inspection/records/{records[0].id}/pdf'
    with _pc_client(db, sales, [READ, 'shipping_inspection:write']) as client:
        result = client.get(url, params={'edit_version': 0})
        assert result.status_code == 200
        assert result.headers['content-type'] == 'application/pdf'
        assert result.headers['cache-control'] == 'no-store'
        assert "filename*=UTF-8''" in result.headers['content-disposition']
        pdf = PdfReader(BytesIO(result.content))
        assert pdf.pages and pdf.metadata.title == '验货单-' + records[0].outbound_no
        assert client.get(f'/api/shipping-inspection/records/{records[1].id}/pdf').status_code == 404
        assert client.get(url, params={'edit_version': 1}).status_code == 409
        assert client.post(f'/api/shipping-inspection/records/{records[0].id}/recall', json={'edit_version': 0}).status_code == 200
        assert client.get(url, params={'edit_version': 0}).status_code == 409
        service.submit(db, outbound_record_id=records[0].outbound_record_id, user_id=sales.id, edit_version=1)
        assert client.get(url, params={'edit_version': 0}).status_code == 409
        assert client.get(url, params={'edit_version': 1}).status_code == 200
    with _pc_client(db, sales, []) as client:
        assert client.get(url).status_code == 403
    with _pc_client(db, sales, [READ]) as client:
        client.headers.pop('Authorization')
        assert client.get(url).status_code in (401, 403)


def test_pdf_fails_instead_of_omitting_photo_or_items(db, scoped_inspections, monkeypatch):
    sales, records, photos = scoped_inspections
    file_service.resolve_path(photos[0].file_path).unlink()
    with _pc_client(db, sales, [READ]) as client:
        url = f'/api/shipping-inspection/records/{records[0].id}/pdf'
        assert client.get(url).status_code == 503
        def broken(*args):
            raise RuntimeError('source unavailable')
        monkeypatch.setattr(pdf_service.outbound_service, 'list_outbound_items', broken)
        assert client.get(url).status_code == 503


def test_pdf_wraps_long_fields_and_paginates_photos(tmp_path):
    photo = tmp_path / 'photo.png'
    Image.new('RGB', (900, 1600), 'green').save(photo)
    doc = pdf_service.InspectionPages('分页验证')
    doc.text('产品规格/颜色/尺寸 ' * 180)
    for _ in range(5):
        doc.photo(photo)
    pdf = PdfReader(BytesIO(doc.finish()))
    assert len(pdf.pages) >= 3
    assert all(abs(float(page.mediabox.width) - 595.2) < 1 for page in pdf.pages)
