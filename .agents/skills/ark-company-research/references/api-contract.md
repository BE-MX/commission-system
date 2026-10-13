# Ark customer research task API

All requests use `Authorization: Bearer <ARK_AGENT_TOKEN>` and JSON. `ARK_BASE_URL` excludes the trailing slash and its exact origin must equal trusted `ARK_ALLOWED_ORIGIN`. Disable redirects or revalidate every destination before forwarding authorization. Successful responses use `{ "code": 200, "message": "ok", "data": ... }`.

## Task lifecycle

- `GET /api/sales-automation/agent/research-tasks` lists claimable unified research tasks.
- `GET /api/sales-automation/agent/research-tasks/{research_task_id}/context` returns `customer_id`, task type, tier, policy, `input_hash`, Ark customer summary, input snapshot, and research rules.
- `POST /api/sales-automation/agent/research-tasks/{research_task_id}/claim` takes `{"agent_id":"research-agent"}` and creates a Run atomically and returns its `agent_run_id`, current `input_hash`, and a one-time lease. Keep it in process memory only.
- `POST /api/sales-automation/agent/research-tasks/{research_task_id}/heartbeat` takes the Agent identity and lease.
- `POST /api/sales-automation/agent/research-tasks/{research_task_id}/industry-gate` takes the lease, `industry_relevance`, and an evidence-based reason.
- `POST /api/sales-automation/agent/research-tasks/{research_task_id}/facts` takes the lease, current `agent_run_id`, and atomic `ResearchFactInput` records. It is the only research-ingest write path and returns a server-generated `tool_call_id`, content hash, classification, and `evidence_refs` for the current customer.
- `POST /api/sales-automation/agent/research-tasks/{research_task_id}/complete` takes the lease, current `agent_run_id`, classification/visibility, and `result_json` using `customer_research_v1` or the advertised private `research_gap_v1` contract.
- `POST /api/sales-automation/agent/research-tasks/{research_task_id}/fail` records a safe error code and releases the lease.

The completion result contains `research_task_id`, `customer_id`, task status, result review status, and evidence fact IDs. Never substitute a company, lead, subject, profile, name, email, or domain identifier.

## Result closure

`customer_research_v1` contains the exact task `input_hash`, claims, citations, optional versioned company-knowledge references, and evidence fact IDs. A citation must name one claim, one successful current-Run tool call, `fact:<id>`, and the exact 64-character fact content hash. Ark rejects missing, stale, cross-customer, cross-Run, or unreferenced evidence.

Context advertises `execution_contract=external_research_run_v1`. MCP checks this before claim and automatically injects the returned Run ID into writes. HTTP clients must use the exact Run from claim. Each fact transaction also records the actual evidence envelope in requested/succeeded events; no client-supplied events are accepted.

`research_gap_v1` requires the exact claim `input_hash`, `gap_reason` (10–2000 characters) and 1–10 unique nonempty `missing_information` entries (at most 200 characters each). No other fields are accepted. It is limited to `private-enrichment-v1` / `full_research`, a passed `research_gate_v1` with `industry_relevance=uncertain`, and zero facts in the current Run. Lease, owner, Run and frozen-input checks still apply. Completion retains the original gate audit, finishes the same Run, preserves the customer, and sets `result_review_status=not_required`. It inherits the stricter task/caller classification and visibility. The result cannot enter quality review or qualification; a later request with new clues creates a new task.
