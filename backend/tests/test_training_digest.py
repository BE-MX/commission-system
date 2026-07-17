"""培训速递：发布校验 / 有用幂等 / 草稿清洗 / 可见性 / 文件清理"""

import json
from datetime import date

import pytest
from fastapi import HTTPException

from app.auth.models import ArkUser
from app.training import draft_service, file_service, service
from app.training.models import TrainingDigestFeedback
from app.training.router import publish_digest as publish_endpoint
from app.training.schemas import DigestCreate, DigestSections, DigestUpdate, SectionApplication, SectionHighlight


def _user(db, username="trainee"):
    user = ArkUser(username=username, password_hash="test-hash", real_name=username)
    db.add(user)
    db.flush()
    return user


def _claims(user, perms=("training:read", "training:write")):
    return {"sub": str(user.id), "roles": [], "permissions": list(perms)}


def _create(db, user, title="TikTok AI 投流实战培训"):
    return service.create_digest(
        db,
        DigestCreate(title=title, org="某跨境学院", lecturer="王老师", trained_at=date(2026, 7, 16)),
        user.id,
    )


def _fill_valid_sections(db, digest):
    sections = DigestSections(
        highlights=[
            SectionHighlight(title=f"重点{i}", detail="展开说明" * 10) for i in range(1, 4)
        ],
        applications=[
            SectionApplication(point="用 AI 批量生成投流素材", roles=["电商运营"], first_step="今天挑 3 个在投商品试跑一组 AI 素材"),
        ],
        review="内容偏实操，第二节的素材工作流最值得看，建议运营同事重点读。",
    )
    return service.update_digest(
        db, digest, DigestUpdate(summary="讲了 AI 素材批量生产和投流测品的完整工作流", sections=sections)
    )


# ---------------- 发布校验（★必填分区） ----------------

def test_publish_blocked_when_sections_missing(db):
    user = _user(db)
    digest = _create(db, user)
    problems = service.validate_for_publish(digest)
    assert any("一句话总结" in p for p in problems)
    assert any("重点" in p for p in problems)
    assert any("可应用点" in p for p in problems)
    assert any("参训人点评" in p for p in problems)

    with pytest.raises(HTTPException) as exc:
        publish_endpoint(digest.id, db=db, current_user=_claims(user))
    assert exc.value.status_code == 400
    assert "发布校验未通过" in exc.value.detail


def test_publish_blocked_when_application_incomplete(db):
    user = _user(db)
    digest = _create(db, user)
    _fill_valid_sections(db, digest)
    sections = DigestSections.model_validate(digest.sections_json)
    sections.applications[0].roles = []
    sections.applications[0].first_step = " "
    service.update_digest(db, digest, DigestUpdate(sections=sections))

    problems = service.validate_for_publish(digest)
    assert any("适用岗位" in p for p in problems)
    assert any("落地第一步" in p for p in problems)


def test_publish_success_sets_state_and_pushes(db, monkeypatch):
    user = _user(db)
    digest = _create(db, user)
    _fill_valid_sections(db, digest)

    pushed_calls = []
    monkeypatch.setattr(
        "app.training.push_service.push_published",
        lambda d, name: pushed_calls.append((d.id, name)) or True,
    )
    result = publish_endpoint(digest.id, db=db, current_user=_claims(user))
    assert result["code"] == 200
    assert result["data"]["pushed"] is True
    db.refresh(digest)
    assert digest.status == "published"
    assert digest.published_at is not None
    assert digest.read_minutes >= 1
    assert pushed_calls and pushed_calls[0][0] == digest.id


def test_publish_forbidden_for_other_user(db):
    author = _user(db, "author")
    other = _user(db, "other")
    digest = _create(db, author)
    _fill_valid_sections(db, digest)
    with pytest.raises(HTTPException) as exc:
        publish_endpoint(digest.id, db=db, current_user=_claims(other))
    assert exc.value.status_code == 403


# ---------------- 有用反馈幂等 ----------------

def test_useful_toggle_and_unique_guard(db):
    author = _user(db, "author2")
    reader = _user(db, "reader2")
    digest = _create(db, author)
    _fill_valid_sections(db, digest)
    service.publish_digest(db, digest)

    r1 = service.toggle_useful(db, digest, reader.id)
    assert r1 == {"my_useful": True, "useful_count": 1}
    r2 = service.toggle_useful(db, digest, reader.id)
    assert r2 == {"my_useful": False, "useful_count": 0}
    # 重复行（模拟并发窗口写入）：唯一约束存在
    db.add(TrainingDigestFeedback(digest_id=digest.id, user_id=reader.id, kind="useful"))
    db.commit()
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        db.add(TrainingDigestFeedback(digest_id=digest.id, user_id=reader.id, kind="useful"))
        db.commit()
    db.rollback()


# ---------------- AI 草稿清洗 ----------------

def test_sanitize_draft_clamps_untrusted_ai_output():
    dirty = {
        "summary": "总结" * 200,
        "highlights": [
            {"title": "  合法重点  ", "detail": "d"},
            "不是对象的条目",
            {"title": ""},
            {"title": "2"}, {"title": "3"}, {"title": "4"}, {"title": "5"}, {"title": "6"},
        ],
        "new_insights": ["一条", "", 123, None],
        "applications": [
            {"point": "可用点", "roles": ["电商运营", "不存在的岗位"], "first_step": "试一下"},
            {"point": ""},
        ],
        "methods": [{"name": "方法", "steps": "步骤"}, {"junk": 1}],
        "review": "AI 不许写这个字段",
    }
    out = draft_service._sanitize_draft(dirty)
    assert len(out["summary"]) <= service.MAX_SUMMARY_CHARS
    assert [h["title"] for h in out["highlights"]] == ["合法重点", "2", "3", "4", "5"]
    assert out["new_insights"] == ["一条", "123"]
    assert out["applications"][0]["roles"] == ["电商运营"]
    assert len(out["applications"]) == 1
    assert out["methods"] == [{"name": "方法", "steps": "步骤"}]
    assert "review" not in out


def test_generate_draft_with_mocked_chat(db, monkeypatch):
    user = _user(db, "drafter")
    digest = _create(db, user)
    ai_json = {
        "summary": "讲了 AI 素材工作流",
        "highlights": [{"title": "重点A", "detail": "细节"}],
        "new_insights": [],
        "applications": [{"point": "批量做图", "roles": ["电商运营"], "first_step": "选品试跑"}],
        "methods": [],
    }
    monkeypatch.setattr(
        "app.ai.service.chat",
        lambda db, preset_name, messages, caller_module, caller_user_id=None: {
            "content": "```json\n" + json.dumps(ai_json, ensure_ascii=False) + "\n```"
        },
    )
    draft = draft_service.generate_draft(db, digest, "现场笔记：AI 素材批量生产……")
    assert draft["summary"] == "讲了 AI 素材工作流"
    assert draft["highlights"][0]["title"] == "重点A"


def test_generate_draft_requires_materials(db):
    user = _user(db, "empty")
    digest = _create(db, user)
    with pytest.raises(draft_service.DraftMaterialError):
        draft_service.generate_draft(db, digest, "   ")


# ---------------- 列表可见性 / 浏览计数 ----------------

def test_list_visibility_draft_vs_published(db):
    author = _user(db, "lister")
    other = _user(db, "viewer")
    draft = _create(db, author, title="草稿培训")
    published = _create(db, author, title="已发布培训")
    _fill_valid_sections(db, published)
    service.publish_digest(db, published)

    default_list = service.list_digests(db, page=1, page_size=20, user_id=other.id)
    titles = [i["title"] for i in default_list["items"]]
    assert "已发布培训" in titles and "草稿培训" not in titles

    mine = service.list_digests(db, page=1, page_size=20, user_id=author.id, mine=True)
    assert {i["title"] for i in mine["items"]} == {"草稿培训", "已发布培训"}


def test_view_count_not_incremented_for_creator(db):
    author = _user(db, "vc_author")
    reader = _user(db, "vc_reader")
    digest = _create(db, author)
    _fill_valid_sections(db, digest)
    service.publish_digest(db, digest)

    service.get_detail(db, digest, _claims(author))
    db.refresh(digest)
    assert digest.view_count == 0
    detail = service.get_detail(db, digest, _claims(reader, perms=("training:read",)))
    db.refresh(digest)
    assert digest.view_count == 1
    assert detail["can_edit"] is False


# ---------------- 删除清理落盘文件 ----------------

def test_delete_digest_removes_rows_and_files(db, tmp_path, monkeypatch):
    monkeypatch.setattr(file_service, "storage_root", lambda: tmp_path)
    user = _user(db, "cleaner")
    digest = _create(db, user)
    rel = file_service.store_bytes("讲义.pdf", b"%PDF-fake")
    assert (tmp_path / rel).is_file()
    service.add_file(db, digest, file_name="讲义.pdf", storage_path=rel,
                     file_size=9, mime_type="application/pdf", uploaded_by=user.id)

    service.delete_digest(db, digest)
    assert not (tmp_path / rel).exists()
    remaining = service.list_digests(db, page=1, page_size=20, user_id=user.id, mine=True)
    assert remaining["total"] == 0
