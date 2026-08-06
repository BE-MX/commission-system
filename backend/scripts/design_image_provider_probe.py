"""Phase 0 capability probe for the design image generation Provider.

The command emits a JSON record to stdout. It never prints API keys or image
base64 payloads and does not write generated images to disk.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from PIL import Image, ImageDraw
from dotenv import load_dotenv
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

_probe_env_file = os.getenv("ARK_PROBE_ENV_FILE")
if _probe_env_file:
    load_dotenv(_probe_env_file, override=True)

from app.ai.http_client import build_headers, build_image_url
from app.ai.keyring import decrypt_key
from app.ai.models import AiPreset, AiProvider
from app.core.config import get_settings
from app.core.database import SessionLocal


PRESET_NAME = "design_image_generation"
SOURCE_PRESET_NAME = "expo_wig_composite"
MODEL_NAME = "gpt-image-2"
PROBE_PROMPT = (
    "Create a clean studio product photograph of a single matte white geometric "
    "vase on a light gray background, without text, logos, people, or trademarks."
)
REQUEST_ID_HEADERS = ("x-request-id", "request-id", "x-trace-id", "cf-ray")
_SECRET_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "password",
    "secret",
    "token",
}
_URL_RE = re.compile(r"https?://[^\s\"'<>]+")
_BEARER_RE = re.compile(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]{8,}")
_OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_LONG_BASE64_RE = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/=]{256,}(?![A-Za-z0-9+/=])")


def build_generation_cases() -> list[dict[str, str]]:
    """Minimum non-duplicated matrix covering all V1 qualities and sizes."""
    return [
        {"quality": "low", "size": "1024x1024"},
        {"quality": "medium", "size": "1024x1024"},
        {"quality": "high", "size": "1024x1024"},
        {"quality": "low", "size": "1024x1536"},
        {"quality": "low", "size": "1536x1024"},
    ]


def build_edit_files(
    images: list[tuple[str, bytes, str]],
) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("image", image) for image in images]


def build_synthetic_edit_inputs() -> list[tuple[str, bytes, str]]:
    """Create two non-sensitive in-memory references for the edit probe."""
    specs = [
        ("blue-circle.png", "circle", "#2f6fed"),
        ("orange-triangle.png", "triangle", "#f28c28"),
    ]
    result = []
    for filename, shape, color in specs:
        image = Image.new("RGB", (512, 512), "#f5f5f5")
        draw = ImageDraw.Draw(image)
        if shape == "circle":
            draw.ellipse((128, 128, 384, 384), fill=color)
        else:
            draw.polygon(((256, 112), (400, 392), (112, 392)), fill=color)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        result.append((filename, buffer.getvalue(), "image/png"))
    return result


def _safe_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https"):
        return "[omitted non-http URL]"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _sanitize_text(value: str) -> str:
    if value.startswith("data:image/"):
        return f"[omitted data image, {len(value)} chars]"
    value = _BEARER_RE.sub("Bearer [redacted]", value)
    value = _OPENAI_KEY_RE.sub("[redacted API key]", value)
    value = _LONG_BASE64_RE.sub("[omitted long base64-like value]", value)
    return _URL_RE.sub(lambda match: _safe_url(match.group(0)), value)


def _is_secret_key(key: Any) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    return (
        normalized in _SECRET_KEYS
        or normalized.endswith("_api_key")
        or normalized.endswith("_secret")
        or normalized.endswith("_token")
    )


def sanitize_response(value: Any) -> Any:
    """Recursively remove image data and signed URL query strings."""
    if isinstance(value, dict):
        safe = {}
        for key, item in value.items():
            if _is_secret_key(key) and isinstance(item, str):
                safe[key] = "[redacted secret]"
            elif key == "b64_json" and isinstance(item, str):
                safe[key] = f"[omitted base64 image, {len(item)} chars]"
            elif key == "url" and isinstance(item, str):
                safe[key] = _safe_url(item)
            else:
                safe[key] = sanitize_response(item)
        return safe
    if isinstance(value, list):
        return [sanitize_response(item) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    return value


def validate_probe_preset(preset: AiPreset, provider: AiProvider) -> None:
    if preset.model != MODEL_NAME:
        raise ValueError(f"{PRESET_NAME} model 必须为 {MODEL_NAME}")
    if not preset.is_enabled or preset.deleted_at is not None:
        raise ValueError(f"{PRESET_NAME} 必须启用")
    if (preset.parameters or {}).get("input_fidelity") is not None:
        raise ValueError(f"{PRESET_NAME} 禁止配置 input_fidelity")
    if provider.provider_type != "direct" or provider.api_type != "openai":
        raise ValueError("设计生图 Preset 必须绑定 OpenAI-compatible 直连 Provider")
    if not provider.is_enabled or provider.deleted_at is not None:
        raise ValueError("设计生图 Provider 必须启用")


def ensure_probe_preset(db: Session) -> tuple[AiPreset, bool]:
    existing = (
        db.query(AiPreset)
        .filter(AiPreset.preset_name == PRESET_NAME)
        .first()
    )
    if existing:
        if existing.deleted_at is not None:
            raise ValueError(
                f"{PRESET_NAME} 已软删除；请在 AI 后台恢复或彻底更名，探针不会自动复活"
            )
        provider = db.query(AiProvider).filter(AiProvider.id == existing.provider_id).first()
        if not provider:
            raise ValueError(f"{PRESET_NAME} 绑定的 Provider 不存在")
        validate_probe_preset(existing, provider)
        return existing, False

    source = (
        db.query(AiPreset)
        .filter(
            AiPreset.preset_name == SOURCE_PRESET_NAME,
            AiPreset.deleted_at.is_(None),
        )
        .first()
    )
    if not source:
        raise ValueError(f"缺少来源 Preset: {SOURCE_PRESET_NAME}")
    provider = db.query(AiProvider).filter(AiProvider.id == source.provider_id).first()
    if not provider:
        raise ValueError(f"{SOURCE_PRESET_NAME} 绑定的 Provider 不存在")

    preset = AiPreset(
        preset_name=PRESET_NAME,
        provider_id=provider.id,
        model=MODEL_NAME,
        system_prompt=None,
        parameters={"output_format": "png"},
        description="设计部 AI 生图工作台：GPT Image 2 独立配置",
        is_enabled=True,
    )
    validate_probe_preset(preset, provider)
    db.add(preset)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = (
            db.query(AiPreset)
            .filter(AiPreset.preset_name == PRESET_NAME)
            .first()
        )
        if not concurrent:
            raise
        if concurrent.deleted_at is not None:
            raise ValueError(
                f"{PRESET_NAME} 已软删除；请在 AI 后台恢复或彻底更名，探针不会自动复活"
            )
        concurrent_provider = (
            db.query(AiProvider).filter(AiProvider.id == concurrent.provider_id).first()
        )
        if not concurrent_provider:
            raise ValueError(f"{PRESET_NAME} 绑定的 Provider 不存在")
        validate_probe_preset(concurrent, concurrent_provider)
        return concurrent, False
    db.refresh(preset)
    return preset, True


def _request_id(response: httpx.Response) -> str | None:
    for name in REQUEST_ID_HEADERS:
        value = response.headers.get(name)
        if value:
            return value
    return None


def _image_metadata(payload: dict) -> dict[str, Any]:
    data = payload.get("data")
    first = data[0] if isinstance(data, list) and data else payload
    if not isinstance(first, dict):
        return {"output_kind": "missing"}
    encoded = first.get("b64_json")
    if isinstance(encoded, str):
        raw = __import__("base64").b64decode(encoded)
        metadata: dict[str, Any] = {
            "output_kind": "b64_json",
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        try:
            with Image.open(io.BytesIO(raw)) as image:
                metadata.update({
                    "format": image.format,
                    "width": image.width,
                    "height": image.height,
                })
        except Exception as exc:
            metadata["decode_error"] = f"{type(exc).__name__}: {exc}"
        return metadata
    if isinstance(first.get("url"), str):
        return {"output_kind": "url", "url": _safe_url(first["url"])}
    return {"output_kind": "missing"}


def _response_record(response: httpx.Response, elapsed_ms: int) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception:
        payload = {"raw_text": f"[omitted non-JSON response, {len(response.text)} chars]"}
    record = {
        "http_status": response.status_code,
        "request_id": _request_id(response),
        "duration_ms": elapsed_ms,
        "response": sanitize_response(payload),
    }
    if response.is_success:
        record["image"] = _image_metadata(payload)
    return record


class LiveProbe:
    def __init__(self, preset: AiPreset, provider: AiProvider):
        validate_probe_preset(preset, provider)
        self.preset = preset
        self.provider = provider
        api_key = decrypt_key(provider.api_key) if provider.api_key else None
        self.headers = build_headers(provider, api_key)
        timeout_sec = max(provider.timeout_sec or 0, 300)
        kwargs: dict[str, Any] = {
            "timeout": httpx.Timeout(timeout_sec, connect=15.0, write=30.0),
        }
        proxy = (get_settings().AI_IMAGE_PROXY or "").strip()
        if proxy:
            kwargs["proxy"] = proxy
        self.client = httpx.Client(**kwargs)

    def close(self) -> None:
        self.client.close()

    def _post(self, url: str, **kwargs) -> tuple[httpx.Response, int]:
        start = time.perf_counter()
        response = self.client.post(url, **kwargs)
        elapsed_ms = round((time.perf_counter() - start) * 1000)
        return response, elapsed_ms

    def models(self) -> dict[str, Any]:
        base = self.provider.api_base.rstrip("/")
        url = f"{base}/models" if base.endswith(("/v1", "/v2", "/v3", "/v4")) else f"{base}/v1/models"
        start = time.perf_counter()
        response = self.client.get(url, headers=self.headers)
        elapsed_ms = round((time.perf_counter() - start) * 1000)
        record = _response_record(response, elapsed_ms)
        try:
            models = response.json().get("data") or []
            record["contains_gpt_image_2"] = any(
                isinstance(item, dict) and item.get("id") == MODEL_NAME for item in models
            )
            record["model_count"] = len(models)
            record.pop("response", None)
        except Exception:
            record["contains_gpt_image_2"] = False
        return record

    def generation(self, case: dict[str, str]) -> dict[str, Any]:
        url = build_image_url(self.provider.api_base, "generations")
        payload = {
            "model": self.preset.model,
            "prompt": PROBE_PROMPT,
            "output_format": "png",
            **case,
        }
        response, elapsed_ms = self._post(url, headers=self.headers, json=payload)
        return {"request": payload, **_response_record(response, elapsed_ms)}

    def edit(self, images: list[tuple[str, bytes, str]]) -> dict[str, Any]:
        url = build_image_url(self.provider.api_base, "edits")
        headers = dict(self.headers)
        headers.pop("Content-Type", None)
        data = {
            "model": self.preset.model,
            "prompt": (
                "Create one simple abstract composition containing the blue circle from the "
                "first reference and the orange triangle from the second reference. "
                "Use a plain light gray background and do not add text or logos."
            ),
            "size": "1024x1024",
            "quality": "low",
            "output_format": "png",
        }
        response, elapsed_ms = self._post(
            url,
            headers=headers,
            data=data,
            files=build_edit_files(images),
        )
        safe_request = {**data, "image_count": len(images), "image_fields": ["image"] * len(images)}
        return {"request": safe_request, **_response_record(response, elapsed_ms)}

    def invalid_model_error(self) -> dict[str, Any]:
        url = build_image_url(self.provider.api_base, "generations")
        payload = {
            "model": "phase0-invalid-model",
            "prompt": "Capability probe: reject this invalid model without generating an image.",
            "size": "1024x1024",
            "quality": "low",
        }
        response, elapsed_ms = self._post(url, headers=self.headers, json=payload)
        return {"request": payload, **_response_record(response, elapsed_ms)}


def run_live_probe(db: Session) -> dict[str, Any]:
    preset, created = ensure_probe_preset(db)
    provider = db.query(AiProvider).filter(AiProvider.id == preset.provider_id).first()
    validate_probe_preset(preset, provider)
    live = LiveProbe(preset, provider)
    try:
        generations = [live.generation(case) for case in build_generation_cases()]
        return {
            "probe_version": 1,
            "preset": {
                "name": preset.preset_name,
                "created": created,
                "model": preset.model,
                "parameters": preset.parameters,
                "provider_id": provider.id,
                "provider_name": provider.name,
                "api_base": _safe_url(provider.api_base),
            },
            "models": live.models(),
            "generations": generations,
            "multi_image_edit": live.edit(build_synthetic_edit_inputs()),
            "invalid_model_error": live.invalid_model_error(),
        }
    finally:
        live.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe GPT Image 2 Provider capabilities")
    parser.add_argument("--ensure-preset", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--edit-only", action="store_true")
    args = parser.parse_args()
    if sum((args.ensure_preset, args.run, args.edit_only)) != 1:
        parser.error("choose exactly one of --ensure-preset, --run, or --edit-only")

    with SessionLocal() as db:
        if args.run:
            result = run_live_probe(db)
        elif args.edit_only:
            preset, _ = ensure_probe_preset(db)
            provider = db.query(AiProvider).filter(AiProvider.id == preset.provider_id).first()
            live = LiveProbe(preset, provider)
            try:
                result = live.edit(build_synthetic_edit_inputs())
            finally:
                live.close()
        else:
            preset, created = ensure_probe_preset(db)
            provider = db.query(AiProvider).filter(AiProvider.id == preset.provider_id).first()
            result = {
                "preset": preset.preset_name,
                "created": created,
                "model": preset.model,
                "parameters": preset.parameters,
                "provider_id": provider.id,
                "provider_name": provider.name,
            }
    print(json.dumps(sanitize_response(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
