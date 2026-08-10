#!/usr/bin/env python3
"""Import Pantone Solid Coated V5 references into ark_pantone_reference.

Usage:
    cd backend
    python scripts/import_pantone.py

The source repository describes this as an unofficial Solid Coated 2024 V5
library. Its CSV stores CIE Lab values despite the legacy RED/GREEN/BLUE
column names. The file was vendored on 2026-08-10 and is pinned below by
upstream commit and SHA-256 checksum.
"""

import csv
import hashlib
import io
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from app.color.calc_service import lab_d50_to_rgb, rgb_to_hex
from app.color.models import PantoneReference
from app.core.database import SessionLocal

PANTONE_SOLID_COATED_SOURCE = (
    "https://raw.githubusercontent.com/aj90909/"
    "unofficial-pantone-solid-coated-2024-v5/"
    "3d6ad83683cebc13ec859a675eae2a4c29bfd4d8/colors.csv"
)
PANTONE_SOLID_COATED_CSV = (
    Path(__file__).resolve().parents[1] / "app" / "color" / "pantone_solid_coated_v5.csv"
)
EXPECTED_COLOR_COUNT = 3219
EXPECTED_SOURCE_SHA256 = "4d01b656c75395ab558006aa24b928e08581040dd6e5f37c72794dcca6280364"


def load_solid_coated_csv() -> str:
    """Read the versioned Solid Coated CSV bundled with the application."""
    source = PANTONE_SOLID_COATED_CSV.read_bytes().replace(b"\r\n", b"\n")
    checksum = hashlib.sha256(source).hexdigest()
    if checksum != EXPECTED_SOURCE_SHA256:
        raise ValueError(f"Pantone Solid Coated source checksum mismatch: {checksum}")
    return source.decode("utf-8-sig")


def parse_solid_coated_csv(source: str) -> list[dict]:
    """Convert source CIE Lab rows to database-ready Solid Coated records."""
    parsed: list[dict] = []
    for source_row in csv.DictReader(io.StringIO(source)):
        raw_name = (source_row.get("PANTONENAME") or "").strip()
        if not raw_name.startswith("PANTONE ") or not raw_name.endswith(" C"):
            raise ValueError(f"Invalid Solid Coated color name: {raw_name!r}")

        lab = np.array([
            float(source_row["RED"]),
            float(source_row["GREEN"]),
            float(source_row["BLUE"]),
        ])
        hex_code = rgb_to_hex(lab_d50_to_rgb(lab))
        rgb = [int(hex_code[index:index + 2], 16) for index in (1, 3, 5)]
        parsed.append({
            "pantone_code": raw_name.removeprefix("PANTONE "),
            "pantone_name": None,
            "hex_code": hex_code,
            "rgb_r": rgb[0],
            "rgb_g": rgb[1],
            "rgb_b": rgb[2],
            "lab_l": float(lab[0]),
            "lab_a": float(lab[1]),
            "lab_b_val": float(lab[2]),
            "collection": "coated",
        })
    return parsed


def replace_solid_coated(db, rows: list[dict]) -> None:
    """Replace only the Solid Coated collection, leaving other books intact."""
    if not rows or any(row.get("collection") != "coated" for row in rows):
        raise ValueError("Solid Coated import requires non-empty coated rows")
    db.query(PantoneReference).filter(
        PantoneReference.collection == "coated"
    ).delete(synchronize_session=False)
    db.bulk_insert_mappings(PantoneReference, rows)


def solid_coated_is_current(db, rows: list[dict]) -> bool:
    """Return whether stored coated codes and display HEX values match the bundle."""
    stored = dict(
        db.query(PantoneReference.pantone_code, PantoneReference.hex_code)
        .filter(PantoneReference.collection == "coated")
        .all()
    )
    expected = {row["pantone_code"]: row["hex_code"] for row in rows}
    return stored == expected


def import_pantone() -> None:
    rows = parse_solid_coated_csv(load_solid_coated_csv())
    if len(rows) != EXPECTED_COLOR_COUNT:
        raise ValueError(
            f"Expected {EXPECTED_COLOR_COUNT} Solid Coated colors, received {len(rows)}"
        )

    db = SessionLocal()
    try:
        if solid_coated_is_current(db, rows):
            print(f"Pantone Solid Coated is current ({len(rows)} colors); skipping import")
            return
        replace_solid_coated(db, rows)
        db.commit()
        print(f"Successfully imported {len(rows)} Pantone Solid Coated colors")
    except Exception as exc:
        db.rollback()
        print(f"Error: {exc}", flush=True)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    import_pantone()
