"""Print-only ordering and selective DOCX emphasis; no production database."""
import io

from docx import Document

from app.shipping_inspection.print_service import sort_outbound_print_items
from app.shipping_inspection.word_service import build_outbound_word
from tests.test_shipping_inspection import _user, _pc_client


def sample_items():
    return [
        {"item_id": "b3p", "spec": "B3平行", "size": "16"},
        {"item_id": "24", "spec": "B1天才", "size": "24"},
        {"item_id": "unknown", "spec": "B1天才", "size": "未知"},
        {"item_id": "b1p", "spec": "B1平行", "size": "16"},
        {"item_id": "22", "spec": "B1天才", "product_name": "Weft／22／#8/20g"},
        {"item_id": "18", "spec": "B1天才", "size": '18"'},
        {"item_id": "b3t", "spec": "B3天才", "size": "24"},
        {"item_id": "20", "spec": "B1天才", "size": "20寸"},
        {"item_id": "16", "spec": "B1天才", "size": "16"},
        {"item_id": "16b", "spec": "B1天才", "size": "16"},
    ]


EXPECTED = ["16", "16b", "18", "20", "22", "24", "unknown", "b1p", "b3t", "b3p"]


def test_sort_groups_then_numeric_sizes_and_preserves_source():
    items = sample_items()
    original = list(items)
    assert [i["item_id"] for i in sort_outbound_print_items(items)] == EXPECTED
    assert items == original
    assert [i["size"] for i in sort_outbound_print_items([
        {"size": "100"}, {"size": "9.5"}, {"size": "9"}, {"size": None},
    ])] == ["9", "9.5", "100", None]
    assert [i.get("spec") for i in sort_outbound_print_items([
        {}, {"spec": "B10"}, {"spec": "B3"}, {"spec": "B1"},
    ])] == ["B1", "B3", "B10", None]


def test_word_order_and_only_grade_is_large_bold():
    items = sample_items()
    for item in items:
        item["product_name"] = item.get("product_name", item["item_id"])
    document = Document(io.BytesIO(build_outbound_word({}, items, "test")))
    rows = document.tables[-1].rows[1:]
    assert [r.cells[1].text for r in rows] == ["16", "16b", "18", "20", "Weft", "24", "unknown", "b1p", "b3t", "b3p"]
    assert [r.cells[0].text for r in rows] == [str(i) for i in range(1, 11)]
    for row in rows:
        runs = [run for run in row.cells[2].paragraphs[0].runs if run.text]
        assert runs[0].text in ("B1", "B3")
        assert runs[0].bold and runs[0].font.size.pt == 12
        assert not runs[1].bold and runs[1].font.size.pt == 9.5  # DOCX stores half-point units, matching the existing body style.
    document = Document(io.BytesIO(build_outbound_word({}, [{"spec": "B10 AB1 B3平行"}], "test")))
    runs = document.tables[-1].cell(1, 2).paragraphs[0].runs
    assert [r.text for r in runs if r.bold] == ["B3"]


def test_print_api_and_word_share_order(db, monkeypatch):
    from app.shipping_inspection import outbound_service
    monkeypatch.setattr(outbound_service, "list_outbound_items", lambda *args: sample_items())
    with _pc_client(db, _user(db), [], roles=["super_admin"]) as client:
        response = client.get("/api/shipping-inspection/outbound-records/OB001/print-data")
        assert response.status_code == 200
        assert [i["item_id"] for i in response.json()["data"]["items"]] == EXPECTED

