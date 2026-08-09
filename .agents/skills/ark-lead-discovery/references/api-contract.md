# Ark sales search API

All requests use `Authorization: Bearer <ARK_AGENT_TOKEN>` and JSON. `ARK_BASE_URL` excludes the trailing slash and its exact origin must equal trusted `ARK_ALLOWED_ORIGIN`. Disable redirects or revalidate the destination before every redirect; never forward authorization to another origin. Successful responses use `{ "code": 200, "message": "ok", "data": ... }`.

## List jobs

`GET {ARK_BASE_URL}/api/sales-automation/agent/search-jobs?status=claimable`

`claimable` includes pending jobs and running jobs whose previous lease expired.

## Read context

`GET {ARK_BASE_URL}/api/sales-automation/agent/search-jobs/{job_id}/context`

The response contains the frozen profile, criteria, counts, status, and output contract.

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
  "request_key": "job-42-batch-1",
  "candidates": [
    {
      "name": "Example Wigs",
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

Required per candidate: `name`, `website`, `source_url`, `captured_at`.

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
  "error_message": "actionable reason"
}
```
