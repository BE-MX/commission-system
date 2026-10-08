"""A quiescent worker preserves scheduled and actively leased unrelated events."""
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.time import beijing_now
from app.portal import mail_worker
from app.portal.models import OutboxEvent
from test_mysql_notification_authority import setup_delivery
from test_mysql_notification_process import notification_case


@pytest.mark.parametrize("status", ["pending", "sending"])
def test_target_preserves_unclaimable_queue_rows(notification_case, monkeypatch, status):
    ctx = notification_case
    later = beijing_now() + timedelta(days=1)
    with Session(ctx.engine) as db:
        row = OutboxEvent(event_key="owned-future:" + uuid4().hex, event_type="invitation",
            aggregate_public_id=str(uuid4()), payload_json={}, status=status,
            next_attempt_at=later, lease_until=later if status == "sending" else None,
            lease_token=uuid4().hex if status == "sending" else None)
        db.add(row); db.commit(); row_id = row.id
        before = db.execute(select(*OutboxEvent.__table__.columns).where(OutboxEvent.id == row_id)).one()
    _, identifier, _ = setup_delivery(ctx, monkeypatch, "invitation")
    sent = []
    assert mail_worker.run_once(sessionmaker(bind=ctx.engine), lambda mail: sent.append(mail.message_id) or True) == "sent"
    assert sent == ["<portal-" + identifier + "@leshine.invalid>"]
    with Session(ctx.engine) as db:
        assert db.execute(select(*OutboxEvent.__table__.columns).where(OutboxEvent.id == row_id)).one() == before
        target = db.scalar(select(OutboxEvent).where(OutboxEvent.public_id == identifier))
        assert target.status == "sent" and target.attempt_count == 1
