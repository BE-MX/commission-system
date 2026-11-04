"""One-time legacy WA association import; never recreates revoked versions."""

from hashlib import sha256
from app.client_desk.private_scope import list_private_companies, user_id
from app.client_desk.models import ClientDeskWaLink
from app.client_desk.service import atomic_insert
from app.system.models import SysDict


def import_history(db, user):
    from app.client_desk.sources import visible_wa
    from app.customer.pcw_models import ConversationBinding
    from app.customer.models import (
        CustomerExternalIdentity as Identity,
        CustomerAccount,
    )
    from app.customer.logical_customer_service import (
        logical_subject_matches_customer,
        resolve_canonical_customer_id,
    )
    from app.client_desk.access import require_enabled

    actor = require_enabled(db, user)
    private = {c["company_id"] for c in list_private_companies(db, actor)}
    pairs = visible_wa(db, actor, owner_only=True)
    imported = 0
    for conv, account, _ in pairs:
        # The marker is per owned conversation, so a newly arrived conversation can be imported
        # once without reconsidering the employee's earlier explicit removals or ignored items.
        code = sha256(
            (account.account_uid + "\0" + conv.conversation_uid).encode()
        ).hexdigest()
        marker = (
            db.query(SysDict).filter_by(type="client_desk_import", code=code).first()
        )
        if marker:
            continue
        db.query(type(conv)).filter_by(id=conv.id).with_for_update().one()
        if (
            not db.query(ClientDeskWaLink.id)
            .filter_by(
                account_uid=account.account_uid, conversation_uid=conv.conversation_uid
            )
            .first()
        ):
            old = (
                db.query(ConversationBinding)
                .filter_by(
                    source_system="whatsapp",
                    source_account_key=account.account_uid,
                    source_conversation_id=conv.conversation_uid,
                    state="active",
                )
                .first()
            )
            if old and old.customer_id:
                canonical = resolve_canonical_customer_id(db, old.customer_id)
                identities = (
                    db.query(Identity)
                    .join(
                        CustomerAccount,
                        logical_subject_matches_customer(
                            Identity, "external_identity", CustomerAccount
                        ),
                    )
                    .filter(
                        CustomerAccount.id == canonical,
                        Identity.source_system == "okki",
                        Identity.identifier_type == "company_id",
                        Identity.status == "active",
                        Identity.verification_status == "verified",
                        Identity.identity_strength == "strong",
                        Identity.cardinality == "one_to_one",
                    )
                    .all()
                )
                company_ids = {
                    str(i.normalized_value)
                    for i in identities
                    if str(i.normalized_value) in private
                }
                if len(company_ids) == 1:
                    db.add(
                        ClientDeskWaLink(
                            account_uid=account.account_uid,
                            conversation_uid=conv.conversation_uid,
                            company_id=int(company_ids.pop()),
                            link_type="imported",
                            created_by=user_id(actor),
                        )
                    )
                    imported += 1
        atomic_insert(
            db,
            SysDict,
            {
                "type": "client_desk_import",
                "code": code,
                "label": "Legacy association checked",
                "is_active": True,
                "sort": 0,
            },
            ["type", "code"],
        )
    db.flush()
    return imported
