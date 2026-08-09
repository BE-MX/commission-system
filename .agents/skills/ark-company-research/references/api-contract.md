# Ark lead enrichment API

All requests use `Authorization: Bearer <ARK_AGENT_TOKEN>` and JSON. `ARK_BASE_URL` excludes the trailing slash and its exact origin must equal trusted `ARK_ALLOWED_ORIGIN`. Disable redirects or revalidate the destination before every redirect; never forward authorization to another origin. Successful responses use `{ "code": 200, "message": "ok", "data": ... }`.

## Read lead

`GET {ARK_BASE_URL}/api/sales-automation/agent/leads/{company_id}`

## Submit contacts

`POST {ARK_BASE_URL}/api/sales-automation/agent/leads/{company_id}/contacts`

```json
{
  "contacts": [
    {
      "name": "Alice Buyer",
      "role": "Purchasing Manager",
      "email": "alice@example.com",
      "email_status": "unknown",
      "source_provider": "official_website",
      "source_url": "https://example.com/team",
      "captured_at": "2026-08-09T01:00:00Z",
      "confidence": 0.95
    }
  ]
}
```

Each contact requires at least `email` or `name`, plus `source_url` and `captured_at`.
If `email_status` is `valid`, `risky`, or `invalid`, both `email` and `verified_at` are required. Omit `email_status` when updating unrelated fields so a previous verification is preserved.

## Submit research

`POST {ARK_BASE_URL}/api/sales-automation/agent/leads/{company_id}/research`

```json
{
  "summary": "Evidence-based company summary",
  "facts": [
    {
      "fact_type": "channel",
      "claim": "The company operates three retail stores.",
      "source_url": "https://example.com/stores",
      "captured_at": "2026-08-09T01:10:00Z",
      "confidence": 0.95
    }
  ],
  "outreach_angles": ["small MOQ"],
  "risks": ["No public purchasing contact found"],
  "provider": "codex_web_research",
  "model": "record the actual model when available",
  "idempotency_key": "company-17-20260809"
}
```
