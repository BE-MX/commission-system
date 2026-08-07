"""Customer image invitation token security contract tests."""

import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from app.customer_image.models import CustomerImageInvite
from app.customer_image.token_service import (
    INVITE_UNAVAILABLE_MESSAGE,
    InviteUnavailableError,
    issue_invite_token,
    resolve_active_invite,
)


def _invite(now: datetime) -> CustomerImageInvite:
    return CustomerImageInvite(
        customer_id="CUST001",
        customer_name_snapshot="Customer One",
        created_by=1,
        okki_salesperson_id_snapshot="1007",
        token_hash="0" * 64,
        token_suffix="000000",
        starts_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(days=1),
        quota_total=3,
    )


def test_issue_invite_token_persists_only_digest_and_suffix(db, monkeypatch):
    plaintext = "private-invite-token-abcdef"
    monkeypatch.setattr(
        "app.customer_image.token_service.secrets.token_urlsafe",
        lambda size: plaintext if size == 32 else None,
    )
    invite = _invite(datetime(2026, 8, 7, 9, 0))

    returned, row = issue_invite_token(db, invite)

    assert returned == plaintext
    assert row.token_hash == hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    assert row.token_suffix == "abcdef"
    assert plaintext not in repr(row.__dict__)


def test_issue_invite_token_normalizes_boundaries_before_persistence(db):
    china = timezone(timedelta(hours=8))
    invite = _invite(datetime(2099, 1, 1, 16, 0, tzinfo=china))

    _plaintext, row = issue_invite_token(db, invite)

    assert row.starts_at == datetime(2099, 1, 1, 7, 59)
    assert row.expires_at == datetime(2099, 1, 2, 8, 0)
    assert row.starts_at.tzinfo is None
    assert row.expires_at.tzinfo is None


def test_resolve_active_invite_uses_digest_lookup(db):
    now = datetime(2026, 8, 7, 9, 0)
    plaintext, invite = issue_invite_token(db, _invite(now))
    db.commit()

    assert resolve_active_invite(db, plaintext, now).id == invite.id


@pytest.mark.parametrize("aware_side", ["now", "row"])
def test_resolve_active_invite_normalizes_mixed_datetime_boundaries(aware_side):
    utc = timezone.utc
    now = datetime(2026, 8, 7, 9, 0)
    invite = _invite(now)
    plaintext = "aware-boundary-token"
    invite.token_hash = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    if aware_side == "now":
        now = now.replace(tzinfo=utc)
    else:
        invite.starts_at = invite.starts_at.replace(tzinfo=utc)
        invite.expires_at = invite.expires_at.replace(tzinfo=utc)

    class FakeSession:
        def scalar(self, _statement):
            return invite

    assert resolve_active_invite(FakeSession(), plaintext, now) is invite


@pytest.mark.parametrize("state", ["missing", "not_started", "expired", "revoked"])
def test_resolve_invite_rejects_all_unavailable_states_with_one_message(db, state):
    now = datetime(2026, 8, 7, 9, 0)
    plaintext = "unknown-token"
    if state != "missing":
        plaintext, invite = issue_invite_token(db, _invite(now))
        if state == "not_started":
            invite.starts_at = now + timedelta(seconds=1)
        elif state == "expired":
            invite.expires_at = now
        else:
            invite.revoked_at = now
        db.commit()

    with pytest.raises(InviteUnavailableError, match=INVITE_UNAVAILABLE_MESSAGE):
        resolve_active_invite(db, plaintext, now)
