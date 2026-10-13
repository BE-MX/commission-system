"""Filter immutable customer snapshots using current WhatsApp source permission."""
from copy import deepcopy

from app.customer.models import CustomerFact, CustomerSourceRecord
from app.whatsapp.access import readable_accounts


def filter_snapshot(db, payload: dict, version, *, access=None) -> tuple[dict, list[int]]:
    from app.customer.profile_service import _collect_fact_ids, _section_for_fact_key
    evidence_ids = set(version.evidence_fact_ids or ()) | _collect_fact_ids(payload)
    if not evidence_ids:
        return deepcopy(payload), []
    rows = db.query(CustomerFact.id, CustomerFact.fact_key, CustomerSourceRecord.source_account_key,
        CustomerSourceRecord.processing_status).join(CustomerSourceRecord, CustomerFact.source_record_id == CustomerSourceRecord.id).filter(
        CustomerFact.id.in_(evidence_ids), CustomerSourceRecord.source_system == 'whatsapp',
    ).all()
    if not rows:
        return deepcopy(payload), sorted(evidence_ids)
    allowed = set(row[0] for row in readable_accounts(db, access.actor_user_id, crm=True, ai=getattr(access, 'run_id', None) is not None).all()) if access else set()
    denied = {row.id for row in rows if row.source_account_key not in allowed or row.processing_status == 'superseded'}
    if not denied:
        return deepcopy(payload), sorted(evidence_ids)
    # Sections can summarize multiple facts: removing only a citation would
    # leave prose that discloses a hidden source value.
    sections = {_section_for_fact_key(row.fact_key) for row in rows if row.id in denied}
    result = deepcopy(payload)
    aliases = {'business': ('business_profile',), 'preferences': ('current_needs',),
        'commercial': ('commercial_summary',), 'behavior': ('behavior_patterns',),
        'quality': ('data_quality', 'open_questions')}
    for section in sections:
        for field in (section, *aliases.get(section, ())):
            if field in result:
                result[field] = {'redacted': True, 'reason': 'source_authorization_changed'}
    def strip(value):
        if isinstance(value, dict):
            direct_ids = set()
            for key, nested in value.items():
                if (key == 'fact_id' or key.endswith('_fact_id')) and isinstance(nested, int):
                    direct_ids.add(nested)
                elif key.endswith('_fact_ids') and isinstance(nested, list):
                    direct_ids.update(item for item in nested if isinstance(item, int))
            if direct_ids & denied:
                return None
            return {key: filtered for key, nested in value.items() if (filtered := strip(nested)) is not None}
        if isinstance(value, list):
            return [filtered for item in value if (filtered := strip(item)) is not None]
        return value
    result = {field: filtered for field, value in result.items() if (filtered := strip(value)) is not None}
    result['source_redacted'] = True
    return result, sorted(evidence_ids - denied)
