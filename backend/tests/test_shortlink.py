"""Regression tests for short-link reuse, collision retries and fallbacks."""

from datetime import timedelta
from unittest.mock import Mock, call

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.time import beijing_now
from app.models.short_link import ArkShortLink
from app.utils import shortlink


@pytest.fixture(autouse=True)
def shortlink_base_url(monkeypatch):
    monkeypatch.setattr(shortlink.settings, "SHORT_LINK_BASE_URL", "https://s.example.com/")


@pytest.fixture
def shortlink_sessions(engine, monkeypatch):
    # The shared engine fixture uses StaticPool, so every session sees the same
    # in-memory SQLite database, including sessions opened inside the utility.
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(shortlink, "SessionLocal", factory)
    return factory


def test_generate_short_link_creates_six_character_code(shortlink_sessions):
    url = "https://example.com/orders/first"

    result = shortlink.generate_short_link(url)

    prefix = "https://s.example.com/s/"
    assert result.startswith(prefix)
    code = result.removeprefix(prefix)
    assert len(code) == 6
    with shortlink_sessions() as db:
        row = db.query(ArkShortLink).one()
        assert row.short_code == code
        assert row.original_url == url


def test_generate_short_link_reuses_recent_url(shortlink_sessions):
    url = "https://example.com/orders/recent"

    first = shortlink.generate_short_link(url)
    second = shortlink.generate_short_link(url)

    assert second == first
    with shortlink_sessions() as db:
        row = db.query(ArkShortLink).one()
        assert first == f"https://s.example.com/s/{row.short_code}"
        assert row.original_url == url


def test_generate_short_link_does_not_reuse_url_older_than_seven_days(
    shortlink_sessions, monkeypatch
):
    url = "https://example.com/orders/expired"
    with shortlink_sessions() as db:
        db.add(ArkShortLink(
            short_code="aaaaaa", original_url=url,
            created_at=beijing_now() - timedelta(days=8),
        ))
        db.commit()
    compute_code = Mock(return_value="bbbbbb")
    monkeypatch.setattr(shortlink, "_compute_code", compute_code)

    result = shortlink.generate_short_link(url)

    assert result == "https://s.example.com/s/bbbbbb"
    compute_code.assert_called_once_with(url, salt="0")
    with shortlink_sessions() as db:
        rows = db.query(ArkShortLink).all()
        assert len(rows) == 2
        assert {row.short_code for row in rows} == {"aaaaaa", "bbbbbb"}
        assert all(row.original_url == url for row in rows)


def test_generate_short_link_retries_two_collisions(shortlink_sessions, monkeypatch):
    occupied_url = "https://example.com/orders/occupied"
    url = "https://example.com/orders/retry"
    with shortlink_sessions() as db:
        db.add(ArkShortLink(short_code="aaaaaa", original_url=occupied_url))
        db.commit()
    compute_code = Mock(side_effect=["aaaaaa", "aaaaaa", "bbbbbb"])
    monkeypatch.setattr(shortlink, "_compute_code", compute_code)

    result = shortlink.generate_short_link(url)

    assert result == "https://s.example.com/s/bbbbbb"
    assert compute_code.call_args_list == [call(url, salt=str(i)) for i in range(3)]
    with shortlink_sessions() as db:
        rows = db.query(ArkShortLink).all()
        assert len(rows) == 2
        assert {row.short_code: row.original_url for row in rows} == {
            "aaaaaa": occupied_url,
            "bbbbbb": url,
        }


def test_generate_short_link_falls_back_after_all_collisions(shortlink_sessions, monkeypatch):
    occupied_url = "https://example.com/orders/occupied"
    url = "https://example.com/orders/exhausted"
    with shortlink_sessions() as db:
        db.add(ArkShortLink(short_code="aaaaaa", original_url=occupied_url))
        db.commit()
    compute_code = Mock(return_value="aaaaaa")
    monkeypatch.setattr(shortlink, "_compute_code", compute_code)

    assert shortlink.generate_short_link(url) == url

    assert compute_code.call_args_list == [call(url, salt=str(i)) for i in range(5)]
    with shortlink_sessions() as db:
        row = db.query(ArkShortLink).one()
        assert row.short_code == "aaaaaa"
        assert row.original_url == occupied_url


def test_generate_short_link_falls_back_on_query_error(monkeypatch):
    url = "https://example.com/orders/query-error"
    db = Mock()
    db.query.side_effect = RuntimeError("test query failure")
    factory = Mock(return_value=db)
    monkeypatch.setattr(shortlink, "SessionLocal", factory)

    assert shortlink.generate_short_link(url) == url

    factory.assert_called_once_with()
    db.query.assert_called_once_with(ArkShortLink)
    db.rollback.assert_called_once_with()
    db.close.assert_called_once_with()


def test_generate_short_link_empty_url_skips_database(monkeypatch):
    factory = Mock(side_effect=AssertionError("empty URL must not open a session"))
    monkeypatch.setattr(shortlink, "SessionLocal", factory)

    assert shortlink.generate_short_link("") == "https://s.example.com"

    factory.assert_not_called()
