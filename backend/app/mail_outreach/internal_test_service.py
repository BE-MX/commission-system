"""Explicit internal acceptance mail, restricted to individually enabled addresses."""
from app.core.config import get_settings
from app.mail_outreach.errors import forbidden

TEST_PREFIX = "[ARK INTERNAL TEST]"


def is_internal_test(revision):
    return bool(revision and (revision.evidence_snapshot_json or {}).get("internal_test"))


def require_internal_test_recipient(user, email):
    allowed = {value.strip().lower() for value in get_settings().MAIL_OUTREACH_ALLOWED_RECIPIENTS.split(",") if value.strip()}
    if "super_admin" not in user.get("roles", []) and "mail_outreach:admin" not in user.get("permissions", []):
        raise forbidden("内部试发仅限邮件管理员", error_code="internal_test_forbidden")
    # A production wildcard never grants permission to test a real customer address.
    if email.lower() not in allowed:
        raise forbidden("内部试发收件人必须单独列入测试白名单", error_code="internal_test_recipient_forbidden")


def require_internal_test_content(subject, claims):
    if not subject.startswith(TEST_PREFIX) or claims:
        raise forbidden("内部试发必须保留测试主题标记且不得包含客户主张", error_code="internal_test_content_invalid")
