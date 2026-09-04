"""Runtime glossary injection for trade-grade translation.

Terms live in the existing `sys_dict` table as dictionary type
`whatsapp_glossary_<lang>` (lang is a supported target language, e.g. `en`).
Semantics per row: `code` holds the Chinese term, `label` holds the term in
<lang>, `remark` is an optional note, `is_active` gates inclusion.
"""

from sqlalchemy.orm import Session

from app.system.models import SysDict
from app.whatsapp_translation.constants import SUPPORTED_TARGET_LANGUAGES

MAX_GLOSSARY_HITS = 30


def glossary_dict_type(language: str) -> str:
    return f"whatsapp_glossary_{language}"


def _active_rows(db: Session, dict_types: list[str]) -> list[SysDict]:
    return (
        db.query(SysDict)
        .filter(SysDict.type.in_(dict_types), SysDict.is_active.is_(True))
        .order_by(SysDict.type, SysDict.sort, SysDict.id)
        .all()
    )


def glossary_for(
    db: Session,
    *,
    direction: str,
    text: str,
    target_language: str,
) -> list[dict]:
    """Return glossary hits relevant to one translation request.

    outgoing: source is Chinese, match the Chinese term (`code`) against the
    text using the target language's table only.
    incoming: source language is unknown, match the foreign term (`label`)
    case-insensitively across every enabled language table.

    Only matched terms are injected; the cap keeps the prompt bounded on long
    messages. Term entries are not chat content, so they may live in the DB.
    """
    haystack = text.lower()
    if direction == "outgoing":
        if target_language == "zh-CN":
            return []
        rows = _active_rows(db, [glossary_dict_type(target_language)])
        matcher = lambda row: bool(row.code) and row.code.lower() in haystack  # noqa: E731
    else:
        rows = _active_rows(db, [glossary_dict_type(lang) for lang in SUPPORTED_TARGET_LANGUAGES if lang != "zh-CN"])
        matcher = lambda row: bool(row.label) and row.label.lower() in haystack  # noqa: E731

    hits: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if not matcher(row):
            continue
        key = (row.code, row.label)
        if key in seen:
            continue
        seen.add(key)
        hits.append({"code": row.code, "label": row.label})
        if len(hits) >= MAX_GLOSSARY_HITS:
            break
    return hits
