"""Bounded ASGI upload reading; no unbounded body/decompression helpers."""
import zlib

from starlette.requests import ClientDisconnect, Request

from .errors import FeedError


async def read_json_body(request: Request, settings) -> bytes:
    parts = [part.strip().lower() for part in request.headers.get("content-type", "").split(";")]
    if parts[0] != "application/json" or any(
        part.replace('"', "").replace(" ", "") not in {"charset=utf-8", "charset=utf8"}
        for part in parts[1:]
    ):
        raise FeedError(415, "JSON_CONTENT_TYPE_REQUIRED")
    encoding = request.headers.get("content-encoding", "identity").strip().lower()
    if encoding not in {"identity", "gzip"}:
        raise FeedError(415, "CONTENT_ENCODING_UNSUPPORTED")
    compressed = encoding == "gzip"
    wire_limit = settings.ALIBABA_FEED_MAX_COMPRESSED_BYTES if compressed else settings.ALIBABA_FEED_MAX_BODY_BYTES
    declared = request.headers.get("content-length")
    if declared is not None:
        if not declared.isascii() or not declared.isdecimal():
            raise FeedError(400, "CONTENT_LENGTH_INVALID")
        normalized = declared.lstrip("0") or "0"
        maximum = str(wire_limit)
        if len(normalized) > len(maximum) or (len(normalized) == len(maximum) and normalized > maximum):
            raise FeedError(413, "PAYLOAD_TOO_LARGE")
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS) if compressed else None
    output = bytearray()
    wire_bytes = 0
    try:
        async for chunk in request.stream():
            wire_bytes += len(chunk)
            if wire_bytes > wire_limit:
                raise FeedError(413, "PAYLOAD_TOO_LARGE")
            if decoder is None:
                output.extend(chunk)
            else:
                pending = chunk
                while pending:
                    output.extend(decoder.decompress(pending, settings.ALIBABA_FEED_MAX_BODY_BYTES - len(output) + 1))
                    if len(output) > settings.ALIBABA_FEED_MAX_BODY_BYTES:
                        raise FeedError(413, "PAYLOAD_TOO_LARGE")
                    if decoder.unused_data:
                        raise FeedError(400, "GZIP_INVALID")
                    pending = decoder.unconsumed_tail
            if len(output) > settings.ALIBABA_FEED_MAX_BODY_BYTES:
                raise FeedError(413, "PAYLOAD_TOO_LARGE")
    except zlib.error as exc:
        raise FeedError(400, "GZIP_INVALID") from exc
    except ClientDisconnect as exc:
        raise FeedError(400, "UPLOAD_INCOMPLETE") from exc
    if decoder is not None:
        if not decoder.eof:
            raise FeedError(400, "GZIP_INVALID")
        if len(output) > wire_bytes * settings.ALIBABA_FEED_MAX_RATIO:
            raise FeedError(413, "COMPRESSION_RATIO_EXCEEDED")
    if declared is not None and wire_bytes != int(normalized):
        raise FeedError(400, "CONTENT_LENGTH_INVALID")
    return bytes(output)
