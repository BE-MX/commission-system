"""Propagate updates to existing customer bindings within the sync transaction."""
from app.core.time import beijing_now
from app.customer.models import CustomerConversation, CustomerMessage, CustomerSourceRecord
from app.customer.pcw_models import ConversationBinding


def project_changed_message(db, account, message):
    from app.customer import pcw_conversation_service as pcw
    bindings = db.query(ConversationBinding).filter_by(
        source_system='whatsapp', source_account_key=account.account_uid,
        source_conversation_id=message.conversation_uid, state='active',
    ).all()
    for binding in bindings:
        conversation = db.get(CustomerConversation, binding.projected_conversation_id)
        if conversation is None:
            continue
        if account.crm_shared and account.consent_state == 'active':
            pcw._project_messages(db, conversation=conversation, account=account,
                customer_id=binding.customer_id, contact_id=binding.contact_id,
                now=beijing_now(), message_uids=[message.message_uid])
        else:
            # Withdrawal of sharing blocks new copies. Existing stale projection
            # is hidden by source ACL and contains no obsolete current body.
            existing = db.query(CustomerMessage).filter_by(conversation_id=conversation.id, external_message_id=message.message_uid).first()
            if existing:
                existing.content_text = None
                existing.attachment_meta_json = []
        db.query(CustomerSourceRecord).filter(
            CustomerSourceRecord.source_system == 'whatsapp',
            CustomerSourceRecord.source_account_key == account.account_uid,
            CustomerSourceRecord.external_record_id == message.message_uid,
            CustomerSourceRecord.id != conversation.latest_source_record_id,
        ).update({'processing_status': 'superseded'}, synchronize_session=False)
        pcw._stale_conversation_derivations(db, binding=binding, old_customer_id=binding.customer_id, now=beijing_now())
