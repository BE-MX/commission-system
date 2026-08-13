from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.order_intelligence import brief_job_service
from app.order_intelligence.models import OrderIntelligenceBriefJob
from app.order_intelligence.service import AnalysisScope
from app.order_intelligence.filtering import AnalysisFilters


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    OrderIntelligenceBriefJob.__table__.create(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


def _prepare(db, owner=7):
    return brief_job_service.prepare_job(
        db,
        owner,
        AnalysisScope("all", None, None, True),
        date(2026, 1, 1),
        date(2026, 8, 12),
        "executive",
    )


def test_prepare_job_reuses_active_job_and_prevents_second_generation(db):
    first, first_started = _prepare(db)
    second, second_started = _prepare(db)

    assert first_started is True
    assert second_started is False
    assert second.id == first.id
    assert db.query(OrderIntelligenceBriefJob).count() == 1


def test_prepare_job_recovers_from_concurrent_unique_key_race(monkeypatch, db):
    first, _ = _prepare(db)
    original = brief_job_service.get_active_job
    calls = 0

    def miss_once(session, owner_user_id):
        nonlocal calls
        calls += 1
        return None if calls == 1 else original(session, owner_user_id)

    monkeypatch.setattr(brief_job_service, "get_active_job", miss_once)
    second, should_start = _prepare(db)

    assert should_start is False
    assert second.id == first.id
    assert db.query(OrderIntelligenceBriefJob).count() == 1


def test_terminal_job_releases_active_key_for_next_generation(db):
    first, _ = _prepare(db)
    first.status = "succeeded"
    first.active_key = None
    db.commit()

    second, should_start = _prepare(db)

    assert should_start is True
    assert second.id != first.id


def test_stale_active_job_is_failed_and_unlocks_generation(db):
    row, _ = _prepare(db)
    row.status = "running"
    row.updated_at = datetime.now() - timedelta(minutes=31)
    db.commit()

    assert brief_job_service.get_active_job(db, 7) is None
    db.refresh(row)
    assert row.status == "failed"
    assert row.active_key is None
    assert "30 分钟" in row.error_message


def test_job_result_is_owner_scoped(db):
    row, _ = _prepare(db, owner=7)

    with pytest.raises(brief_job_service.BriefJobNotFoundError):
        brief_job_service.get_job(db, 8, row.id)


def test_latest_job_restores_terminal_result(db):
    row, _ = _prepare(db)
    row.status = "succeeded"
    row.active_key = None
    row.content = "已完成"
    db.commit()

    assert brief_job_service.get_active_job(db, 7) is None
    assert brief_job_service.get_latest_job(db, 7).content == "已完成"


def test_execute_job_persists_result_and_serializes_evidence(monkeypatch, db):
    row, _ = _prepare(db)
    monkeypatch.setattr(
        brief_job_service.analysis_service,
        "build_ai_brief",
        lambda **_kwargs: {
            "content": "经营简报",
            "source": "ai",
            "evidence": {"window_end": date(2026, 8, 12)},
        },
    )

    brief_job_service.execute_job(db, row.id)

    result = brief_job_service.get_job(db, 7, row.id)
    assert result.status == "succeeded"
    assert result.active_key is None
    assert result.content == "经营简报"
    assert result.evidence == {"window_end": "2026-08-12"}


def test_job_snapshot_preserves_multidimensional_filters(db):
    row, should_start = brief_job_service.prepare_job(
        db,
        9,
        AnalysisScope("all", None, None, True),
        date(2026, 1, 1),
        date(2026, 8, 12),
        "executive",
        AnalysisFilters.build(
            countries=["美国"],
            models=["Genius Weft"],
            colors=["#1B"],
            sources=["alibaba_inquiry"],
        ),
    )

    serialized = brief_job_service.serialize_job(row)

    assert should_start is True
    assert serialized["request_context"] == {
        "team": "",
        "user_id": "",
        "countries": ["美国"],
        "models": ["Genius Weft"],
        "colors": ["#1B"],
        "sources": ["alibaba_inquiry"],
    }


def test_execute_job_forwards_snapshot_filters(monkeypatch, db):
    row, _ = brief_job_service.prepare_job(
        db,
        10,
        AnalysisScope("all", None, None, True),
        date(2026, 1, 1),
        date(2026, 8, 12),
        "executive",
        AnalysisFilters.build(countries=["德国"], sources=["social_owned"]),
    )
    captured = {}

    def build(**kwargs):
        captured.update(kwargs)
        return {"content": "完成", "source": "ai", "evidence": {}}

    monkeypatch.setattr(brief_job_service.analysis_service, "build_ai_brief", build)

    brief_job_service.execute_job(db, row.id)

    assert captured["analysis_filters"].countries == ("德国",)
    assert captured["analysis_filters"].sources == ("social_owned",)
