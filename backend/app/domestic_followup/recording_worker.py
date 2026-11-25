"""办公室录音转写 worker：领取 queued 录音 → 局域网 ASR → txt 写 COS → 删原音频。

只在 ASR_WORKER_ENABLED 的实例（办公室）启动；北京不启动，也就不会去访问局域网 ASR。
与业务 scheduler 无关，自带线程循环（照 app/core/storage/worker.py）。ASR 单卡串行，一次只领一条。
ASR 离线：任务放回队列且不计次数，不会因为本机关机把录音判失败。
"""
import logging
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from uuid import uuid4

import httpx
from sqlalchemy import and_, or_

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.storage import files as cloud_files
from app.core.storage.cos import CosObjectStore
from app.core.time import beijing_now
from app.domestic import file_service
from app.domestic_followup import recording_service
from app.domestic_followup.models import DomesticFollowupRecording as Recording

logger = logging.getLogger("commission")

ENGINE = "moss-transcribe-diarize"
IDLE_WAIT_SEC = 15
OFFLINE_WAIT_SEC = 60
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class AsrOffline(RuntimeError):
    """ASR 不可达：不计次数，稍后重领。"""


class AsrRejected(RuntimeError):
    """ASR 明确拒绝（解码失败、空音频等）：重试无意义。"""


def _log(message: str) -> None:
    logger.warning(message)
    print(f"[followup_recording] {message}", flush=True)


def claim(db, *, now=None):
    now = now or beijing_now()
    row = (db.query(Recording).filter(
        Recording.archived_at.is_(None), Recording.file_key.is_not(None), Recording.next_attempt_at <= now,
        or_(Recording.asr_status == "queued",
            and_(Recording.asr_status == "running", or_(Recording.lease_until.is_(None), Recording.lease_until <= now))),
    ).order_by(Recording.next_attempt_at, Recording.id).with_for_update(skip_locked=True).first())
    if row is None:
        db.rollback()
        return None
    settings = get_settings()
    row.asr_status = "running"
    row.lease_token = uuid4().hex
    row.lease_until = now + timedelta(seconds=settings.ASR_TIMEOUT_SECONDS + 600)
    job = {"id": row.id, "lease_token": row.lease_token, "file_key": row.file_key, "file_name": row.file_name,
           "hotwords": row.hotwords, "followup_id": row.followup_id}
    db.commit()
    return job


def _headers() -> dict:
    key = get_settings().ASR_API_KEY
    return {"Authorization": f"Bearer {key}"} if key else {}


def _check_online(client: httpx.Client, base: str) -> None:
    try:
        response = client.get(f"{base}/health", headers=_headers(), timeout=5)
    except httpx.HTTPError as exc:
        raise AsrOffline(type(exc).__name__) from exc
    if response.status_code != 200 or not response.json().get("model_loaded"):
        raise AsrOffline(f"health {response.status_code}")


def transcribe(job: dict, *, client: httpx.Client | None = None) -> dict:
    settings = get_settings()
    base = settings.ASR_BASE_URL.rstrip("/")
    if not base:
        raise AsrOffline("ASR_BASE_URL not configured")
    owns = client is None
    client = client or httpx.Client(trust_env=False)
    try:
        _check_online(client, base)
        path = file_service.resolve_path(job["file_key"])
        with open(path, "rb") as stream:
            data = {"response_format": "verbose_json"}
            if job.get("hotwords"):
                data["hotwords"] = job["hotwords"]
            try:
                response = client.post(
                    f"{base}/v1/audio/transcriptions", headers=_headers(), data=data,
                    files={"file": (Path(job["file_key"]).name, stream, "application/octet-stream")},
                    timeout=httpx.Timeout(settings.ASR_TIMEOUT_SECONDS, connect=10),
                )
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                raise AsrOffline(type(exc).__name__) from exc
    finally:
        if owns:
            client.close()
    if response.status_code in (401, 403):
        raise AsrOffline(f"auth {response.status_code}")  # 密钥配错是运维问题，不消耗录音的重试次数
    if response.status_code in _RETRYABLE_STATUS:
        raise RuntimeError(f"ASR HTTP {response.status_code}")
    if response.status_code != 200:
        raise AsrRejected(f"ASR HTTP {response.status_code}")
    result = response.json()
    if result.get("truncated"):
        _log(f"transcript truncated id={job['id']}")
    return result


def _fmt(seconds) -> str:
    total = int(float(seconds or 0))
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def build_txt(meta: dict, result: dict) -> str:
    segments = result.get("segments") or []
    lines = [
        f"客户：{meta.get('shop_name') or '未关联'}　跟进日期：{meta.get('followup_date') or '未关联'}"
        f"　录音时长：{_fmt(result.get('duration_sec'))}　转写：{ENGINE}",
        "说明：机器转写，可能有错字；说话人编号按 5 分钟分段各自编排，仅供参考。",
        "-" * 60,
    ]
    if segments:
        lines.extend(f"[{_fmt(s.get('start'))}] {s.get('speaker') or ''}：{(s.get('text') or '').strip()}"
                     for s in segments if (s.get("text") or "").strip())
    else:
        lines.append((result.get("text") or "").strip())
    return "\n".join(lines) + "\n"


def _meta(db, followup_id) -> dict:
    from app.domestic.models import DomesticCustomer
    from app.domestic_followup.models import DomesticFollowup

    followup = db.get(DomesticFollowup, followup_id) if followup_id else None
    customer = db.get(DomesticCustomer, followup.customer_id) if followup and followup.customer_id else None
    return {"shop_name": customer.shop_name if customer else None,
            "followup_date": followup.followup_date.isoformat() if followup else None}


def _store_and_verify_txt(content: bytes) -> str:
    """写 txt 并回读核对；任何一步失败都不删原音频。"""
    name = f"{uuid4().hex}.txt"
    key = f"transcripts/{name[:2]}/{name}"
    if not cloud_files.put_bytes(recording_service.STORAGE_DOMAIN, key, content, "text/plain; charset=utf-8"):
        raise RuntimeError("domestic storage is not cloud-enabled")
    settings = get_settings()
    cache = Path(settings.COS_CACHE_ROOT)
    cache.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="transcript-check-", dir=cache) as temporary:
        target = Path(temporary) / "check.txt"
        CosObjectStore(recording_service.STORAGE_DOMAIN).download(key, target, max_bytes=len(content) + 1)
        if target.read_bytes() != content:
            raise RuntimeError("transcript verification mismatch")
    return key


def _owned(db, job) -> Recording | None:
    row = (db.query(Recording).filter(Recording.id == job["id"])
           .populate_existing().with_for_update().first())
    if row is None or row.lease_token != job["lease_token"]:
        db.rollback()
        return None
    return row


def finish_success(db, job: dict, result: dict) -> bool:
    text = (result.get("text") or "").strip()
    if not text:
        raise AsrRejected("empty transcript")
    txt = build_txt(_meta(db, job["followup_id"]), result).encode("utf-8")
    db.rollback()  # 写 COS 前不持锁
    key = _store_and_verify_txt(txt)
    row = _owned(db, job)
    if row is None:
        return False
    audio_key = row.file_key
    segments = [{"start": s.get("start"), "end": s.get("end"), "speaker": s.get("speaker"),
                 "text": (s.get("text") or "").strip()} for s in (result.get("segments") or [])]
    row.transcript_key, row.transcript_text, row.segments = key, text, segments
    row.transcript_chars = len(text)
    row.duration_sec = int(float(result.get("duration_sec") or 0)) or None
    row.asr_elapsed_sec = int(float(result.get("elapsed_sec") or 0)) or None
    row.asr_engine, row.asr_status, row.error_message = ENGINE, "done", None
    row.lease_token = row.lease_until = None
    db.commit()
    if audio_key:
        try:
            cloud_files.delete(recording_service.STORAGE_DOMAIN, audio_key, file_service.storage_root())
        except Exception as exc:  # noqa: BLE001 — 删除失败保留 file_key，下轮清理任务再删
            _log(f"audio delete failed id={job['id']} type={type(exc).__name__}")
            return True
        row = db.get(Recording, job["id"])
        row.file_key, row.audio_deleted_at = None, beijing_now()
        db.commit()
    return True


def finish_failure(db, job: dict, exc: Exception) -> None:
    row = _owned(db, job)
    if row is None:
        return
    row.lease_token = row.lease_until = None
    now = beijing_now()
    if isinstance(exc, AsrOffline):
        row.asr_status, row.next_attempt_at = "queued", now + timedelta(seconds=OFFLINE_WAIT_SEC)
        row.error_message = "转写服务暂时离线，录音已排队"
    else:
        row.attempts += 1
        row.error_message = f"转写失败（{type(exc).__name__}）"[:255]
        if isinstance(exc, AsrRejected) or row.attempts >= get_settings().ASR_MAX_ATTEMPTS:
            row.asr_status = "failed"
        else:
            row.asr_status = "queued"
            row.next_attempt_at = now + timedelta(minutes=2 ** row.attempts)
    db.commit()


def run_once(session_factory=SessionLocal, transcriber=transcribe) -> str:
    """返回 idle / done / offline / failed，供循环决定等待时长。"""
    with session_factory() as db:
        job = claim(db)
    if job is None:
        return "idle"
    try:
        result = transcriber(job)
        with session_factory() as db:
            finish_success(db, job, result)
        return "done"
    except Exception as exc:  # noqa: BLE001 — 单条失败落库，循环继续
        _log(f"transcribe failed id={job['id']} type={type(exc).__name__}")
        try:
            with session_factory() as db:
                finish_failure(db, job, exc)
        except Exception as mark_exc:  # noqa: BLE001 — 标记失败靠租约到期回收
            _log(f"mark failed also failed id={job['id']} type={type(mark_exc).__name__}")
        return "offline" if isinstance(exc, AsrOffline) else "failed"


def cleanup_deleted_audio(session_factory=SessionLocal) -> int:
    """转写成功但删除音频失败的，补删。"""
    count = 0
    with session_factory() as db:
        rows = (db.query(Recording).filter(Recording.asr_status == "done", Recording.file_key.is_not(None),
                                           Recording.transcript_key.is_not(None)).limit(20).all())
        for row in rows:
            try:
                cloud_files.delete(recording_service.STORAGE_DOMAIN, row.file_key, file_service.storage_root())
                row.file_key, row.audio_deleted_at = None, beijing_now()
                db.commit()
                count += 1
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                _log(f"cleanup delete failed id={row.id} type={type(exc).__name__}")
    return count


def start_worker():
    settings = get_settings()
    if not settings.ASR_WORKER_ENABLED:
        return None
    if not settings.ASR_BASE_URL:
        raise RuntimeError("ASR_BASE_URL must be set when ASR_WORKER_ENABLED=true")
    stop = Event()

    def loop():
        cycles = 0
        while not stop.is_set():
            try:
                outcome = run_once()
                cycles += 1
                if cycles % 40 == 0:
                    cleanup_deleted_audio()
            except Exception as exc:  # noqa: BLE001
                _log(f"worker loop failed type={type(exc).__name__}")
                outcome = "failed"
            if outcome != "done":
                stop.wait(OFFLINE_WAIT_SEC if outcome == "offline" else IDLE_WAIT_SEC)

    thread = Thread(target=loop, name="followup-asr", daemon=True)
    thread.start()
    print("[followup_recording] ASR worker started", flush=True)
    return stop, thread


def stop_worker(worker):
    if worker:
        stop, thread = worker
        stop.set()
        thread.join(timeout=5)
