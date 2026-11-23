# scripts/devlog/tests/test_rules.py
import pytest

from classify import agent_of, item_type, module_of
from redact import redact_title, safe_identifier


@pytest.mark.parametrize("raw, expected", [
    ("Notify ops@leshinehair.com on failure", "Notify [邮箱] on failure"),
    ("Fix total 146,352.55 USD rounding", "Fix total [金额] rounding"),
    ("Call +86 138 0013 8000 back", "Call [号码] back"),
    ("Repair order 240611093 outbound", "Repair order [编号] outbound"),
    ("Rotate sk-abcdefghijklmnop key", "Rotate [密钥] key"),
    ("Fix 1751 outbound name", "Fix 1751 outbound name"),
])
def test_redact(raw, expected):
    assert redact_title(raw) == expected


def test_redact_truncates_to_40_chars():
    assert len(redact_title("Implement " + "very long subject " * 5)) == 40


def test_credentials_redacted_before_truncation():
    assert "short_secret" not in redact_title("Fix password=short_secret")
    assert "api_key" not in redact_title("Rotate api_key=short-secret")


def test_private_or_invalid_branch_identifiers_are_hashed():
    assert safe_identifier("codex/order-240611093").startswith("private-")
    assert safe_identifier("codex/客户名字").startswith("private-")
    assert safe_identifier("codex/cross-border-review") == "codex/cross-border-review"


def test_item_type_priority():
    assert item_type(["Add cross border review", "Fix typo"]) == "feature"
    assert item_type(["Fix invoice rounding"]) == "bug"
    assert item_type(["Backfill receipt dates"]) == "data"
    assert item_type(["Speed up invoice matching"]) == "improve"


def test_item_type_by_paths_when_subjects_neutral():
    assert item_type(["Update notes"], [("M", "docs/handoff.md")]) == "docs"
    assert item_type(["Tune retention"], [("M", "deploy/publish.py")]) == "ops"


def test_module_of_counts_domain_dirs():
    files = [("M", "backend/app/cross_border/a.py"), ("M", "backend/app/cross_border/b.py"),
             ("A", "frontend/src/views/cross_border/X.vue"), ("M", "backend/app/core/config.py")]
    assert module_of(files) == "cross_border"
    assert module_of([("M", "docs/a.md")]) == ""


def test_agent_of():
    assert agent_of("codex/fix-x", "") == "codex"
    assert agent_of(None, "Claude Opus <noreply@anthropic.com>") == "claude"
    assert agent_of(None, "") == "unknown"
