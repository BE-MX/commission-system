"""Guard the unified customer cutover against retired runtime contracts."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOTS = (
    REPO_ROOT / "backend" / "app",
    REPO_ROOT / "services" / "openclaw-sales-agent",
)
TEXT_SUFFIXES = {".py", ".mjs", ".json5"}
RETIRED_SYMBOLS = (
    "LeadCompany",
    "ResearchSubject",
    "CustomerProfileEvent",
)
RETIRED_CONTRACTS = (
    "ark_get_lead",
    "ark_save_contacts",
    "ark_save_research",
    "ark_list_public_pool_tasks",
    "ark_get_public_pool_task_context",
    "ark_claim_public_pool_task",
    "ark_heartbeat_public_pool_task",
    "ark_submit_public_pool_industry_gate",
    "ark_complete_public_pool_task",
    "ark_fail_public_pool_task",
    "/agent/leads/",
    "/agent/public-pool/tasks",
)


def _runtime_files():
    for root in RUNTIME_ROOTS:
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in TEXT_SUFFIXES and "node_modules" not in path.parts:
                yield path


def test_retired_customer_models_and_agent_contracts_are_absent_from_runtime():
    findings: list[str] = []
    for path in _runtime_files():
        text = path.read_text(encoding="utf-8")
        for token in (*RETIRED_SYMBOLS, *RETIRED_CONTRACTS):
            if token in text:
                findings.append(f"{path.relative_to(REPO_ROOT)}: {token}")
        if "openclaw-sales-agent" in path.parts and "company_id" in text:
            findings.append(f"{path.relative_to(REPO_ROOT)}: company_id")
    assert findings == [], "Retired customer runtime references remain:\n" + "\n".join(findings)
