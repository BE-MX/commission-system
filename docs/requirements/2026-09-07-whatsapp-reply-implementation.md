# WhatsApp reply assistant implementation

Scope: implement the approved design and SOUL locally on `codex/whatsapp-reply-design`, based on main `7d65322b`. No production changes, push or deployment. All chat test data is synthetic.

## Work and evidence

1. Backend: live device/user authorization, scoped revision-bound knowledge retrieval, two bounded metadata-only AI calls, strict response validation, shared metadata idempotency and independent quota. Evidence: isolated database tests covering ACL revocation, revision changes, source purposes, injection, duplicate requests and logging.
2. Extension: both-direction loaded DOM context, reply button and preview, optional draft intent/style/goal, safe fill/restore and stale-result guards. Evidence: synthetic unit and browser tests; unchanged incoming translation boundary; build/package.
3. Integration: exact request/response contract, configuration and API/database/module documentation. At least 30 synthetic semantic scenarios, English/German at least eight each. Mock tests are not model quality evidence; actual paid benchmark requires user test authorization.
4. Independent adversarial specification and code review, fix actionable findings, convention checks, scoped test suites, local commit and handoff. Production source disclosure approval and provider retention verification remain explicit activation prerequisites.

## Frozen wire contract

POST `/api/whatsapp-translation/reply-suggestions`, normal envelope and no-store. Device token only in background. Timeout 35 seconds client / 30 seconds server. No automatic retries.

Request: `request_id` UUID; `conversation_epoch` UUID generated per page conversation instance; `context_version` nonnegative integer; `draft_version` nonnegative integer; `messages: {role: 'customer'|'salesperson', text: string}[]`; `context_scope: {requested_limit: 20|40, truncated: boolean, omitted_media: boolean, latest_visible: boolean}`; `draft_intent: string` default empty; `target_language: 'auto'|supported code`; `fallback_language: supported code` default en; `style: 'default'|'shorter'|'softer'|'alternative'` default default; `goal: string` default empty. Maximum 40 messages, 12000 message characters, 2000 draft characters and 500 goal characters. Backend may configure smaller bounds. UUIDs and versions are local synthetic identifiers, never WhatsApp identifiers.

Response: echoes `request_id`, `conversation_epoch`, `context_version`, `draft_version`; `status: 'ready'|'needs_confirmation'|'insufficient_context'`; `reply_language`; `reply_text`; `meaning_zh`; `rationale_zh`; `sources: {document_id:number, revision_id:number, version_no:number, section:string, title:string}[]`; `claims: {text:string, source_index:number, quote:string}[]`; `risk_flags:string[]`; `missing_information:string[]`. No raw model output or report/COT. A safe clarification can have no sources; never render unsanitized HTML.

Capabilities adds optional `reply: {available:boolean, max_messages:number, default_messages:number, max_context_chars:number, max_draft_chars:number, max_goal_chars:number, timeout_seconds:number}`. Missing field means unsupported backend; translation remains functional. Runtime request `reply/suggest` carries `payload` with above shape; runtime response carries `result`. Extension may add typed `reply/capabilities` transport to avoid changing existing callers.

## Source authorization

Settings hold a finite list of bindings with document ID, exact published revision, section text SHA-256, section index and policy version; purpose is method/public_fact/constraint/blocked. Mandatory policy bindings are retrieved independently of search rank. New revisions cannot inherit public permission. No production facts are approved merely by copying a published document. Missing/changed/unreadable required policies lead to safe noncommittal clarification, not unbounded generation.

## Acceptance status

Local implementation and independent review complete; model/real-UI acceptance is not yet passed. The authorized 59-call synthetic baseline found a JSON-mode omission, now fixed. Post-fix 14-case retest returned 11 suggestions and 3 safety rejections, median 9.094s/P95 18.688s. See [model baseline](2026-09-07-whatsapp-reply-model-baseline.md). No production changes, push, merge or deployment.

| Requirement | Current evidence | Boundary |
| --- | --- | --- |
| Current both-direction context, 20/40, media/unknown/old-scope signals, capability ceilings | Extension context/adapter tests and full-content Chromium 6,000-character regression | Synthetic DOM only; actual WhatsApp 1.3.0 smoke test pending |
| Language/draft/context epochs, preview/fill/restore, no send | 198 extension unit tests; 14 Chromium tests with actual Lexical, including late language changes and cancelled in-flight restore | Network intercepted; not a production backend end-to-end claim |
| Live employee/device/source ACL, source revision/hash/purpose, required policies | Reply service/source tests, revoked role/membership/device/library/revision checks during generation and cache hits | Production public-fact bindings not approved |
| Two-call facade, metadata-only logs, no query audit body, strict evidence/promise checks | Reply service/guard tests; 30 original EN/DE scenarios prepared; real slow-drip transport deadline test | Structural/regex guards are not semantic proof |
| Shared metadata idempotency, quota, no ownership takeover, cache expiry | Request-state/service tests; same-ID conflicts and another worker/restart cannot silently call again | SQLite behavior + MySQL DDL compilation; no live multi-worker MySQL contention run |
| Migration 141 / independent disabled seeds | SQLite up/down preserves existing user data; unsigned MySQL FK compilation; seed preservation regression | Shared production database untouched; actual MySQL 141 migration not run |
| Compatibility and documentation | Backend scoped suite: **268 passed, 1 skipped** (29.44s); extension package/build/test and browser run both exit 0 | Backend scope: reply, translation, knowledge, AI HTTP/call/facade; not whole repository suite |
| Adversarial review | Independent spec + quality review passed; five findings fixed with regressions | Original issues: cancelled restore, late autodetection, paragraph loss, drip timeout, capability ceilings |
| Real model baseline / business-owner blind review | Authorized 59 calls, 103,410 tokens; JSON mode fixed; 14 post-fix cases: 11 returned / 3 blocked | Full 30-case post-fix gate, rejection diagnosis, performance and semantic review unpassed; new paid calls need new budget authorization |

Convention check: no red findings; one reviewed yellow for the device-authenticated reply route. Its documented machine-to-human dependency plus service `whatsapp_reply:write`/knowledge ACL checks are intentional, not a public endpoint. API, database, module notes, extension instructions and [activation guide](2026-09-07-whatsapp-reply-activation.md) synchronized.

Extension package: `extensions/whatsapp-translation/release/whatsapp-translation-1.3.0.zip`, 36,078 bytes, SHA-256 `6ef76643c4bbe89e1ff501c8a4eb2f43b2c71a287d381f5412b56ed1698b944c`. Generated build/ZIP files are kept locally, not committed.
