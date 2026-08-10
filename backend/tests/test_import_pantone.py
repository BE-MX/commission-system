import pytest

from app.color.models import PantoneReference
from scripts import import_pantone


def test_bundled_solid_coated_source_is_complete():
    rows = import_pantone.parse_solid_coated_csv(import_pantone.load_solid_coated_csv())

    assert len(rows) == import_pantone.EXPECTED_COLOR_COUNT
    assert len({row["pantone_code"] for row in rows}) == import_pantone.EXPECTED_COLOR_COUNT


def test_bundled_solid_coated_source_rejects_checksum_drift(tmp_path, monkeypatch):
    changed = tmp_path / "pantone.csv"
    changed.write_text("PANTONENAME,UNIQUECODE,RED,GREEN,BLUE\n", encoding="utf-8")
    monkeypatch.setattr(import_pantone, "PANTONE_SOLID_COATED_CSV", changed)

    with pytest.raises(ValueError, match="checksum"):
        import_pantone.load_solid_coated_csv()


def test_bundled_solid_coated_source_accepts_windows_line_endings(tmp_path, monkeypatch):
    windows_copy = tmp_path / "pantone.csv"
    source = import_pantone.PANTONE_SOLID_COATED_CSV.read_bytes()
    windows_copy.write_bytes(source.replace(b"\n", b"\r\n"))
    monkeypatch.setattr(import_pantone, "PANTONE_SOLID_COATED_CSV", windows_copy)

    loaded = import_pantone.load_solid_coated_csv()

    assert "\r" not in loaded
    assert loaded.startswith("PANTONENAME,UNIQUECODE,RED,GREEN,BLUE\n")


def test_parse_solid_coated_csv_converts_lab_rows():
    source = """PANTONENAME,UNIQUECODE,RED,GREEN,BLUE
PANTONE 100 C,10001,92,-8,65
PANTONE Black C,10002,17,0,0
"""

    rows = import_pantone.parse_solid_coated_csv(source)

    assert [row["pantone_code"] for row in rows] == ["100 C", "Black C"]
    assert all(row["collection"] == "coated" for row in rows)
    assert all(row["hex_code"].startswith("#") and len(row["hex_code"]) == 7 for row in rows)
    assert rows[0]["hex_code"] == "#F5EA63"
    assert rows[0]["lab_l"] == 92
    assert rows[0]["lab_a"] == -8
    assert rows[0]["lab_b_val"] == 65


def test_replace_solid_coated_preserves_other_collections(db):
    db.add(PantoneReference(
        pantone_code="Old C", hex_code="#111111", rgb_r=17, rgb_g=17, rgb_b=17,
        collection="coated",
    ))
    db.add(PantoneReference(
        pantone_code="11-0103 TCX", hex_code="#F3ECE0", rgb_r=243, rgb_g=236, rgb_b=224,
        collection="tcx",
    ))
    db.commit()

    import_pantone.replace_solid_coated(db, [{
        "pantone_code": "100 C",
        "pantone_name": None,
        "hex_code": "#F6EB61",
        "rgb_r": 246,
        "rgb_g": 235,
        "rgb_b": 97,
        "lab_l": 92,
        "lab_a": -8,
        "lab_b_val": 65,
        "collection": "coated",
    }])
    db.commit()

    rows = db.query(PantoneReference).order_by(PantoneReference.pantone_code).all()
    assert [(row.pantone_code, row.collection) for row in rows] == [
        ("100 C", "coated"),
        ("11-0103 TCX", "tcx"),
    ]


def test_solid_coated_current_check_compares_codes_and_hex(db):
    db.add(PantoneReference(
        pantone_code="100 C", hex_code="#F5EA63", rgb_r=245, rgb_g=234, rgb_b=99,
        collection="coated",
    ))
    db.commit()
    expected = [{"pantone_code": "100 C", "hex_code": "#F5EA63"}]

    assert import_pantone.solid_coated_is_current(db, expected) is True
    assert import_pantone.solid_coated_is_current(
        db, [{"pantone_code": "100 C", "hex_code": "#000000"}],
    ) is False
