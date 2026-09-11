"""Load reviewed release bindings, with explicit environment overrides by section."""

import json
from pathlib import Path

from app.whatsapp_translation.reply_state import error
from app.knowledge.reply_sources import parse_bindings

REPO_ROOT = Path(__file__).resolve().parents[3]


def source_profile(settings):
    values = []
    if settings.WHATSAPP_REPLY_SOURCE_PROFILE:
        path = Path(settings.WHATSAPP_REPLY_SOURCE_PROFILE)
        if not path.is_absolute():
            path = REPO_ROOT / path
        try:
            if path.stat().st_size > 512000:
                raise ValueError('profile too large')
            values = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(values, list):
                raise ValueError('profile must be a list')
        except (OSError, ValueError):
            raise error('reply_configuration_invalid', 503) from None
    # Validate both lists before merging; an explicit blocked override stays blocked.
    try:
        base = parse_bindings(values)
        overrides = parse_bindings(settings.WHATSAPP_REPLY_SOURCE_BINDINGS)
        merged = {(b.document_id, b.section_index): b for b in base}
        merged.update({(b.document_id, b.section_index): b for b in overrides})
        return parse_bindings([b.model_dump(mode='json') for b in merged.values()])
    except (ValueError, TypeError):
        raise error('reply_configuration_invalid', 503) from None
