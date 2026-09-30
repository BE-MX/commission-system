"""Rehearse the display-image migration against a read-only D1 snapshot."""

import json
import sqlite3
import sys
from pathlib import Path


if len(sys.argv) != 2:
    raise SystemExit("usage: python scripts/qa-display-live-copy.py <pre-migration.sqlite>")

snapshot = Path(sys.argv[1]).resolve()
source = sqlite3.connect(f"file:{snapshot.as_posix()}?mode=ro", uri=True)
assert source.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
db = sqlite3.connect(":memory:")
source.backup(db)
source.close()
db.row_factory = sqlite3.Row

current = db.execute("""
    SELECT m.template_id, v.id AS version_id, v.source_version_id, e.entry_id,
           e.display_order, e.lengths_json, e.hot, s.config_json,
           (SELECT count(*) FROM master_version_specs ms WHERE ms.version_id = v.id) AS specs
    FROM master_template_state m
    JOIN master_versions v ON v.id = m.current_version_id
    JOIN template_source_versions s ON s.id = v.source_version_id
    JOIN master_version_entries e ON e.version_id = v.id AND e.display_order = 0
    ORDER BY m.template_id
""").fetchall()
assert len(current) == 23, f"expected 23 current templates, got {len(current)}"
before = {row["template_id"]: row for row in current}
display_targets = []
for row in current:
    card = json.loads(row["config_json"])["template"]["initialCards"][0]
    if (row["entry_id"] == card["entryId"] and row["lengths_json"] == "[16]"
            and card["colorCode"].startswith("#048A")
            and card["geometry"]["sizeLabel"] is None
            and card["geometry"]["swatch"][0] > 800
            and card["geometry"]["swatch"][1] < 220):
        display_targets.append(row["template_id"])
assert len(display_targets) == 22, f"expected 22 false inventory cards, got {len(display_targets)}"
assert "20g-genius-weft-regular" in display_targets
assert before["20g-genius-weft-regular"]["specs"] == 178

sql = (Path(__file__).resolve().parent.parent / "drizzle/0009_display_images.sql").read_text(encoding="utf-8")
with db:
    for statement in sql.split("--> statement-breakpoint"):
        if statement.strip():
            db.execute(statement)

for template_id, old in before.items():
    entry = db.execute("""
        SELECT kind, lengths_json, hot, display_order FROM master_version_entries
        WHERE version_id = ? AND entry_id = ?
    """, (old["version_id"], old["entry_id"])).fetchone()
    new_specs = db.execute(
        "SELECT count(*) FROM master_version_specs WHERE version_id = ?",
        (old["version_id"],),
    ).fetchone()[0]
    new_config = json.loads(db.execute(
        "SELECT config_json FROM template_source_versions WHERE id = ?",
        (old["source_version_id"],),
    ).fetchone()[0])
    old_config = json.loads(old["config_json"])
    new_card = new_config["template"]["initialCards"][0]
    old_card = old_config["template"]["initialCards"][0]
    assert new_card["entryId"] == old_card["entryId"]
    assert new_card["colorId"] == old_card["colorId"]
    assert new_card["order"] == old_card["order"]
    assert new_card["geometry"] == old_card["geometry"]
    assert new_card.get("image") == old_card.get("image")
    assert entry["display_order"] == old["display_order"]
    if template_id in display_targets:
        assert (entry["kind"], entry["lengths_json"], entry["hot"]) == ("display", "[]", 0)
        assert new_card["kind"] == "display" and new_card["lengths"] == []
        assert new_specs == old["specs"] - 1, template_id
        assert new_config["template"]["initialColorCount"] == old_config["template"]["initialColorCount"] - 1
    else:
        assert template_id == "invisible-tape-weft-super", template_id
        assert entry["kind"] == "stock" and new_specs == old["specs"]
        assert new_config == old_config

assert db.execute("""
    SELECT count(*) FROM master_version_entries e
    JOIN master_template_state m ON m.current_version_id = e.version_id
    WHERE e.kind = 'display'
""").fetchone()[0] == 22
assert db.execute("""
    SELECT count(*) FROM master_version_specs ms
    JOIN master_template_state m ON m.current_version_id = ms.version_id
    JOIN master_specs spec ON spec.id = ms.spec_id
    JOIN master_version_entries e ON e.version_id = ms.version_id AND e.entry_id = spec.entry_id
    WHERE e.kind = 'display'
""").fetchone()[0] == 0
print("real D1 snapshot rehearsal: 23 templates, 22 display images migrated, 22 false specs removed")
print("20g Genius Weft Regular: 178 -> 177 specs; image, order, and geometry preserved")
print("invisible-tape-weft-super: no false card or spec; unchanged")
db.close()
