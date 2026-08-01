"""展会扫码上传：并发场景下的竞态回归（I1，2026-08-01）。

三处排序/属性读取（_prune_pending 的 sort key、latest_pending 的 max key、
get_pending_photo 的 to_rel()+stat()）都直接读磁盘属性，而候选文件随时可能被
另一个并发的 sweep_stale / _prune_pending / create_session 收尾 unlink 删掉。
这类竞态只在真实并发下才会现形——正是"regresses invisibly"的典型场景，单独
开一个文件把并发探针钉成回归测试，不与其余同步测试混在一起。

两条测试都在文档里记录了修复前、本机实测的真实数字（不是理论推演）。
"""
import io
import threading
import time

import pytest
from PIL import Image

from app.expo import ai_pipeline, router, upload_service


@pytest.fixture(autouse=True)
def _isolate_pending_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(upload_service, "PENDING_DIR", tmp_path / "pending")
    monkeypatch.setattr(ai_pipeline, "REPO_ROOT", tmp_path)


def _jpeg_bytes(size=(80, 120)):
    buf = io.BytesIO()
    Image.new("RGB", size, (120, 90, 70)).save(buf, "JPEG")
    return buf.getvalue()


def test_concurrent_save_pending_never_leaks_bare_os_error():
    """C1 的裁剪（_prune_pending）在并发上传同一客户时，排序 key 必须扛住
    "排序途中候选文件被另一线程删掉"——多个线程各自 glob 出重叠的候选文件
    列表，线程 A 正在 unlink 某个"多余"文件的同时，线程 B 排序时对同一个文件
    调 stat() 就会撞见它已经消失。

    实测（本机、修复前）：120 线程并发上传同一客户 → 88/120 次调用带着裸
    FileNotFoundError（OSError 子类，不是 ValueError）逃出 save_pending——
    router 的 `except ValueError` 接不住，变成客户手机上一次"其实已经传成功"
    的上传收到 500。
    """
    errors = []
    lock = threading.Lock()

    def worker(i):
        try:
            upload_service.save_pending(42, _jpeg_bytes(), f"{i}.jpg")
        except Exception as exc:  # noqa: BLE001 —— 要拿到所有类型，不只 ValueError
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(120)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    non_value_errors = [e for e in errors if not isinstance(e, ValueError)]
    assert not non_value_errors, f"unexpected non-ValueError exceptions: {non_value_errors[:3]}"


def test_concurrent_poll_upload_sweep_never_500s_get_pending_photo():
    """kiosk 每 2 秒轮询一次 GET /kiosk/pending-photo；发码（每次 ticket）、
    建会话确认（每次 create_session）都会触发 sweep_stale/_prune_pending——
    这两个删除路径与轮询路径天然并发。latest_pending 选出的文件可能在
    get_pending_photo 构造响应前就被删掉，两处都可能报错：`latest.stat()`
    对已消失文件抛 FileNotFoundError；`ai_pipeline.to_rel()` 内部
    `Path.resolve()` 对一个已经不存在的路径在 Windows 上走不同的规范化分支，
    会让 `relative_to()` 抛 ValueError（"不在 REPO_ROOT 子路径下"）——这是并发
    探针实测才发现的第二种报错形态，review 只点名了 stat() 那一处。

    实测（本机、修复前）：4 秒并发上传+清理压力下，1146 次轮询里 315 次抛出
    异常（131 FileNotFoundError + 184 ValueError），kiosk 会把这些 500 计入
    POLL_FAIL_HINT_AT 轮询失败计数，最终误判成「现场网络拥堵」。
    """
    stop = threading.Event()

    def uploader():
        i = 0
        while not stop.is_set():
            try:
                upload_service.save_pending(42, _jpeg_bytes(), f"{i}.jpg")
            except Exception:  # noqa: BLE001 —— 这个后台线程只管制造并发压力
                pass
            i += 1

    def sweeper():
        while not stop.is_set():
            # now 故意设成远未来：把所有文件都判定为"已过期"，制造持续删除压力
            upload_service.sweep_stale(now=time.time() + 999_999)
            upload_service._prune_pending(42, keep=1)

    threads = [threading.Thread(target=uploader) for _ in range(4)]
    threads += [threading.Thread(target=sweeper) for _ in range(4)]
    for t in threads:
        t.start()

    errors = []
    polls = 0
    deadline = time.time() + 2
    while time.time() < deadline:
        try:
            router.get_pending_photo(customer_id=42, _user={})
        except Exception as exc:  # noqa: BLE001 —— 端点在任何并发下都不该抛任何异常
            errors.append(exc)
        polls += 1

    stop.set()
    for t in threads:
        t.join()

    assert polls > 0
    assert not errors, f"{len(errors)}/{polls} polls raised, e.g. {errors[:3]}"
