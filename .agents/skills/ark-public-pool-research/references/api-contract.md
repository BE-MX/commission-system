# Ark unified research MCP contract

Use only these `ark-sales` tools for public-pool-style research:

- `ark_search_knowledge(query, limit)` and `ark_get_knowledge_document(document_id)` read ACL-authorized published company knowledge.
- `ark_list_research_tasks(page, page_size)` lists claimable unified tasks.
- `ark_get_research_task_context(research_task_id)` returns the Ark `customer_id`, frozen input hash, task type, tier, policy, and research rules.
- `ark_claim_research_task(research_task_id)` acquires an in-process lease.
- `ark_heartbeat_research_task(research_task_id)` renews it.
- `ark_submit_research_industry_gate(research_task_id, industry_relevance, reason)` submits the gate. `gate_status=stopped` is terminal; `passed` permits bounded research.
- `ark_append_research_facts(research_task_id, agent_run_id, facts)` writes atomic evidence inside the task/Run/customer scope and returns canonical evidence references.
- `ark_complete_research_task(...)` submits `customer_research_v1` for review.
- `ark_fail_research_task(research_task_id, error_code)` records an operational failure.

The sidecar injects Agent identity and holds the lease. Never request, include, log, or disclose either secret. Task completion returns `research_task_id`, `customer_id`, task status, result review status, and evidence fact IDs. It does not qualify the customer or send a message.

Every final claim must cite a same-Run evidence envelope returned for the task's `customer_id` and frozen `input_hash`. Published company-knowledge references contain only document, immutable revision, and version IDs; they do not become customer facts.
