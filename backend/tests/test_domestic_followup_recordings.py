"""跟进录音：上传校验、绑定、权限、worker 领取/成功删音频/离线不计次、txt 下载、AI 整理引用核对。"""
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.core.time import beijing_now
from app.domestic_followup import recording_organize_service, recording_service, recording_worker
from app.domestic_followup.models import DomesticFollowup, DomesticFollowupRecording
from tests.domestic_followup_helpers import followup_client, make_user, seed_dicts

AUDIO = b"ID3fake-audio-bytes" * 10


class FakeCloud:
    """put_bytes 写进 tmp 目录；delete 删文件；模拟 domestic 已接入 COS。"""

    def __init__(self, root: Path):
        self.root = root
        self.deleted = []

    def put_bytes(self, domain, key, content, content_type=None):
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return True

    def read_path(self, domain, key, root):
        return self.root / key

    def delete(self, domain, key, root):
        self.deleted.append(key)
        (self.root / key).unlink(missing_ok=True)


@pytest.fixture
def cloud(tmp_path, monkeypatch):
    from app.domestic import file_service

    fake = FakeCloud(tmp_path)
    monkeypatch.setattr(file_service, "storage_root", lambda: tmp_path)
    monkeypatch.setattr(file_service.cloud_files, "read_path", fake.read_path)
    for module in (recording_service.cloud_files, recording_worker.cloud_files):
        monkeypatch.setattr(module, "put_bytes", fake.put_bytes)
        monkeypatch.setattr(module, "delete", fake.delete)

    class Store:
        def __init__(self, domain):
            pass

        def download(self, key, destination, max_bytes, expected_sha256=None):
            Path(destination).write_bytes((tmp_path / key).read_bytes())

    monkeypatch.setattr(recording_worker, "CosObjectStore", Store)
    monkeypatch.setattr(recording_worker, "get_settings", lambda: type("S", (), {
        "COS_CACHE_ROOT": str(tmp_path / "cache"), "ASR_TIMEOUT_SECONDS": 60, "ASR_MAX_ATTEMPTS": 3,
        "ASR_BASE_URL": "http://asr.test", "ASR_API_KEY": "k"})())
    return fake


def _user(db, name):
    user = make_user(db, name)
    return user, {"sub": str(user.id), "roles": [], "permissions": ["domestic_followup:read", "domestic_followup:write"]}


def _draft(db, user, request_id):
    row = DomesticFollowup(author_user_id=user.id, followup_date=date(2026, 11, 25), request_id=request_id)
    db.add(row)
    db.flush()
    return row


def _session(db):
    class Ctx:
        def __enter__(self):
            return db

        def __exit__(self, *exc):
            return False

    return lambda: Ctx()


def test_upload_validates_extension_size_and_mime(db, cloud):
    _, cu = _user(db, "rec_v")
    with pytest.raises(ValueError, match="只支持录音"):
        recording_service.upload(db, cu, "a.exe", "", AUDIO)
    with pytest.raises(ValueError, match="为空"):
        recording_service.upload(db, cu, "a.m4a", "", b"")
    with pytest.raises(ValueError, match="不匹配"):
        recording_service.upload(db, cu, "a.mp3", "image/png", AUDIO)
    row = recording_service.upload(db, cu, "call.m4a", "application/octet-stream", AUDIO, hotwords="接发, 天才发帘，接发")
    assert row.asr_status == "queued" and row.file_key.startswith("audio/") and row.hotwords == "接发,天才发帘"
    assert (cloud.root / row.file_key).read_bytes() == AUDIO


def test_upload_refuses_when_domestic_not_on_cloud(db, cloud, monkeypatch):
    _, cu = _user(db, "rec_nocos")
    monkeypatch.setattr(recording_service.cloud_files, "put_bytes", lambda *a, **k: False)
    with pytest.raises(ValueError, match="共享云存储"):
        recording_service.upload(db, cu, "call.m4a", "", AUDIO)


def test_same_unbound_audio_reuses_row(db, cloud):
    _, cu = _user(db, "rec_dup")
    first = recording_service.upload(db, cu, "call.m4a", "", AUDIO)
    second = recording_service.upload(db, cu, "call-copy.m4a", "", AUDIO)
    assert first.id == second.id


def test_bind_rules_and_per_followup_limit(db, cloud):
    owner, cu = _user(db, "rec_b1")
    other, cu2 = _user(db, "rec_b2")
    rec = recording_service.upload(db, cu, "a.m4a", "", AUDIO)
    theirs = _draft(db, other, "rec-b-other")
    with pytest.raises(PermissionError):
        recording_service.bind(db, other.id, theirs.id, [rec.id])
    mine = _draft(db, owner, "rec-b-mine")
    recording_service.bind(db, owner.id, mine.id, [rec.id])
    assert rec.followup_id == mine.id and rec.seq == 1
    with pytest.raises(ValueError, match="最多 3"):
        recording_service.bind(db, owner.id, mine.id, [1, 2, 3, 4])
    with pytest.raises(PermissionError):
        recording_service.upload(db, cu2, "b.m4a", "", AUDIO + b"x", followup_id=mine.id)


def test_upload_directly_onto_own_confirmed_record(db, cloud):
    owner, cu = _user(db, "rec_c")
    record = _draft(db, owner, "rec-c")
    record.status = "confirmed"
    db.flush()
    rec = recording_service.upload(db, cu, "c.m4a", "", AUDIO, followup_id=record.id)
    assert rec.followup_id == record.id and rec.seq == 1


def test_stranger_cannot_read_unbound_recording(db, cloud):
    _, cu = _user(db, "rec_p1")
    _, cu2 = _user(db, "rec_p2")
    rec = recording_service.upload(db, cu, "a.m4a", "", AUDIO)
    with pytest.raises(PermissionError):
        recording_service.get_readable(db, cu2, rec.id)


def test_worker_success_writes_txt_and_deletes_audio(db, cloud):
    owner, cu = _user(db, "rec_w1")
    rec = recording_service.upload(db, cu, "w.m4a", "", AUDIO)
    db.commit()
    audio_key = rec.file_key
    result = {"text": "你好我想订接发", "duration_sec": 65.2, "elapsed_sec": 12,
              "segments": [{"start": 0.1, "end": 3.0, "speaker": "S01", "text": "你好"},
                           {"start": 61.0, "end": 64.0, "speaker": "S02", "text": "我想订接发"}]}
    assert recording_worker.run_once(_session(db), transcriber=lambda job: result) == "done"
    db.refresh(rec)
    assert rec.asr_status == "done" and rec.transcript_chars == 7 and rec.duration_sec == 65
    assert rec.file_key is None and rec.audio_deleted_at is not None and audio_key in cloud.deleted
    txt = (cloud.root / rec.transcript_key).read_text(encoding="utf-8")
    assert "[00:01:01] S02：我想订接发" in txt and "机器转写" in txt
    content, name = recording_service.transcript_download(db, cu, rec.id)
    assert content.decode("utf-8") == txt and name.endswith("_转写.txt")


def test_worker_offline_requeues_without_counting(db, cloud):
    _, cu = _user(db, "rec_w2")
    rec = recording_service.upload(db, cu, "o.m4a", "", AUDIO)
    db.commit()

    def offline(job):
        raise recording_worker.AsrOffline("ConnectError")

    assert recording_worker.run_once(_session(db), transcriber=offline) == "offline"
    db.refresh(rec)
    assert rec.asr_status == "queued" and rec.attempts == 0 and rec.file_key
    assert rec.next_attempt_at > beijing_now()
    assert recording_worker.run_once(_session(db), transcriber=offline) == "idle"


def test_worker_failures_count_then_fail_and_keep_audio(db, cloud):
    _, cu = _user(db, "rec_w3")
    rec = recording_service.upload(db, cu, "f.m4a", "", AUDIO)
    db.commit()

    def broken(job):
        raise RuntimeError("ASR HTTP 500")

    for expected in (1, 2, 3):
        rec.next_attempt_at = beijing_now() - timedelta(seconds=1)
        db.commit()
        recording_worker.run_once(_session(db), transcriber=broken)
        db.refresh(rec)
        assert rec.attempts == expected
    assert rec.asr_status == "failed" and rec.file_key
    recording_service.retry(db, cu, rec.id)
    assert rec.asr_status == "queued" and rec.attempts == 0


def test_rejected_audio_fails_immediately(db, cloud):
    _, cu = _user(db, "rec_w4")
    rec = recording_service.upload(db, cu, "r.m4a", "", AUDIO)
    db.commit()
    assert recording_worker.run_once(_session(db), transcriber=lambda job: {"text": "  "}) == "failed"
    db.refresh(rec)
    assert rec.asr_status == "failed" and rec.attempts == 1


def test_expired_lease_is_reclaimed(db, cloud):
    _, cu = _user(db, "rec_w5")
    rec = recording_service.upload(db, cu, "l.m4a", "", AUDIO)
    rec.asr_status, rec.lease_token = "running", "stale"
    rec.lease_until = beijing_now() - timedelta(minutes=1)
    db.commit()
    job = recording_worker.claim(db)
    assert job["id"] == rec.id and job["lease_token"] != "stale"


def test_organize_normalize_marks_unverified_quotes():
    values = {"domestic_followup_category": ["质量", "其他"], "domestic_followup_channel": ["电话"]}
    output = {"summary": "客户想补货",
              "facts": [{"text": "要补 20 条", "nature": "customer_said", "excerpt": "这周要补二十条货"},
                        {"text": "编造", "nature": "customer_said", "excerpt": "转写里根本没有这句话"}],
              "issues": [{"text": "色差", "category": "不存在", "excerpt": "上次那批颜色偏黄"}],
              "next_steps": [{"text": "周五发样", "method": "微信", "excerpt": "周五之前把样品发过去"}]}
    transcript = "S02：这周要补二十条货\nS02：上次那批颜色偏黄\nS01：周五之前把样品发过去"
    draft = recording_organize_service.normalize(output, transcript, values)
    assert draft["facts"][0]["nature"] == "customer_said" and draft["facts"][0]["source"]["verified"]
    assert draft["facts"][1]["nature"] == "to_confirm" and not draft["facts"][1]["source"]["verified"]
    assert draft["items"][0]["category"] is None and draft["items"][0]["source"]["verified"]
    assert draft["next_steps"][0]["method"] is None


def test_organize_requires_finished_transcript(db, cloud):
    _, cu = _user(db, "rec_o1")
    rec = recording_service.upload(db, cu, "o.m4a", "", AUDIO)
    with pytest.raises(ValueError, match="转写完成后"):
        recording_organize_service.start(db, cu, rec.id)


def test_router_upload_detail_and_download(db, cloud):
    seed_dicts(db)
    user, _ = _user(db, "rec_api")
    with followup_client(db, user) as client:
        response = client.post("/api/domestic-followup/recordings",
                               files={"file": ("call.m4a", AUDIO, "audio/mp4")}, data={"hotwords": "接发"})
        assert response.status_code == 200, response.text
        rid = response.json()["data"]["id"]
        assert response.json()["data"]["queue_position"] == 1
        assert client.get(f"/api/domestic-followup/recordings/{rid}/transcript.txt").status_code == 404
        rec = db.get(DomesticFollowupRecording, rid)
        rec.asr_status, rec.transcript_key, rec.transcript_text = "done", "transcripts/aa/x.txt", "文本"
        (cloud.root / "transcripts/aa").mkdir(parents=True)
        (cloud.root / "transcripts/aa/x.txt").write_text("文本", encoding="utf-8")
        db.flush()
        download = client.get(f"/api/domestic-followup/recordings/{rid}/transcript.txt")
        assert download.status_code == 200 and download.content.decode("utf-8") == "文本"
        assert "filename*=UTF-8''" in download.headers["content-disposition"]
        assert client.get(f"/api/domestic-followup/recordings/{rid}").json()["data"]["transcript_text"] == "文本"
