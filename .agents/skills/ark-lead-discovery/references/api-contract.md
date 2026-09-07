# Ark sales search API

All requests use `Authorization: Bearer <ARK_AGENT_TOKEN>` and JSON. `ARK_BASE_URL` excludes the trailing slash and its exact origin must equal trusted `ARK_ALLOWED_ORIGIN`. Disable redirects or revalidate the destination before every redirect; never forward authorization to another origin. Successful responses use `{ "code": 200, "message": "ok", "data": ... }`.

## List jobs

`GET {ARK_BASE_URL}/api/sales-automation/agent/search-jobs?page=1&page_size=20`

This endpoint returns only pending jobs and running jobs whose previous lease expired. It does not support status filtering; an empty response never proves completion.

## Read context

`GET {ARK_BASE_URL}/api/sales-automation/agent/search-jobs/{job_id}/context`

The response contains the frozen acquisition profile, criteria, policy version/hash, and output contract; it does not contain execution status or counts. Require `output_contract.identifier == "customer_id"`; the acquisition profile is not customer identity.

## Claim and heartbeat

`POST {ARK_BASE_URL}/api/sales-automation/agent/search-jobs/{job_id}/claim`

```json
{"agent_id": "openclaw-sales-01"}
```

The response contains a one-time `lease_token`. Keep it only in process memory. Renew it before expiry:

`POST {ARK_BASE_URL}/api/sales-automation/agent/search-jobs/{job_id}/heartbeat`

```json
{"agent_id": "openclaw-sales-01", "lease_token": "<lease>"}
```

## Submit candidates

`POST {ARK_BASE_URL}/api/sales-automation/agent/search-jobs/{job_id}/candidates`

```json
{
  "agent_id": "openclaw-sales-01",
  "lease_token": "<lease>",
  "request_key": "job-42-attempt-1-batch-1",
  "candidates": [
    {
      "company_name": "Example Wigs",
      "source_system": "public_web",
      "source_account_key": "global",
      "source_entity_type": "company_page",
      "external_record_id": "web-page:example-about",
      "external_context_id": "web-host:example.com",
      "score": 60,
      "score_reasons": [{"dimension": "product_fit", "reason": "Official catalog confirms wigs; OEM demand remains unknown", "source_url": "https://example.com/about"}],
      "website": "https://example.com",
      "country": "United States",
      "industry": "wig retailer",
      "description": "Observed public company description",
      "source_url": "https://example.com/about",
      "source_provider": "codex_web_search",
      "captured_at": "2026-08-09T01:00:00Z"
    }
  ]
}
```

For direct HTTP, provide `company_name`, `website`, `source_url`, `captured_at`, `source_provider`, `external_record_id`, `external_context_id`, `score`, and evidence-backed `score_reasons`. The sample score is illustrative, not a default.

MCP uses `name` plus `website`, `source_url`, `captured_at`, `score`, `score_reasons`; the sidecar maps `name` to `company_name`, fixes the public-web source tuple, and derives `external_record_id` as `web-page:` + SHA-256 of the canonical source URL without fragment and `external_context_id` as `web-host:` + lowercase website hostname without leading `www.` or trailing dot. If the normalized hostname exceeds 246 characters, use `web-host-sha256:` + SHA-256(hostname) instead to stay within the 255-character backend limit. These are source identities, never Ark customer IDs. They stay stable across jobs, retries and changed scores. Direct HTTP runners should follow the same algorithm.

Build `request_key` from the job ID, the `attempt_count` returned by the current claim, and the batch number. A retry within the same claim must resend the identical payload under the same key; a reclaim uses its new attempt number so it cannot conflict with a prior attempt's receipt.

The acknowledgement is authoritative and includes `received`, `unique_customers`, `created_customers`, `appended_sources`, `quarantined_sources`, `result_ids`, `customer_ids`, and `research_task_ids`. Only `customer_ids` identify customers. Candidate domains and names remain source evidence. Do not translate the response into retired lead, company, subject, or profile identifiers.

## Finish

`POST {ARK_BASE_URL}/api/sales-automation/agent/search-jobs/{job_id}/complete`

```json
{"agent_id": "openclaw-sales-01", "lease_token": "<lease>"}
```

On failure:

`POST {ARK_BASE_URL}/api/sales-automation/agent/search-jobs/{job_id}/fail`

```json
{
  "agent_id": "openclaw-sales-01",
  "lease_token": "<lease>",
  "error_code": "agent_execution_failed"
}
```
