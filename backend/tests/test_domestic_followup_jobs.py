"""后台 AI/OCR 线程池：并发上限、异常不吞（红线 6）、预置模型绑定视觉 provider。"""
from app.domestic_followup import jobs


def test_pool_caps_background_ai_at_three_workers():
    assert jobs.MAX_WORKERS == 3
    assert jobs._executor._max_workers == 3


def test_submit_runs_job_with_args():
    seen = []
    jobs.submit(lambda a, b: seen.append((a, b)), 1, "x").result(timeout=5)
    assert seen == [(1, "x")]


def test_failed_job_is_logged_and_printed(capsys, caplog):
    def boom(followup_id):
        raise RuntimeError("model down")

    assert jobs.submit(boom, 42).result(timeout=5) is None
    out = capsys.readouterr().out
    assert "background job boom failed" in out and "RuntimeError" in out
    assert any("boom" in r.getMessage() for r in caplog.records if r.levelname == "WARNING")


def test_followup_presets_bind_same_vision_model_as_invoice_screenshot(monkeypatch):
    from app.bootstrap import seed_ai

    created = {}
    monkeypatch.setattr(seed_ai, "_auto_create_preset", lambda **kw: created.setdefault(kw["preset_name"], kw))
    seed_ai._init_domestic_followup_presets()
    for name in ("domestic_followup_parse", "domestic_followup_ocr"):
        kw = created[name]
        assert kw["provider_name_hint"] == seed_ai._TEAMROUTER_CHAT_PROVIDER
        assert kw["model_name_hint"] == seed_ai._VISION_MODEL
        assert kw["require_direct_anthropic"] is True and kw["allow_provider_fallback"] is False
