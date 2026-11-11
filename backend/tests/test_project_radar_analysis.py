import json

from app.project_radar.analysis import analyze_target
from app.project_radar.models import RadarTarget
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
