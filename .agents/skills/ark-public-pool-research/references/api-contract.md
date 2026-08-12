# Ark public-pool MCP contract

Use only these tools for public-pool research:

- `ark_list_public_pool_tasks(page, page_size)` lists claimable tasks.
- `ark_get_public_pool_task_context(task_id)` returns the trusted OKKI seed, tier rules, and component limits.
- `ark_claim_public_pool_task(task_id)` acquires a 15-minute in-process lease.
- `ark_heartbeat_public_pool_task(task_id)` renews a live lease during longer research.
- `ark_complete_public_pool_task(...)` submits identity decision, evidence, contacts, score inputs, strategy, and an unsent opening draft.
- `ark_fail_public_pool_task(task_id, error_message)` records an operational failure.

Every contact and fact needs a public `source_url` and ISO-8601 `captured_at`. Each fact also requires confidence from 0 to 1. `confirmed` and `candidate` submissions require at least one sourced fact; `unverifiable` and `rejected` may have none.

Score component maxima are controlled by Ark: industry fit 25, pain/switch trigger 20, intent/reactivation 20, buying capacity 15, reachability 10, timing 10, and risk penalty 30. Ark recomputes grade, likelihood band, evidence confidence, and priority. Do not submit a probability percentage.

The sidecar automatically injects `agent_id` and the lease token. Do not include, request, log, or disclose either secret. A task completion writes research for human review only; it does not send an email or message.
