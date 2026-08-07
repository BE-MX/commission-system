"""Issue and resolve invitation tokens without persisting plaintext secrets."""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.customer_image.datetime_utils import as_utc_naive
from app.customer_image.models import CustomerImageInvite


INVITE_UNAVAILABLE_MESSAGE = "此链接已失效，请联系您的业务经理重新获取"


class InviteUnavailableError(Exception):
    """Raised when an invitation cannot be used, without disclosing why."""


@dataclass(frozen=True, slots=True)
class IssuedToken:
    plaintext: str
    digest: str
    suffix: str


def issue_token() -> IssuedToken:
    plaintext = secrets.token_urlsafe(32)
    return IssuedToken(
        plaintext=plaintext,
        digest=hashlib.sha256(plaintext.encode("utf-8")).hexdigest(),
        suffix=plaintext[-6:],
    )


def issue_invite_token(
    db: Session,
    invite: CustomerImageInvite,
) -> tuple[str, CustomerImageInvite]:
    issued = issue_token()
    invite.token_hash = issued.digest
    invite.token_suffix = issued.suffix
    invite.starts_at = as_utc_naive(invite.starts_at)
    invite.expires_at = as_utc_naive(invite.expires_at)
    if invite.revoked_at is not None:
        invite.revoked_at = as_utc_naive(invite.revoked_at)
    db.add(invite)
    db.flush()
    return issued.plaintext, invite


def resolve_active_invite(
    db: Session,
    plaintext: str,
    now: datetime,
) -> CustomerImageInvite:
    now = as_utc_naive(now)
    digest = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    row = db.scalar(
        select(CustomerImageInvite).where(CustomerImageInvite.token_hash == digest)
    )
    active = (
        row is not None
        and hmac.compare_digest(row.token_hash, digest)
        and row.revoked_at is None
        and as_utc_naive(row.starts_at) <= now < as_utc_naive(row.expires_at)
    )
    if not active:
        raise InviteUnavailableError(INVITE_UNAVAILABLE_MESSAGE)
    return row
