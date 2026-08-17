"""Rasterize untrusted dieline documents into bounded PNG model inputs."""

from __future__ import annotations

import base64
import binascii
import io
import math
import multiprocessing
import re
import sys
import threading
import warnings
from xml.etree import ElementTree

from PIL import Image, UnidentifiedImageError


DOCUMENT_MIME_TYPES = ("application/pdf", "image/svg+xml")
MAX_DOCUMENT_PAGES = 1
MAX_SVG_ELEMENTS = 20_000
DOCUMENT_RENDER_TIMEOUT_SECONDS = 20
MAX_CONCURRENT_DOCUMENT_RENDERS = 2
MAX_RENDERED_DOCUMENT_BYTES = 32 * 1024 * 1024
MAX_EMBEDDED_IMAGE_BYTES = 16 * 1024 * 1024
MAX_EMBEDDED_IMAGE_PIXELS = 32_000_000
_PDF_LOCK = threading.RLock()  # PDFium is not thread-safe across concurrent calls.
_DOCUMENT_RENDER_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_DOCUMENT_RENDERS)
_WINDOWS_JOB_HANDLE = None
_LENGTH_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)")
_CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)
_DATA_IMAGE_RE = re.compile(
    r"data:image/(png|jpeg|webp);base64,([a-z0-9+/=\s]+)", re.IGNORECASE
)
_FORBIDDEN_SVG_TAGS = {
    "audio",
    "foreignobject",
    "iframe",
    "script",
    "video",
}


class ReferenceDocumentError(ValueError):
    """A PDF/SVG upload cannot be safely converted into a model input."""


class ReferenceDocumentUnavailableError(ReferenceDocumentError):
    """The isolated document renderer is temporarily unavailable."""


def _png_bytes(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True, compress_level=9)
    return output.getvalue()


def _render_pdf(content: bytes, max_edge: int) -> bytes:
    import pypdfium2 as pdfium

    if not content.startswith(b"%PDF-"):
        raise ReferenceDocumentError("PDF 真实格式与声明的 MIME 不匹配")
    document = page = bitmap = image = None
    try:
        with _PDF_LOCK:
            document = pdfium.PdfDocument(content)
            page_count = len(document)
            if page_count != MAX_DOCUMENT_PAGES:
                raise ReferenceDocumentError("PDF 刀版仅支持单页文件")
            page = document[0]
            width, height = page.get_size()
            if (
                not math.isfinite(width)
                or not math.isfinite(height)
                or width <= 0
                or height <= 0
            ):
                raise ReferenceDocumentError("PDF 刀版页面尺寸无效")
            scale = max_edge / max(width, height)
            bitmap = page.render(scale=scale, fill_color=(255, 255, 255, 255))
            image = bitmap.to_pil()
            return _png_bytes(image)
    except ReferenceDocumentError:
        raise
    except Exception:
        raise ReferenceDocumentError("PDF 刀版无法解析或已加密") from None
    finally:
        if image is not None:
            image.close()
        if bitmap is not None:
            bitmap.close()
        if page is not None:
            page.close()
        if document is not None:
            document.close()


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1].lower()


def _is_embedded_resource(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized.startswith("#") or normalized.startswith(
        ("data:image/png;base64,", "data:image/jpeg;base64,", "data:image/webp;base64,")
    )


def _validate_css_resources(value: str) -> None:
    if "@import" in value.lower():
        raise ReferenceDocumentError("SVG 刀版不能引用外部样式或文件")
    for match in _CSS_URL_RE.finditer(value):
        if not _is_embedded_resource(match.group(2)):
            raise ReferenceDocumentError("SVG 刀版不能引用外部样式或文件")


def _svg_ratio(root: ElementTree.Element) -> float:
    view_box = root.attrib.get("viewBox") or root.attrib.get("viewbox")
    if view_box:
        try:
            values = [float(item) for item in re.split(r"[\s,]+", view_box.strip())]
        except ValueError:
            values = []
        if len(values) == 4 and values[2] > 0 and values[3] > 0:
            return values[2] / values[3]

    def length(name: str) -> float | None:
        match = _LENGTH_RE.match(root.attrib.get(name, ""))
        return float(match.group(1)) if match else None

    width, height = length("width"), length("height")
    if width and height and width > 0 and height > 0:
        return width / height
    return 1.0


def _validate_embedded_images(source: str) -> None:
    total_bytes = 0
    total_pixels = 0
    for match in _DATA_IMAGE_RE.finditer(source):
        try:
            content = base64.b64decode("".join(match.group(2).split()), validate=True)
        except (binascii.Error, ValueError):
            raise ReferenceDocumentError("SVG 刀版包含无效的内嵌图片") from None
        total_bytes += len(content)
        if total_bytes > MAX_EMBEDDED_IMAGE_BYTES:
            raise ReferenceDocumentError("SVG 刀版内嵌图片过大")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(content)) as image:
                    expected = "JPEG" if match.group(1).lower() == "jpeg" else match.group(1).upper()
                    if image.format != expected or image.width < 1 or image.height < 1:
                        raise ReferenceDocumentError("SVG 刀版包含无效的内嵌图片")
                    total_pixels += image.width * image.height
                    if total_pixels > MAX_EMBEDDED_IMAGE_PIXELS:
                        raise ReferenceDocumentError("SVG 刀版内嵌图片分辨率过高")
                    image.verify()
        except ReferenceDocumentError:
            raise
        except (Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise ReferenceDocumentError("SVG 刀版内嵌图片分辨率过高") from None
        except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
            raise ReferenceDocumentError("SVG 刀版包含无效的内嵌图片") from None


def _validate_svg(content: bytes) -> tuple[str, float]:
    try:
        source = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ReferenceDocumentError("SVG 刀版必须使用 UTF-8 编码") from None
    lowered = source.lower()
    if "\x00" in source or "<!doctype" in lowered or "<!entity" in lowered:
        raise ReferenceDocumentError("SVG 刀版包含不安全的 XML 声明")
    try:
        root = ElementTree.fromstring(source)
    except ElementTree.ParseError:
        raise ReferenceDocumentError("SVG 刀版无法解析") from None
    if _local_name(root.tag) != "svg":
        raise ReferenceDocumentError("SVG 真实格式与声明的 MIME 不匹配")
    _validate_embedded_images(source)
    for index, element in enumerate(root.iter(), start=1):
        if index > MAX_SVG_ELEMENTS:
            raise ReferenceDocumentError("SVG 刀版元素过多")
        if _local_name(element.tag) in _FORBIDDEN_SVG_TAGS:
            raise ReferenceDocumentError("SVG 刀版包含不支持的动态内容")
        for key, value in element.attrib.items():
            if _local_name(key) == "href" and not _is_embedded_resource(value):
                raise ReferenceDocumentError("SVG 刀版不能引用外部样式或文件")
            _validate_css_resources(value)
        if _local_name(element.tag) == "style" and element.text:
            _validate_css_resources(element.text)
    return source, _svg_ratio(root)


def _render_svg(content: bytes, max_edge: int) -> bytes:
    import resvg_py

    source, ratio = _validate_svg(content)
    if not math.isfinite(ratio) or ratio <= 0:
        raise ReferenceDocumentError("SVG 刀版画布尺寸无效")
    if ratio >= 1:
        width, height = max_edge, max(1, round(max_edge / ratio))
    else:
        width, height = max(1, round(max_edge * ratio)), max_edge
    try:
        return resvg_py.svg_to_bytes(
            svg_string=source,
            background="#ffffff",
            width=width,
            height=height,
            resources_dir=None,
            shape_rendering="geometric_precision",
            text_rendering="optimize_legibility",
            image_rendering="optimize_quality",
        )
    except ValueError:
        raise ReferenceDocumentError("SVG 刀版无法渲染") from None


def _set_windows_job_limit() -> None:
    import ctypes
    from ctypes import wintypes

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
        )]

    class BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimitInformation),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = (
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
    )
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE

    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
    info = ExtendedLimitInformation()
    info.BasicLimitInformation.LimitFlags = 0x100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
    info.ProcessMemoryLimit = 768 * 1024 * 1024
    if not kernel32.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
        raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")
    if not kernel32.AssignProcessToJobObject(handle, kernel32.GetCurrentProcess()):
        raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")
    global _WINDOWS_JOB_HANDLE
    _WINDOWS_JOB_HANDLE = handle


def _limit_child_resources() -> None:
    if sys.platform == "win32":
        _set_windows_job_limit()
        return
    if not sys.platform.startswith("linux"):
        return
    import resource

    # Fail closed: a Linux renderer without its CPU/memory cage must not parse uploads.
    resource.setrlimit(resource.RLIMIT_CPU, (15, 16))
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024,) * 2)


def _render_document_child(connection, content: bytes, mime: str, max_edge: int) -> None:
    try:
        _limit_child_resources()
        if mime == "application/pdf":
            result = _render_pdf(content, max_edge)
        elif mime == "image/svg+xml":
            result = _render_svg(content, max_edge)
        else:
            raise ReferenceDocumentError("不支持的刀版文件格式")
        if len(result) > MAX_RENDERED_DOCUMENT_BYTES:
            raise ReferenceDocumentError("刀版预览文件过大")
        connection.send(("ok", result))
    except ReferenceDocumentError as exc:
        connection.send(("error", str(exc)))
    except BaseException:
        connection.send(("unavailable", "刀版文件转换服务暂不可用"))
    finally:
        connection.close()


def _stop_process(process) -> None:
    if process.is_alive():
        process.terminate()
        process.join(timeout=1)
    if process.is_alive():
        process.kill()
        process.join(timeout=1)


def rasterize_reference_document(
    content: bytes,
    declared_mime: str,
    *,
    max_edge: int,
) -> bytes:
    """Convert one untrusted document in a bounded child process."""
    mime = (declared_mime or "").split(";", 1)[0].strip().lower()
    if mime not in DOCUMENT_MIME_TYPES:
        raise ReferenceDocumentError("不支持的刀版文件格式")
    if not _DOCUMENT_RENDER_SLOTS.acquire(timeout=1):
        raise ReferenceDocumentUnavailableError("刀版文件转换繁忙，请稍后重试")

    process = None
    receive = send = None
    try:
        context = multiprocessing.get_context("spawn")
        receive, send = context.Pipe(duplex=False)
        process = context.Process(
            target=_render_document_child,
            args=(send, content, mime, max_edge),
            name="design-image-document-render",
            daemon=True,
        )
        process.start()
        send.close()
        send = None
        if not receive.poll(DOCUMENT_RENDER_TIMEOUT_SECONDS):
            _stop_process(process)
            raise ReferenceDocumentUnavailableError("刀版文件转换超时，请稍后重试")
        try:
            status, payload = receive.recv()
        except EOFError:
            raise ReferenceDocumentUnavailableError("刀版文件转换服务暂不可用") from None
        process.join(timeout=1)
        _stop_process(process)
        if status == "unavailable":
            raise ReferenceDocumentUnavailableError(str(payload))
        if status != "ok":
            raise ReferenceDocumentError(str(payload))
        if not isinstance(payload, bytes) or len(payload) > MAX_RENDERED_DOCUMENT_BYTES:
            raise ReferenceDocumentError("刀版预览文件过大")
        return payload
    except (OSError, RuntimeError):
        if process is not None:
            _stop_process(process)
        raise ReferenceDocumentUnavailableError("刀版文件转换服务暂不可用") from None
    finally:
        if receive is not None:
            receive.close()
        if send is not None:
            send.close()
        _DOCUMENT_RENDER_SLOTS.release()
