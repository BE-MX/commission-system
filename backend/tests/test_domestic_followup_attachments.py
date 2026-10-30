import io
from contextlib import nullcontext
from datetime import date

import pytest
from PIL import Image

from app.domestic_followup import attachment_service
from app.domestic_followup.models import DomesticFollowup, DomesticFollowupAttachment
from tests.domestic_followup_helpers import make_user


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 20), "white").save(buf, format="PNG")
    return buf.getvalue()


def _gif() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), "white").save(buf, format="GIF")
    return buf.getvalue()


@pytest.fixture
def storage(tmp_path, monkeypatch):
    from app.domestic import file_service

    monkeypatch.setattr(file_service, "storage_root", lambda: tmp_path)
    monkeypatch.setattr(file_service.cloud_files, "put_bytes", lambda *a, **k: False)
    monkeypatch.setattr(file_service.cloud_files, "read_path", lambda _ns, rel, root: root / rel)
    return tmp_path


def test_upload_then_bind_to_own_draft(db, storage):
    user = make_user(db, "fu_att_a")
    att = attachment_service.upload(db, user.id, "chat.png", "image/png", _png())
    assert att.followup_id is None and att.ocr_status == "pending"
    followup = DomesticFollowup(author_user_id=user.id, followup_date=date(2026, 10, 30), request_id="r-att-a")
    db.add(followup)
    db.flush()
    attachment_service.bind(db, user.id, followup.id, [att.id])
    assert att.followup_id == followup.id and att.seq == 1


def test_cannot_bind_someone_elses_attachment(db, storage):
    owner = make_user(db, "fu_att_b1")
    thief = make_user(db, "fu_att_b2")
    att = attachment_service.upload(db, owner.id, "chat.png", "image/png", _png())
    followup = DomesticFollowup(author_user_id=thief.id, followup_date=date(2026, 10, 30), request_id="r-att-b")
    db.add(followup)
    db.flush()
    with pytest.raises(PermissionError):
        attachment_service.bind(db, thief.id, followup.id, [att.id])


def test_cannot_bind_to_someone_elses_draft(db, storage):
    owner = make_user(db, "fu_att_e1")
    other = make_user(db, "fu_att_e2")
    att = attachment_service.upload(db, other.id, "chat.png", "image/png", _png())
    followup = DomesticFollowup(author_user_id=owner.id, followup_date=date(2026, 10, 30), request_id="r-att-e")
    db.add(followup)
    db.flush()
    with pytest.raises(PermissionError):
        attachment_service.bind(db, other.id, followup.id, [att.id])


def test_rebind_releases_unselected(db, storage):
    user = make_user(db, "fu_att_f")
    a1 = attachment_service.upload(db, user.id, "a.png", "image/png", _png())
    a2 = attachment_service.upload(db, user.id, "b.png", "image/png", _png())
    followup = DomesticFollowup(author_user_id=user.id, followup_date=date(2026, 10, 30), request_id="r-att-f")
    db.add(followup)
    db.flush()
    attachment_service.bind(db, user.id, followup.id, [a1.id, a2.id])
    attachment_service.bind(db, user.id, followup.id, [a2.id])
    assert a1.followup_id is None and a2.followup_id == followup.id and a2.seq == 1


def test_bind_to_own_other_record_rejected_with_specific_message(db, storage):
    user = make_user(db, "fu_att_j")
    att = attachment_service.upload(db, user.id, "a.png", "image/png", _png())
    first = DomesticFollowup(author_user_id=user.id, followup_date=date(2026, 10, 30), request_id="r-att-j1")
    second = DomesticFollowup(author_user_id=user.id, followup_date=date(2026, 10, 30), request_id="r-att-j2")
    db.add_all([first, second])
    db.flush()
    attachment_service.bind(db, user.id, first.id, [att.id])
    with pytest.raises(PermissionError, match="另一条记录"):
        attachment_service.bind(db, user.id, second.id, [att.id])


def test_rejects_fake_image(db, storage):
    user = make_user(db, "fu_att_g")
    with pytest.raises(ValueError, match="图片"):
        attachment_service.upload(db, user.id, "x.png", "image/png", b"not really a png")


def test_rejects_non_image(db, storage):
    user = make_user(db, "fu_att_c")
    with pytest.raises(ValueError):
        attachment_service.upload(db, user.id, "x.exe", "application/octet-stream", b"MZ")


def test_rejects_disguised_gif_as_png(db, storage):
    user = make_user(db, "fu_att_i")
    with pytest.raises(ValueError, match="PNG"):
        attachment_service.upload(db, user.id, "x.png", "image/png", _gif())


def test_ocr_job_fills_text_and_survives_failures(db, storage, monkeypatch):
    user = make_user(db, "fu_att_d")
    ok_att = attachment_service.upload(db, user.id, "a.png", "image/png", _png())
    bad_att = attachment_service.upload(db, user.id, "b.png", "image/png", _png())
    db.commit()  # run_ocr 失败分支会 rollback，先提交，避免把上传记录一起回滚

    def fake_chat(**kwargs):
        kwargs["db"].commit()  # 真实 facade 写调用日志会提交事务；打桩也要模拟，防 savepoint 类回归
        assert kwargs["snapshot_mode"] == "metadata"  # 截图隐私：不落全量快照
        if kwargs["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/png") and fake_chat.calls == 0:
            fake_chat.calls += 1
            return {"content": '{"text": "客户：退货率太高", "unreadable": ["语音条 3″"]}'}
        raise TimeoutError("slow")
    fake_chat.calls = 0
    monkeypatch.setattr(attachment_service, "chat", fake_chat)

    attachment_service.run_ocr([ok_att.id, bad_att.id], session_factory=lambda: nullcontext(db))
    assert ok_att.ocr_status == "done" and "退货率" in ok_att.ocr_text
    assert ok_att.unreadable_note == "语音条 3″"
    assert bad_att.ocr_status == "failed"


def test_run_ocr_survives_session_get_crash(db, storage, monkeypatch):
    user = make_user(db, "fu_att_h")
    crash_att = attachment_service.upload(db, user.id, "a.png", "image/png", _png())
    ok_att = attachment_service.upload(db, user.id, "b.png", "image/png", _png())
    db.commit()

    def fake_chat(**kwargs):
        kwargs["db"].commit()
        return {"content": '{"text": "ok"}'}
    monkeypatch.setattr(attachment_service, "chat", fake_chat)

    original_get = db.get

    def flaky_get(model, ident, *args, **kwargs):
        if model is DomesticFollowupAttachment and ident == crash_att.id:
            raise RuntimeError("db hiccup")
        return original_get(model, ident, *args, **kwargs)

    monkeypatch.setattr(db, "get", flaky_get)
    attachment_service.run_ocr([crash_att.id, ok_att.id], session_factory=lambda: nullcontext(db))
    monkeypatch.setattr(db, "get", original_get)

    assert ok_att.ocr_status == "done"  # 第一张彻底取不出来，后面这张仍要被处理
    assert crash_att.ocr_status == "pending"  # 连取附件都失败，没法标记，保持原状不假装成功
