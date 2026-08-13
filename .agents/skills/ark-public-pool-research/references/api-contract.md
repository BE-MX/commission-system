# Ark public-pool MCP contract

Use only these tools for public-pool research:

- `ark_search_knowledge(query, limit)` searches ACL-authorized published enterprise knowledge.
- `ark_get_knowledge_document(document_id)` reads one published knowledge document returned by search.
- `ark_list_public_pool_tasks(page, page_size)` lists claimable tasks.
- `ark_get_public_pool_task_context(task_id)` returns the trusted OKKI seed, tier rules, and component limits.
- `ark_claim_public_pool_task(task_id)` acquires a 15-minute in-process lease.
- `ark_heartbeat_public_pool_task(task_id)` renews a live lease during longer research.
- `ark_submit_public_pool_industry_gate(...)` submits the cheap identity/industry gate and returns whether deep research is authorized.
- `ark_complete_public_pool_task(...)` is allowed only after a passed gate; it submits evidence, contacts, score inputs, strategy, and an unsent opening draft.
- `ark_fail_public_pool_task(task_id, error_message)` records an operational failure.

Every contact and fact needs a public `source_url` and ISO-8601 `captured_at`. Each fact also requires confidence from 0 to 1. Social profiles need platform, public profile URL, activity level, capture time, confidence, and only observed business signals. `confirmed` and `candidate` submissions require at least one sourced fact; `unverifiable` and `rejected` may have none.

Submit `industry_relevance` and its reason through the gate first. `irrelevant` is finalized by that endpoint as `gate_only`; never call the full completion tool afterward. Enterprise knowledge references contain only `document_id`, immutable `revision_id`, and `version_no`; they are not public evidence and never go in `facts`.

Score component maxima are controlled by Ark: industry fit 25, pain/switch trigger 20, intent/reactivation 20, buying capacity 15, reachability 10, timing 10, and risk penalty 30. Ark recomputes grade, likelihood band, evidence confidence, and priority. Do not submit a probability percentage.

The sidecar automatically injects `agent_id` and the lease token. Do not include, request, log, or disclose either secret. A task completion writes research for human review only; it does not send an email or message.
