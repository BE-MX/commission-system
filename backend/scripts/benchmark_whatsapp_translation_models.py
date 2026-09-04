"""Read-only synthetic benchmark for configured WhatsApp translation models.

The script reads enabled direct provider/model pairs, calls their public model
endpoints with synthetic text, and writes aggregate results only. It never
changes providers, presets, call logs, translation quota, or release settings.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

import httpx

from app.whatsapp_translation.schemas import TranslationModelOutput


LANGUAGES = ("en", "de", "nl", "es", "sv")
LENGTHS = ("short", "medium", "long")
IMAGE_MODEL_RE = re.compile(r"(?:^|[-_/])(image|dall-e|flux|seedream)(?:$|[-_/0-9])", re.IGNORECASE)
SKU_RE = re.compile(r"\b[A-Z]{2,}-[A-Z0-9]+\b")
NUMBER_RE = re.compile(r"(?<!\w)\d+(?:[.,]\d+)?(?!\w)")
URL_RE = re.compile(r"https?://[^\s]+")
EMOJI_MARKERS = ("🤗", "💕", "✅")


_SAMPLES = {
    "en": {
        "short": "Hello 🤗 SKU-A17 will be ready in 12 days.",
        "medium": "Hello 🤗 Thank you for checking SKU-A17. Production takes 12 days.\nPlease confirm the delivery address.",
        "long": "Hello 🤗 Thank you for asking about SKU-A17. We checked the production schedule and the order will be ready in 12 days.\nQuality inspection happens before packing, and we will share the tracking update after dispatch. Please confirm the delivery address so the shipment is not delayed.",
    },
    "de": {
        "short": "Hallo 🤗 SKU-A17 ist in 12 Tagen fertig.",
        "medium": "Hallo 🤗 Vielen Dank für Ihre Anfrage zu SKU-A17. Die Produktion dauert 12 Tage.\nBitte bestätigen Sie die Lieferadresse.",
        "long": "Hallo 🤗 Vielen Dank für Ihre Anfrage zu SKU-A17. Wir haben den Produktionsplan geprüft und die Bestellung ist in 12 Tagen fertig.\nVor dem Verpacken erfolgt eine Qualitätskontrolle. Nach dem Versand senden wir die Sendungsverfolgung. Bitte bestätigen Sie die Lieferadresse, damit es keine Verzögerung gibt.",
    },
    "nl": {
        "short": "Hallo 🤗 SKU-A17 is over 12 dagen klaar.",
        "medium": "Hallo 🤗 Bedankt voor uw vraag over SKU-A17. De productie duurt 12 dagen.\nBevestig alstublieft het afleveradres.",
        "long": "Hallo 🤗 Bedankt voor uw vraag over SKU-A17. We hebben de productieplanning gecontroleerd en de bestelling is over 12 dagen klaar.\nVoor het verpakken voeren we een kwaliteitscontrole uit. Na verzending sturen we de trackinginformatie. Bevestig het afleveradres om vertraging te voorkomen.",
    },
    "es": {
        "short": "Hola 🤗 SKU-A17 estará listo en 12 días.",
        "medium": "Hola 🤗 Gracias por preguntar por SKU-A17. La producción tarda 12 días.\nConfirme la dirección de entrega.",
        "long": "Hola 🤗 Gracias por preguntar por SKU-A17. Revisamos el calendario de producción y el pedido estará listo en 12 días.\nAntes de embalar hacemos un control de calidad. Después del envío compartiremos el seguimiento. Confirme la dirección de entrega para evitar retrasos.",
    },
    "sv": {
        "short": "Hej 🤗 SKU-A17 är klar om 12 dagar.",
        "medium": "Hej 🤗 Tack för din fråga om SKU-A17. Produktionen tar 12 dagar.\nBekräfta leveransadressen.",
        "long": "Hej 🤗 Tack för din fråga om SKU-A17. Vi har kontrollerat produktionsplanen och beställningen är klar om 12 dagar.\nFöre packning gör vi en kvalitetskontroll. Efter leverans skickar vi spårningsinformationen. Bekräfta leveransadressen för att undvika förseningar.",
    },
}


@dataclass(frozen=True)
class BenchmarkCase:
    source_language: str
    length: str
    repetition: int
    text: str


@dataclass(frozen=True)
class BenchmarkTarget:
    provider: object
    model: str


@dataclass
class BenchmarkResult:
    provider_name: str
    model: str
    attempts: int = 0
    successes: int = 0
    contract_valid: int = 0
    invariant_valid: int = 0
    latencies_ms: list[int] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    errors: Counter[str] | dict[str, int] = field(default_factory=Counter)


def generate_cases(repetitions: int = 2) -> list[BenchmarkCase]:
    return [
        BenchmarkCase(language, length, repetition, _SAMPLES[language][length])
        for repetition in range(1, repetitions + 1)
        for language in LANGUAGES
        for length in LENGTHS
    ]


def percentile(values: Sequence[int | float], quantile: float) -> int | float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    value = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return int(value) if float(value).is_integer() else round(value, 1)


def preserves_invariants(source: str, translated: str) -> bool:
    required = (
        SKU_RE.findall(source),
        NUMBER_RE.findall(source),
        URL_RE.findall(source),
        [marker for marker in EMOJI_MARKERS if marker in source],
    )
    return (
        all(translated.count(token) >= source.count(token) for tokens in required for token in tokens)
        and translated.count("\n") == source.count("\n")
    )


def _is_text_model(model: str) -> bool:
    return not IMAGE_MODEL_RE.search(model)


def deduplicate_targets(rows: Iterable[tuple[object, object]]) -> list[BenchmarkTarget]:
    seen: set[tuple[int, str]] = set()
    targets: list[BenchmarkTarget] = []
    for provider, preset in rows:
        model = str(getattr(preset, "model", "") or "").strip()
        key = (int(provider.id), model)
        if (
            not model
            or key in seen
            or getattr(provider, "provider_type", None) != "direct"
            or not getattr(provider, "is_enabled", False)
            or not _is_text_model(model)
        ):
            continue
        seen.add(key)
        targets.append(BenchmarkTarget(provider=provider, model=model))
    return targets


def _parse_contract(content: str) -> str | None:
    try:
        payload = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return None
    try:
        output = TranslationModelOutput.model_validate(payload)
    except Exception:
        return None
    return output.translated_text


def _request_body(target: BenchmarkTarget, system_prompt: str, case: BenchmarkCase) -> tuple[str, dict, dict]:
    from app.ai.http_client import build_anthropic_body, build_chat_url, build_headers
    from app.ai.keyring import decrypt_key

    provider = target.provider
    api_type = getattr(provider, "api_type", "openai") or "openai"
    payload = json.dumps({
        "direction": "incoming",
        "source_language": "auto",
        "target_language": "zh-CN",
        "allowed_source_languages": ["zh-CN", "en", "es", "fr", "ar", "ja", "de", "nl", "sv"],
        "glossary": [],
        "text": case.text,
    }, ensure_ascii=False)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": payload},
    ]
    if api_type == "anthropic":
        body = build_anthropic_body(target.model, messages, system_prompt, {"max_tokens": 1200})
    else:
        body = {"model": target.model, "messages": messages, "stream": False, "max_tokens": 1200}
    api_key = decrypt_key(provider.api_key) if provider.api_key else None
    return (
        build_chat_url(provider.api_base, api_type),
        build_headers(provider, api_key),
        body,
    )


def _extract_response(provider: object, response: dict) -> tuple[str, int, int]:
    if (getattr(provider, "api_type", "openai") or "openai") == "anthropic":
        from app.ai.http_client import extract_anthropic_content, extract_anthropic_usage

        usage = extract_anthropic_usage(response)
        return (
            extract_anthropic_content(response),
            int(usage.get("prompt_tokens") or 0),
            int(usage.get("completion_tokens") or 0),
        )
    message = (response.get("choices") or [{}])[0].get("message") or {}
    content = message.get("content") or message.get("reasoning_content") or ""
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    usage = response.get("usage") or {}
    return content, int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)


def _error_category(error: Exception) -> str:
    if isinstance(error, httpx.TimeoutException):
        return "timeout"
    if isinstance(error, httpx.HTTPStatusError):
        return "http_5xx" if error.response.status_code >= 500 else "http_4xx"
    if isinstance(error, httpx.TransportError):
        return "transport"
    if isinstance(error, (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError)):
        return "invalid_response"
    return "other"


def benchmark_target(
    target: BenchmarkTarget,
    system_prompt: str,
    cases: Sequence[BenchmarkCase],
    *,
    timeout_sec: int = 20,
) -> BenchmarkResult:
    from app.ai.http_client import post_json

    result = BenchmarkResult(provider_name=str(target.provider.name), model=target.model)
    shuffled = list(cases)
    random.Random(20260904).shuffle(shuffled)

    # Warm the provider route and TLS path once; it is intentionally excluded.
    try:
        url, headers, body = _request_body(target, system_prompt, shuffled[0])
        post_json(url, headers=headers, body=body, timeout_sec=timeout_sec)
    except Exception:
        pass

    for index, case in enumerate(shuffled, start=1):
        result.attempts += 1
        started = time.monotonic()
        try:
            url, headers, body = _request_body(target, system_prompt, case)
            response = post_json(url, headers=headers, body=body, timeout_sec=timeout_sec)
            elapsed = int((time.monotonic() - started) * 1000)
            result.successes += 1
            result.latencies_ms.append(elapsed)
            content, input_tokens, output_tokens = _extract_response(target.provider, response)
            result.input_tokens += input_tokens
            result.output_tokens += output_tokens
            translated = _parse_contract(content)
            if translated is None:
                result.errors["invalid_contract"] += 1
            else:
                result.contract_valid += 1
                if preserves_invariants(case.text, translated):
                    result.invariant_valid += 1
                else:
                    result.errors["invariant_changed"] += 1
        except Exception as error:
            result.errors[_error_category(error)] += 1
        print(
            f"benchmark provider={result.provider_name} model={result.model} progress={index}/{len(shuffled)}",
            flush=True,
        )
    return result


def _rate(value: int, total: int) -> str:
    return f"{value / total:.1%}" if total else "0.0%"


def _safe_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_report(results: Sequence[BenchmarkResult], generated_at: str) -> str:
    eligible = [
        result for result in results
        if result.attempts
        and result.successes / result.attempts >= 0.95
        and result.contract_valid / result.attempts >= 0.95
        and result.invariant_valid / result.attempts >= 0.95
    ]
    fastest = min(eligible, key=lambda item: percentile(item.latencies_ms, 0.50) or float("inf"), default=None)
    recommendation = (
        f"推荐 `{_safe_cell(fastest.provider_name)} / {_safe_cell(fastest.model)}`：在达到 95% 稳定与契约门槛的模型中 P50 最低。"
        if fastest
        else "本轮没有模型同时达到 95% 成功率、契约正确率和关键内容保持率，不建议自动切换生产预设。"
    )
    lines = [
        "# WhatsApp 翻译模型基准报告",
        "",
        f"生成时间：{generated_at}",
        "",
        "## 结论",
        "",
        recommendation,
        "",
        "## 汇总",
        "",
        "| 提供商 / 模型 | 请求 | 成功率 | 契约正确率 | 关键内容保持率 | P50 | P95 | 最大 | 输入 Token | 输出 Token | 错误分类 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for result in sorted(results, key=lambda item: percentile(item.latencies_ms, 0.50) or float("inf")):
        errors = ", ".join(f"{name}: {count}" for name, count in sorted(result.errors.items())) or "无"
        p50 = percentile(result.latencies_ms, 0.50)
        p95 = percentile(result.latencies_ms, 0.95)
        maximum = max(result.latencies_ms, default=None)
        lines.append(
            "| {name} | {attempts} | {success} | {contract} | {invariant} | {p50} | {p95} | {maximum} | {input_tokens} | {output_tokens} | {errors} |".format(
                name=_safe_cell(f"{result.provider_name} / {result.model}"),
                attempts=result.attempts,
                success=_rate(result.successes, result.attempts),
                contract=_rate(result.contract_valid, result.attempts),
                invariant=_rate(result.invariant_valid, result.attempts),
                p50=f"{p50} ms" if p50 is not None else "—",
                p95=f"{p95} ms" if p95 is not None else "—",
                maximum=f"{maximum} ms" if maximum is not None else "—",
                input_tokens=result.input_tokens or "—",
                output_tokens=result.output_tokens or "—",
                errors=_safe_cell(errors),
            )
        )
    lines.extend([
        "",
        "## 方法与边界",
        "",
        "- 对每个已启用的直连文本模型先预热 1 次，再测试 30 次：英语、德语、荷兰语、西班牙语、瑞典语 × 短/中/长文本 × 2。",
        "- 所有模型使用同一 WhatsApp 收件翻译系统提示词和同一批合成文本；顺序固定随机化，避免样本顺序偏差。",
        "- 契约正确率检查 JSON 字段与语言值域；关键内容保持率检查 SKU、数字、Emoji、URL 和换行。",
        "- 延迟包含当前真实 HTTP/TLS 调用路径。报告不保存提示词、翻译正文、API 地址、密钥或原始响应。",
        "- 系统未配置统一模型单价，因此不编造成本；仅报告可核验的 Token 用量。人工语义质量评审不在本轮自动基准范围内。",
        "",
    ])
    return "\n".join(lines)


def _load_configured_targets(db) -> tuple[str, list[BenchmarkTarget]]:
    from app.ai.models import AiPreset, AiProvider
    from app.core.config import get_settings

    settings = get_settings()
    common = (
        db.query(AiPreset)
        .filter(
            AiPreset.preset_name == settings.WHATSAPP_TRANSLATION_PRESET_NAME,
            AiPreset.is_enabled.is_(True),
            AiPreset.deleted_at.is_(None),
        )
        .first()
    )
    if common is None or not (common.system_prompt or "").strip():
        raise RuntimeError("enabled WhatsApp incoming translation preset with a system prompt is required")
    rows = (
        db.query(AiProvider, AiPreset)
        .join(AiPreset, AiPreset.provider_id == AiProvider.id)
        .filter(
            AiProvider.provider_type == "direct",
            AiProvider.is_enabled.is_(True),
            AiProvider.deleted_at.is_(None),
            AiPreset.is_enabled.is_(True),
            AiPreset.deleted_at.is_(None),
        )
        .order_by(AiProvider.id, AiPreset.model)
        .all()
    )
    return common.system_prompt, deduplicate_targets(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Aggregate Markdown output path")
    parser.add_argument("--timeout", type=int, default=20, help="Per-request timeout in seconds")
    args = parser.parse_args()

    from app.core.database import SessionLocal
    from app.core.time import beijing_now

    with SessionLocal() as db:
        system_prompt, targets = _load_configured_targets(db)
    if not targets:
        print("benchmark failed: no enabled direct text models", flush=True)
        return 2

    results = [benchmark_target(target, system_prompt, generate_cases(), timeout_sec=args.timeout) for target in targets]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        render_report(results, beijing_now().strftime("%Y-%m-%d %H:%M:%S +08:00")),
        encoding="utf-8",
    )
    print(f"benchmark complete models={len(results)} report={args.output}", flush=True)
    return 0 if any(result.successes for result in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
