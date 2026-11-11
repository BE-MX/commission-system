from datetime import datetime

import pytest

from app.project_radar.classify import rule_level, should_push
from app.project_radar.urls import canonicalize_url, external_datetime, parse_input


@pytest.mark.parametrize("raw", [
    "https://github.com/Microsoft/MarkItDown.git?utm_source=x",
    "https://github.com/microsoft/markitdown/tree/main/packages",
    "github.com/microsoft/markitdown#readme",
])
def test_github_url_canonicalization_ignores_transport_variants(raw):
    assert canonicalize_url(raw) == "https://github.com/microsoft/markitdown"


def test_website_canonicalization_keeps_meaningful_path_and_query():
    assert canonicalize_url("HTTPS://WWW.Example.com/changelog/?utm_source=x&page=2") == (
        "https://example.com/changelog?page=2"
    )


def test_input_extracts_multiple_urls_notes_and_tags():
    parsed = parse_input("https://github.com/a/b 和 https://example.com 对比看看 #Agent #知识库")
    assert parsed["urls"] == ["https://github.com/a/b", "https://example.com"]
    assert parsed["note"] == "和 对比看看"
    assert parsed["tags"] == ["Agent", "知识库"]


@pytest.mark.parametrize("server_zone", ["UTC", "America/New_York"])
def test_release_time_converts_to_beijing_before_dropping_offset(monkeypatch, server_zone):
    monkeypatch.setenv("TZ", server_zone)
    assert external_datetime("2026-11-10T16:00:00Z") == datetime(2026, 11, 11, 0, 0)
    assert external_datetime("2026-11-10T23:00:00-08:00") == datetime(2026, 11, 11, 15, 0)


def test_rule_classification_distinguishes_major_breaking_normal_and_prerelease():
    assert rule_level("v1.9.0", "v2.0.0") == "key"
    assert rule_level("v1.1.0", "v1.2.0", "Deprecated old API") == "key"
    assert rule_level("v1.1.0", "v1.2.0", "Add EPUB support") == "normal"
    assert rule_level("v1.1.0", "v1.2.0-rc.1", "Release candidate") == "noise"
    assert rule_level(signal="commit") == "noise"
    assert rule_level(archived=True) == "key"


def test_watch_levels_and_normal_update_cooldown():
    assert should_push("normal", "normal") is False
    assert should_push("normal", "key") is True
    assert should_push("key", "normal", days_since_normal_push=3) is False
    assert should_push("key", "normal", days_since_normal_push=7) is True
    assert should_push("adopted", "normal") is False
    assert should_push("adopted", "key", "security fix for CVE-2026-1") is True
    assert should_push("adopted", "key", "new extension API") is False
    assert should_push("silent", "key") is False
