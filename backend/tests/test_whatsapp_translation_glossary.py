"""Glossary matching for WhatsApp translation."""

from sqlalchemy.orm import Session

from app.system.models import SysDict
from app.whatsapp_translation.glossary_service import (
    MAX_GLOSSARY_HITS,
    glossary_dict_type,
    glossary_for,
)


def _add(db: Session, dict_type: str, rows: list[tuple[str, str]], active: bool = True, sort_base: int = 0):
    for i, (code, label) in enumerate(rows):
        db.add(SysDict(
            type=dict_type,
            code=code,
            label=label,
            sort=sort_base + i,
            is_active=active,
            remark=None,
        ))
    db.flush()


def test_outgoing_matches_chinese_code_case_insensitive(db):
    _add(db, glossary_dict_type("en"), [("交期", "lead time"), ("顺发", "remy")])
    db.commit()
    hits = glossary_for(db, direction="outgoing", text="交期两周，顺发", target_language="en")
    assert [h["label"] for h in hits] == ["lead time", "remy"]
    # zh-CN 目标不注入
    assert glossary_for(db, direction="outgoing", text="交期两周", target_language="zh-CN") == []


def test_incoming_matches_foreign_label_any_language(db):
    _add(db, glossary_dict_type("es"), [("样品费", "gastos de muestra"), ("形式发票", "factura proforma")])
    _add(db, glossary_dict_type("en"), [("交期", "lead time")])
    db.commit()
    hits = glossary_for(db, direction="incoming", text="Confirm lead time y gastos de muestra por favor", target_language="zh-CN")
    labels = [h["label"] for h in hits]
    assert "lead time" in labels
    assert "gastos de muestra" in labels


def test_inactive_rows_are_skipped(db):
    _add(db, glossary_dict_type("en"), [("交期", "lead time")], active=False)
    db.commit()
    assert glossary_for(db, direction="outgoing", text="交期两周", target_language="en") == []


def test_matches_are_bounded_and_deduplicated(db):
    rows = [(f"术语{i}", f"term-{i}") for i in range(40)]
    _add(db, glossary_dict_type("fr"), rows)
    db.commit()
    text = " ".join(f"术语{i}" for i in range(40))
    hits = glossary_for(db, direction="outgoing", text=text, target_language="fr")
    assert len(hits) <= MAX_GLOSSARY_HITS
    codes = [h["code"] for h in hits]
    assert len(codes) == len(set(codes))


def test_seed_populates_only_supported_target_languages():
    import app.bootstrap.seed_whatsapp_translation as seed_mod
    langs = {row[0] for row in seed_mod._START}
    # zh-CN excluded: incoming is always zh-CN, glossary only drives outgoing.
    assert "zh-CN" not in langs
