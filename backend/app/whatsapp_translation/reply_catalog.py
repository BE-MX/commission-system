"""Read available specifications before asking the customer to repeat a question."""

import logging
import re
from app.invoice.catalog_specs import lookup_specs

logger = logging.getLogger('commission.whatsapp_reply')


def retrieve_catalog(db, actor, request):
    latest = next((message.text for message in reversed(request.messages) if message.role == 'customer'), '')
    context = '\n'.join(message.text for message in request.messages[-12:])
    product_scope = latest if re.search(r'weft|发帘|天才', latest, re.I) else context
    if not re.search(r'\bwefts?\b|发帘|天才', product_scope, re.I):
        return {'status': 'not_requested', 'matches': []}
    # Series terms narrow a general weft family only when present in the chat.
    terms = ['genius', '天才'] if re.search(r'\bgenius\b|天才', product_scope, re.I) else ['weft', '发帘']
    lengths = re.findall(r'(?<![\d.])(\d{1,2}(?:\.\d+)?)\s*(?:inches\b|inch\b|英寸|寸|["″])', latest, re.I)
    length = lengths[0] if len(set(lengths)) == 1 else None
    try:
        return lookup_specs(db, actor, terms, length)
    except Exception as exc:
        # Catalog outages must not discard usable knowledge answers or leak SQL.
        logger.warning('reply catalog failed error_type=%s', type(exc).__name__)
        print(f'[WhatsApp reply] catalog failed error_type={type(exc).__name__}', flush=True)
        return {'status': 'unavailable', 'matches': [], 'available_lengths': []}
