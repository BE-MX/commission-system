"""Conservative inbox matching and audited human classification."""
import re
from datetime import timedelta, timezone

from app.core.time import beijing_now
from app.customer.fact_service import append_customer_event
from app.customer.models import CustomerAccount, CustomerContactPoint
from app.mail_outreach.errors import conflict, not_found
from app.mail_outreach.models import MailEvent, MailOutreachMessage, MailOutreachRevision, MailOutreachSendJob
from app.mail_outreach.worker_service import binding


def append_timeline(db, customer_id, event_type, item_id, title, payload, actor_id=None):
    return append_customer_event(db, customer_id=customer_id, event_type=event_type,
        event_source="manual" if actor_id else "email", event_title=title,
        event_payload=payload, payload_schema_version="customer_event_v1", occurred_at=beijing_now(),
        source_ref_type="customer", source_ref_id=str(customer_id),
        data_classification="personal_contact", actor_user_id=actor_id)


def _subject(value):
    return re.sub(r"^(?:(?:re|fw|fwd|回复|答复)\s*[:：]\s*)+", "", value.strip(), flags=re.I).casefold()


def serialize_event(row):
    return {"id": row.id, "matched_customer_id": row.matched_customer_id,
        "matched_job_id": row.matched_job_id, "subject": row.subject,
        "from_address": row.from_address, "classification": row.classification,
        "processed_status": row.processed_status, "match_basis": row.match_basis,
        "received_at_utc": row.received_at_utc.replace(tzinfo=timezone.utc).isoformat() if row.received_at_utc else None}


def ingest(db, identity, mailbox_id, payload):
    mailbox = binding(db, identity, mailbox_id, lock=True)
    inserted = 0
    for event in payload.events:
        if db.query(MailEvent.id).filter_by(mailbox_binding_id=mailbox_id,
                provider_message_id=event.provider_message_id).first():
            continue
        if event.to_address.lower() != mailbox.sender_email.lower():
            continue
        received = event.received_at_utc.replace(tzinfo=timezone.utc) if event.received_at_utc.tzinfo is None else event.received_at_utc
        received = received.astimezone(timezone.utc).replace(tzinfo=None)
        delivery_notice = bool(re.match(r"^(mailer-daemon|postmaster)@", event.from_address, flags=re.I)
            and re.search(r"undeliver|delivery|failure|returned|退信|未送达", event.subject, flags=re.I))
        addresses = [event.from_address.lower()]
        if delivery_notice:
            addresses = [x.lower() for x in event.original_recipient_candidates
                if len(x) <= 255 and re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", x)]
        candidates = db.query(MailOutreachSendJob, MailOutreachRevision).join(
            MailOutreachRevision, MailOutreachRevision.id == MailOutreachSendJob.revision_id,
        ).filter(MailOutreachSendJob.mailbox_binding_id == mailbox_id,
            MailOutreachSendJob.to_email_snapshot.in_(addresses),
            MailOutreachSendJob.send_started_at_utc <= received,
            MailOutreachSendJob.send_started_at_utc >= received - timedelta(days=14),
            MailOutreachSendJob.status.in_(("provider_accepted", "ambiguous")),
        ).all()
        matches = [job for job, rev in candidates if delivery_notice or _subject(rev.subject) == _subject(event.subject)]
        # Never ingest unrelated personal mailbox content or infer customer from sender alone.
        if len(matches) != 1:
            continue
        job = matches[0]
        message = db.get(MailOutreachMessage, job.message_id)
        db.add(MailEvent(mailbox_binding_id=mailbox_id, provider_message_id=event.provider_message_id,
            from_address=event.from_address.lower(), to_address=event.to_address.lower(),
            subject=event.subject, received_at_utc=received, in_reply_to=event.in_reply_to,
            references_header=event.references_header, classification="uncertain",
            matched_job_id=job.id, matched_customer_id=message.customer_id,
            match_basis="sender_subject_candidate", processed_status="needs_human",
            payload_redacted={"metadata_only": True, "delivery_notice_candidate": delivery_notice}))
        inserted += 1
    db.commit()
    return {"inserted": inserted}


def classify(db, event_id, user, payload):
    probe = db.get(MailEvent, event_id)
    if probe is None or probe.matched_customer_id is None:
        raise not_found("收件事件不存在")
    db.query(CustomerAccount).filter_by(id=probe.matched_customer_id).with_for_update().one()
    from app.mail_outreach.models import MailMailboxBinding
    db.query(MailMailboxBinding).filter_by(id=probe.mailbox_binding_id).with_for_update().one()
    event = db.query(MailEvent).filter_by(id=event_id).populate_existing().with_for_update().one_or_none()
    if event is None:
        raise not_found("收件事件不存在")
    if event.processed_status == "processed":
        if event.classification != payload.classification:
            raise conflict("该事件已完成分类，不能覆盖既有抑制结论", error_code="event_already_classified")
        return serialize_event(event)
    if event.matched_customer_id is None or event.matched_job_id is None:
        raise conflict("请先确认事件关联客户", error_code="event_unmatched")
    event.classification = payload.classification
    event.classification_confidence = 1
    event.processed_status = "processed"
    event.match_basis = "manual"
    event.payload_redacted = {"classified_by": int(user["sub"]), "reason": payload.reason}
    job = db.get(MailOutreachSendJob, event.matched_job_id)
    if payload.classification in ("opt_out", "bounce"):
        points = db.query(CustomerContactPoint).filter_by(point_type="email", normalized_value=job.to_email_snapshot).order_by(CustomerContactPoint.id).populate_existing().with_for_update().all()
        for point in points:
            point.contactability_status = "opted_out" if payload.classification == "opt_out" else "bounced"
    if payload.classification in ("human_reply", "opt_out", "bounce"):
        jobs = db.query(MailOutreachSendJob).filter(
            MailOutreachSendJob.to_email_snapshot == job.to_email_snapshot,
            MailOutreachSendJob.status.in_(("scheduled", "claimed", "blocked", "needs_review")),
            MailOutreachSendJob.send_started_at_utc.is_(None),
        ).order_by(MailOutreachSendJob.id).populate_existing().with_for_update().all()
        for pending in jobs:
            pending.status = "cancelled"
            pending.cancel_note = f"inbox_{payload.classification}:event_{event.id}"
    append_timeline(db, event.matched_customer_id, "outreach.classified", event.id,
        "开发信收件事件已人工确认", {"event_id": event.id, "classification": event.classification,
                                "reason": payload.reason}, int(user["sub"]))
    db.commit()
    return serialize_event(event)
