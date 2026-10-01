"""Live, versioned evidence for work item result acceptance."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Numeric, inspect
from sqlalchemy.orm import object_session

from app.customer import pcw_errors
from app.customer.access_service import apply_record_access
from app.customer.models import CustomerConversation, CustomerEvent, CustomerMessage, CustomerSourceRecord
from app.customer.pcw_idempotency import canonical_request_hash


def evidence_revision(row):
    """Hash persisted business content; a refresh timestamp is not a source revision."""
    # MySQL DATETIME without fsp may round a freshly flushed Python timestamp.
    # Refresh the clean row before issuing a revision so it matches the next read.
    session = object_session(row)
    if session is not None and inspect(row).persistent and not session.is_modified(row, include_collections=False):
        bind = session.get_bind(mapper=type(row))
        if bind.dialect.name == "mysql" and any(
                isinstance(getattr(row, column.name), datetime)
                and getattr(row, column.name).microsecond
                and getattr(column.type.dialect_impl(bind.dialect), "fsp", None) in (None, 0)
                for column in row.__table__.columns):
            session.refresh(row)
    ignored = {"created_at", "updated_at", "captured_at", "synced_at", "ingested_at", "last_polled_at", "poll_count", "last_synced_at", "last_pushed_status"}
    def stable(value):
        if isinstance(value, dict):
            return {key: stable(entry) for key, entry in value.items()}
        if isinstance(value, (list, tuple)):
            return [stable(entry) for entry in value]
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return format(value.normalize(), "f")
        if isinstance(value, float):
            return format(Decimal(str(value)).normalize(), "f")
        if isinstance(value, bytes):
            return value.hex()
        return value
    fields = {}
    for column in row.__table__.columns:
        if column.name in ignored:
            continue
        value = getattr(row, column.name)
        if isinstance(column.type, Boolean) and value is not None:
            value = bool(value)
        elif isinstance(column.type, Numeric) and value is not None:
            value = Decimal(str(value))
        fields[column.name] = stable(value)
    return canonical_request_hash(fields)


def visible_message(db, access, message_id):
    from app.customer.logical_customer_service import logical_root_predicate
    conversations = db.query(CustomerConversation.id).filter(logical_root_predicate(
        CustomerConversation, "conversation", access.customer_id))
    sources = apply_record_access(db.query(CustomerSourceRecord.id), CustomerSourceRecord, access,
                                  logical_object_type="source_record")
    return db.query(CustomerMessage).filter(CustomerMessage.id == message_id,
        CustomerMessage.conversation_id.in_(conversations), CustomerMessage.source_record_id.in_(sources)).one_or_none()


def validate_evidence(db, access, refs, *, item=None):
    from app.customer.evidence_service import serialize_facts, visible_facts, visible_events
    if not refs:
        raise pcw_errors.bad_request("需要有效的结果依据", error_code="RESOLUTION_EVIDENCE_REQUIRED")
    checked, records = [], []
    for ref in refs:
        kind, identity = ref.get("type"), ref.get("id")
        if kind == "fact":
            from app.customer.models import CustomerFact
            row = visible_facts(db, access).filter(CustomerFact.id == identity).one_or_none()
            valid = row is not None and serialize_facts(db, [row])[0]["selectable"] and row.verification_status in {"verified", "confirmed"}
        elif kind == "event":
            row = visible_events(db, access).filter(CustomerEvent.id == identity).one_or_none()
            valid = row is not None
        elif kind in {"message", "customer_message"}:
            row = visible_message(db, access, identity)
            valid = row is not None
        else:
            raise pcw_errors.bad_request("不支持的证据类型", error_code="EVIDENCE_TYPE_INVALID")
        if not valid:
            raise pcw_errors.conflict("证据不可见或失效，请重新核验", error_code="SOURCE_REVALIDATION_REQUIRED")
        revision = evidence_revision(row)
        if str(ref.get("revision") or "") != revision:
            raise pcw_errors.conflict("证据版本已变化，请重新选择", error_code="EVIDENCE_VERSION_CONFLICT")
        normalized = {"type": kind, "id": int(identity), "revision": revision}
        if normalized not in checked:
            checked.append(normalized)
            records.append(row)
    if item is not None:
        goal = item.goal_type
        if goal in {"inquiry", "inquiry_sla"}:
            context = item.context_json or {}
            conversation_id = context.get("conversation_id")
            inbound = db.get(CustomerMessage, context.get("last_inbound_message_id")) if context.get("last_inbound_message_id") else None
            baseline = inbound.sent_at if inbound else item.created_at
            matches = [row for row in records if isinstance(row, CustomerMessage) and row.direction == "out"
                       and (conversation_id is None or row.conversation_id == conversation_id)
                       and (row.sent_at > baseline or row.sent_at == baseline and (inbound is None or row.id > inbound.id))]
            if not matches:
                raise pcw_errors.conflict("回复目标需要对应会话的真实出站消息", error_code="GOAL_EVIDENCE_MISMATCH")
        elif goal in {"sample", "sample_feedback"}:
            if not any(isinstance(row, CustomerEvent) and row.event_type in {"sample.feedback_received", "sample.feedback.logged"}
                       and str((row.event_payload or {}).get("sample_id")) == str((item.context_json or {}).get("sample_case_id", (item.context_json or {}).get("sample_id")))
                       for row in records):
                raise pcw_errors.conflict("样品目标需要对应的反馈记录", error_code="GOAL_EVIDENCE_MISMATCH")
        elif goal == "delivery_exception":
            from app.customer.workbench_models import WorkItemDependency, WorkItemEvent

            shipments = db.query(WorkItemDependency).filter_by(item_id=item.id,
                source_domain="shipment", required=True).all()
            if not shipments:
                raise pcw_errors.conflict("交期异常需要关联实际运单与订单履约来源",
                                          error_code="GOAL_EVIDENCE_MISMATCH")
            plan_event = db.query(WorkItemEvent).filter_by(item_id=item.id,
                event_type="delivery_plan_decided").order_by(WorkItemEvent.id.desc()).first()
            reopened = db.query(WorkItemEvent.id).filter_by(item_id=item.id,
                event_type="reopen").order_by(WorkItemEvent.id.desc()).first()
            plan_payload = (plan_event.payload_json or {}) if plan_event else {}
            if (not plan_event or (reopened and plan_event.id < reopened.id)
                    or not plan_payload.get("delivery_plan") or not plan_payload.get("conversation_id")):
                raise pcw_errors.conflict("先记录已决定且已向客户发送的对应方案",
                                          error_code="GOAL_EVIDENCE_MISMATCH")
            # A later changed or hidden outbound proposal cannot still authorize
            # acceptance of the old plan. The event remains in immutable history.
            try:
                validate_evidence(db, access, plan_event.evidence_refs or [])
            except pcw_errors.PcwError as exc:
                raise pcw_errors.conflict("原交付方案来源已变化，请按新事实重开、核验并重新登记方案",
                                          error_code="DELIVERY_PLAN_SOURCE_CHANGED") from exc
            proposed = db.get(CustomerMessage, plan_payload["outbound_message_id"])
            accepted = any(isinstance(row, CustomerMessage) and row.direction == "in"
                and row.conversation_id == plan_payload["conversation_id"]
                and proposed is not None and row.sent_at > proposed.sent_at for row in records)
            if not accepted:
                raise pcw_errors.conflict("需要同一会话中方案发出后的客户真实回复",
                                          error_code="GOAL_EVIDENCE_MISMATCH")
        elif goal in {"reorder", "repurchase"}:
            raise pcw_errors.conflict("新订单覆盖复购提示由订单源模块验收", error_code="GOAL_EVIDENCE_MISMATCH")
        elif goal not in {"followup", "maintenance", "monitor", "campaign", "manual"}:
            raise pcw_errors.conflict("该目标尚缺结果验收规则", error_code="RESOLUTION_POLICY_UNAVAILABLE")
    return checked
