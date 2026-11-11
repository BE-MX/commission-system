import json

import httpx
import pytest

from app.ai.models import AiCallLog, AiPreset, AiProvider
from app.project_radar.analysis import analyze_target, classify_update
from app.project_radar.models import RadarTarget
from app.project_radar.resolve import extract_name_candidates
from app.system.models import SysDict


def test_ai_receives_runtime_dictionaries_and_cannot_write_version(db, monkeypatch):
    db.add_all([
        SysDict(type="project_radar_type", code="open_source", label="开源项目", sort=1, is_active=True),
        SysDict(type="ark_module", code="module_1", label="知识库", sort=1, is_active=True),
    ])
    target = RadarTarget(canonical_url="https://github.com/a/b", url_hash="x" * 64,
                         kind="repo", title="b", item_type="other", one_liner="待补充",
                         ark_modules=[], last_update_summary=[], version="v9.0.0")
    db.add(target)
    db.flush()
    prompts = []

    def fake_chat(**kwargs):
        prompts.append(kwargs["messages"][0]["content"])
        return {"content": json.dumps({
            "title": "Project B", "item_type": "开源项目", "one_liner": "文件转 Markdown",
            "description": "详细说明", "version": "v999",
            "ark_modules": [{"name": "知识库", "reason": "文档预处理", "effort": "低"},
                            {"name": "不存在模块", "reason": "不能采用"}],
        })}

    monkeypatch.setattr("app.project_radar.analysis.chat", fake_chat)
    result = analyze_target(db, target, "untrusted readme")
    prompt = json.loads(prompts[0])
    assert prompt["allowed_item_types"] == ["开源项目"]
    assert prompt["allowed_ark_modules"] == ["知识库"]
    assert result["analyzed"] is True and target.version == "v9.0.0"
    assert target.item_type == "open_source" and len(target.ark_modules) == 1

def test_radar_ai_uses_enabled_presets_from_migration(db, monkeypatch):
    provider = AiProvider(name="Radar test provider", api_base="https://example.com/v1")
    db.add(provider)
    db.flush()
    db.add_all([
        AiPreset(preset_name="ark_project_radar_analyze", provider_id=provider.id,
                 model="radar-analysis-model", is_enabled=True),
        AiPreset(preset_name="ark_project_radar_update_classify", provider_id=provider.id,
                 model="radar-review-model", is_enabled=True),
    ])
    db.commit()

    responses = iter([
        {"title": "Project B", "description": "Converts documents to Markdown"},
        TimeoutError("name extraction deadline"),
        {"names": ["Project B"]},
        httpx.ReadTimeout("classification timed out"),
        {"level": "key", "reason": "Breaking API change", "summary": ["Removed legacy API"]},
    ])

    def fake_post_json(*args, **kwargs):
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return {"choices": [{"message": {"content": json.dumps(response)}}]}

    monkeypatch.setattr("app.ai.call_service.post_json", fake_post_json)
    target = RadarTarget(title="b", item_type="other", one_liner="b")
    analyzed = analyze_target(db, target, "Project B converts documents to Markdown.")
    names = extract_name_candidates(db, "I use Project B.")
    review = classify_update(
        db, from_version="v1.0.0", to_version="v2.0.0",
        release_notes="Removed the legacy API.", level="normal",
    )

    assert analyzed["analyzed"] and target.description == "Converts documents to Markdown"
    assert names == ["Project B"]
    assert review["level"] == "key" and review["reason"] == "Breaking API change"
    logs = db.query(AiCallLog).order_by(AiCallLog.id).all()
    assert [(log.preset_name, log.model, log.status) for log in logs] == [
        ("ark_project_radar_analyze", "radar-analysis-model", "success"),
        ("ark_project_radar_analyze", "radar-analysis-model", "error"),
        ("ark_project_radar_analyze", "radar-analysis-model", "success"),
        ("ark_project_radar_update_classify", "radar-review-model", "error"),
        ("ark_project_radar_update_classify", "radar-review-model", "success"),
    ]


@pytest.mark.parametrize(("failures", "statuses", "analyzed"), [
    ([httpx.ReadTimeout], ["error", "success"], True),
    ([httpx.ReadTimeout, TimeoutError], ["error", "error"], False),
    ([RuntimeError], ["error"], False),
])
def test_radar_analysis_retries_only_one_timeout(db, monkeypatch, failures, statuses, analyzed):
    provider = AiProvider(name="Radar retry provider", api_base="https://example.com/v1")
    db.add(provider)
    db.flush()
    db.add(AiPreset(preset_name="ark_project_radar_analyze", provider_id=provider.id,
                    model="radar-model", is_enabled=True))
    db.commit()
    calls = []

    def post(*args, **kwargs):
        calls.append(kwargs["body"])
        if len(calls) <= len(failures):
            raise failures[len(calls) - 1]("request failed")
        return {"choices": [{"message": {"content": '{"description":"Readme analysis"}'}}]}

    monkeypatch.setattr("app.ai.call_service.post_json", post)
    target = RadarTarget(title="Original", item_type="other", one_liner="Original")
    assert analyze_target(db, target, "readme")["analyzed"] is analyzed
    assert target.description == ("Readme analysis" if analyzed else None)
    assert len(calls) == len(statuses)
    assert all(body == calls[0] for body in calls)
    assert [log.status for log in db.query(AiCallLog).order_by(AiCallLog.id)] == statuses
