"""Read available specifications before asking the customer to repeat a question."""

import logging
import re

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import get_settings
from app.invoice.catalog_specs import lookup_specs
from app.whatsapp_translation.reply_state import error

logger = logging.getLogger('commission.whatsapp_reply')

# Preserves the original hard-coded behavior; override via WHATSAPP_REPLY_CATALOG_RULES.
DEFAULT_CATALOG_RULES = [
    {"trigger": r"\bgenius\b|天才", "terms": ["genius", "天才"]},
    {"trigger": r"\bwefts?\b|发帘", "terms": ["weft", "发帘"]},
]


class CatalogRule(BaseModel):
    """First matching rule wins; earlier rules are the narrower series."""

    model_config = ConfigDict(extra="forbid")
    trigger: str = Field(min_length=1, max_length=200)
    terms: list[str] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def usable_trigger(self):
        try:
            re.compile(self.trigger)
        except re.error:
            raise ValueError("invalid catalog trigger") from None
        if any(not term.strip() or len(term) > 40 for term in self.terms):
            raise ValueError("invalid catalog term")
        return self


def catalog_rules(settings) -> list[CatalogRule]:
    values = settings.WHATSAPP_REPLY_CATALOG_RULES or DEFAULT_CATALOG_RULES
    try:
        if len(values) > 32:
            raise ValueError("too many catalog rules")
        return [CatalogRule.model_validate(value) for value in values]
    except (ValueError, TypeError):
        # Misconfiguration is an operator error: fail closed and loud, like the
        # source profile, instead of silently dropping product lines.
        raise error('reply_configuration_invalid', 503) from None


def retrieve_catalog(db, actor, request, settings=None):
    settings = settings or get_settings()
    rules = catalog_rules(settings)
    latest = next((message.text for message in reversed(request.messages) if message.role == 'customer'), '')
    context = '\n'.join(message.text for message in request.messages[-12:])
    product_scope = latest if any(re.search(rule.trigger, latest, re.I) for rule in rules) else context
    rule = next((rule for rule in rules if re.search(rule.trigger, product_scope, re.I)), None)
    if rule is None:
        return {'status': 'not_requested', 'matches': []}
    lengths = re.findall(r'(?<![\d.])(\d{1,2}(?:\.\d+)?)\s*(?:inches\b|inch\b|英寸|寸|["″])', latest, re.I)
    length = lengths[0] if len(set(lengths)) == 1 else None
    try:
        return lookup_specs(db, actor, rule.terms, length)
    except Exception as exc:
        # Catalog outages must not discard usable knowledge answers or leak SQL.
        logger.warning('reply catalog failed error_type=%s', type(exc).__name__)
        print(f'[WhatsApp reply] catalog failed error_type={type(exc).__name__}', flush=True)
        return {'status': 'unavailable', 'matches': [], 'available_lengths': []}
