from types import SimpleNamespace

from scripts.benchmark_whatsapp_translation_models import (
    _parse_contract,
    BenchmarkResult,
    deduplicate_targets,
    generate_cases,
    percentile,
    preserves_invariants,
    render_report,
)


def test_generate_cases_covers_five_languages_three_lengths_twice():
    cases = generate_cases()

    assert len(cases) == 30
    assert {(case.source_language, case.length) for case in cases} == {
        (language, length)
        for language in ("en", "de", "nl", "es", "sv")
        for length in ("short", "medium", "long")
    }
    assert all(sum(case.repetition == repetition for case in cases) == 15 for repetition in (1, 2))


def test_percentile_interpolates_and_handles_empty_input():
    assert percentile([], 0.95) is None
    assert percentile([100], 0.95) == 100
    assert percentile([100, 200, 300, 400], 0.50) == 250
    assert percentile([100, 200, 300, 400], 0.95) == 385


def test_invariants_cover_sku_numbers_emoji_urls_and_newlines():
    source = "SKU-A17 costs 12.50 EUR 🤗\nhttps://example.invalid/order"
    valid = "SKU-A17 的价格是 12.50 欧元 🤗\nhttps://example.invalid/order"

    assert preserves_invariants(source, valid)
    assert not preserves_invariants(source, valid.replace("SKU-A17", "SKU-A18"))
    assert not preserves_invariants(source, valid.replace("12.50", "12"))
    assert not preserves_invariants(source, valid.replace("🤗", ""))
    assert not preserves_invariants(source, valid.replace("\n", " "))


def test_deduplicate_targets_uses_provider_and_model_and_skips_image_models():
    provider = SimpleNamespace(id=7, name="Synthetic provider", provider_type="direct", is_enabled=True)
    rows = [
        (provider, SimpleNamespace(model="model-fast")),
        (provider, SimpleNamespace(model="model-fast")),
        (provider, SimpleNamespace(model="gpt-image-2")),
    ]

    targets = deduplicate_targets(rows)

    assert [(target.provider.id, target.model) for target in targets] == [(7, "model-fast")]


def test_benchmark_contract_matches_production_output_schema():
    valid = '{"translated_text":"合成译文","detected_source_language":"de"}'

    assert _parse_contract(valid) == "合成译文"
    assert _parse_contract('{"translated_text":"x","detected_source_language":"auto"}') is None
    assert _parse_contract('{"translated_text":"x","detected_source_language":"de","extra":1}') is None


def test_report_contains_only_aggregate_results():
    result = BenchmarkResult(
        provider_name="Synthetic provider",
        model="model-fast",
        attempts=30,
        successes=29,
        contract_valid=28,
        invariant_valid=27,
        latencies_ms=[100, 200, 300],
        input_tokens=120,
        output_tokens=60,
        errors={"timeout": 1},
    )

    report = render_report([result], generated_at="2026-09-04 23:00:00 +08:00")

    assert "Synthetic provider" in report
    assert "model-fast" in report
    assert "p50" in report.lower()
    assert "timeout: 1" in report
    assert "api_key" not in report.lower()
    assert "https://example.invalid/order" not in report
    assert "SKU-A17" not in report
