# Customer After-sales Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development for every behavior change. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a production-ready customer after-sales module covering registration, evidence, versioned SOP analysis, AI advice, salesperson decisions, conditional approval, DingTalk notification, execution, and closure.

**Architecture:** Add a self-contained `app/aftersales` backend domain and a `views/aftersales` frontend domain. The Ark database stores immutable business snapshots and workflow history; the business database remains read-only. Workflow transitions, compensation classification, approval identity, optimistic locking, and notification idempotency are enforced in the service layer.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Alembic, Pydantic, Vue 3, Element Plus, Vite, pytest.

---

## File map

### Backend domain

- `backend/app/aftersales/models.py`: six persisted aggregates and indexes.
- `backend/app/aftersales/schemas.py`: request/response contracts and AI JSON validation.
- `backend/app/aftersales/rules.py`: pure evidence, compensation, and state-transition rules.
- `backend/app/aftersales/query_service.py`: read-only customer/order/product selectors and paginated queries.
- `backend/app/aftersales/sop_service.py`: DOCX/PDF storage, structured extraction, activation, and citation lookup.
- `backend/app/aftersales/ai_service.py`: prompt assembly, `app.ai.service.chat`, structured result validation, one correction retry, and manual fallback.
- `backend/app/aftersales/notification_service.py`: outbox rows, DingTalk delivery, retry, and idempotency.
- `backend/app/aftersales/file_service.py`: authenticated evidence storage and validation under a configured root.
- `backend/app/aftersales/service.py`: case lifecycle, workflow transaction boundaries, approver snapshots, execution, and close.
- `backend/app/aftersales/router.py`: thin authenticated HTTP endpoints using `ok()`.
- `backend/app/aftersales/__init__.py`: domain package marker.

### Backend integration

- `backend/alembic/versions/057_add_aftersales.py`: all after-sales tables, indexes, and FKs.
- `backend/app/routers.py`: register `/api/aftersales`.
- `backend/app/auth/service.py`: seed `aftersales:read`, `write`, `admin`, and data permission `read_all`.
- `backend/app/core/config.py`: evidence storage root and public detail base URL through Settings.
- `backend/app/bootstrap/seed_ai.py`: register `aftersales_solution_advice` preset metadata without hardcoded provider credentials.

### Frontend

- `frontend/src/api/aftersales.js`: all module requests through the registered API client.
- `frontend/src/api/clients.js`: register `aftersalesClient`.
- `frontend/src/config/navigation.js`: 售后单、待我审核、SOP 管理、售后分析 entries.
- `frontend/src/views/aftersales/AfterSalesList.vue`: DESIGN.md-compliant list page.
- `frontend/src/views/aftersales/AfterSalesWorkspace.vue`: thin page shell.
- `frontend/src/views/aftersales/composables/useAfterSalesWorkspace.js`: form, AI, decision, review, and lifecycle orchestration.
- `frontend/src/views/aftersales/components/CaseRegistration.vue`: customer/order/product/problem fields.
- `frontend/src/views/aftersales/components/EvidencePanel.vue`: evidence upload, preview, completeness, and differences.
- `frontend/src/views/aftersales/components/AiDecisionPanel.vue`: SOP citations, responsibility, measures, compensation, and English reply.
- `frontend/src/views/aftersales/components/ApprovalRoute.vue`: approval path and immutable audit history.
- `frontend/src/views/aftersales/components/ReviewActions.vue`: return/reject/approve controls.
- `frontend/src/views/aftersales/SopManagement.vue`: upload, parse preview, and activate SOP versions.
- `frontend/src/views/aftersales/AfterSalesAnalytics.vue`: first-phase aggregate metrics.

---

### Task 1: Lock business rules with failing unit tests

**Files:**
- Create: `backend/tests/test_aftersales_rules.py`
- Create: `backend/app/aftersales/rules.py`

- [ ] Write failing tests proving that value-bearing actions always set `has_compensation`, freight payer changes `return_inspection` classification, and custom company cost is compensation.
- [ ] Run `cd backend && pytest tests/test_aftersales_rules.py -v`; verify failure is caused by the missing module.
- [ ] Implement `classify_compensation(actions) -> tuple[bool, Decimal]` with server-side totals based on action details.
- [ ] Add failing tests for evidence score/missing items for overview image, close-up image, batch label, care note, and conditional video.
- [ ] Implement `evaluate_evidence(issue_type, batch_no, care_note, evidence)` as a pure function.
- [ ] Add failing tests for every legal and illegal transition, especially supervisor compensation routing and director-only final approval.
- [ ] Implement `next_status(current_status, actor_role, decision, has_compensation)` and keep all state constants in this module.
- [ ] Run the focused test file and keep output clean.

### Task 2: Persist auditable after-sales aggregates

**Files:**
- Create: `backend/app/aftersales/models.py`
- Create: `backend/alembic/versions/057_add_aftersales.py`
- Modify: `backend/tests/conftest.py`
- Test: `backend/tests/test_aftersales_models.py`

- [ ] Write failing model tests for case number uniqueness, review round uniqueness, notification event-recipient uniqueness, and DECIMAL compensation fields.
- [ ] Run the tests and verify model/table failures.
- [ ] Define `AfterSalesCase`, `AfterSalesEvidence`, `AfterSalesAiRun`, `AfterSalesReview`, `AfterSalesEvent`, `AfterSalesSopVersion`, and `AfterSalesNotificationLog`; use `noload` relationships.
- [ ] Create migration revision `057_add_aftersales` with `mysql.INTEGER(unsigned=True)` for every `ark_users.id` FK and revision id under 32 characters.
- [ ] Immediately stage only the migration file with `git add backend/alembic/versions/057_add_aftersales.py`.
- [ ] Extend the SQLite business fixtures only where selector tests need missing product/order columns.
- [ ] Run `pytest tests/test_aftersales_models.py -v` and `alembic heads`.

### Task 3: Define contracts and read-only selectors

**Files:**
- Create: `backend/app/aftersales/schemas.py`
- Create: `backend/app/aftersales/query_service.py`
- Test: `backend/tests/test_aftersales_queries.py`

- [ ] Write failing tests that customer search returns snapshots, order search requires and filters by `company_id`, and product search excludes disabled products.
- [ ] Add Pydantic contracts for creation, update, decision, review, execution, close, SOP, AI result, pagination, and selectors.
- [ ] Implement parameterized cross-database SQL against configured `BUSINESS_DB_NAME` without mutating the business database.
- [ ] Add failing tests that custom product/spec fields are mutually exclusive with standard IDs and feedback date cannot precede purchase date.
- [ ] Implement schema validators and query pagination.
- [ ] Run focused tests.

### Task 4: Implement SOP upload, parsing, preview, and activation

**Files:**
- Create: `backend/app/aftersales/sop_service.py`
- Create: `backend/app/aftersales/file_service.py`
- Test: `backend/tests/test_aftersales_sop.py`
- Fixture: `backend/tests/fixtures/aftersales_sop.docx`

- [ ] Create a minimal DOCX fixture containing unified flow, A/B/C/D rules, two issue cards, and English reply sections.
- [ ] Write failing tests for heading/paragraph/table extraction, issue mapping, active-version uniqueness, path containment, MIME/extension limits, and immutable referenced versions.
- [ ] Implement DOCX parsing with `python-docx`; PDF text extraction must fail with an actionable unsupported-parser message if the installed runtime cannot parse it.
- [ ] Store original files under `AFTERSALES_STORAGE_ROOT/sop/<uuid>/` and persist structured sections as JSON.
- [ ] Activate exactly one version transactionally and record an immutable event.
- [ ] Run focused tests.

### Task 5: Implement AI advice and English reply

**Files:**
- Create: `backend/app/aftersales/ai_service.py`
- Modify: `backend/app/bootstrap/seed_ai.py`
- Test: `backend/tests/test_aftersales_ai.py`

- [ ] Write failing tests for minimal prompt inputs, active SOP requirement, citation existence validation, responsibility/action code validation, compensation caveat enforcement, and one repair retry.
- [ ] Implement the `AfterSalesAiResult` schema matching the approved requirement JSON.
- [ ] Assemble only relevant SOP sections and evidence summaries; call `from app.ai.service import chat` with preset `aftersales_solution_advice`.
- [ ] Persist every run before returning; never overwrite an older run.
- [ ] On invalid JSON, perform one correction call; after a second failure set `ai_failed` and preserve a usable manual path.
- [ ] Ensure compensation replies contain `subject to final internal approval` before final approval.
- [ ] Run focused tests.

### Task 6: Implement lifecycle and approval state machine

**Files:**
- Create: `backend/app/aftersales/service.py`
- Test: `backend/tests/test_aftersales_workflow.py`

- [ ] Write failing tests for create/update/delete ownership, edit locks after submit, evidence gating, approver snapshot resolution, and missing DingTalk binding errors.
- [ ] Implement case creation with `AS-YYYYMMDD-NNN` number generation protected by retry on unique collision.
- [ ] Resolve current supervisor through `supervisor_relation_history` and map business user IDs to active Ark users; resolve exactly one configured/default sales director.
- [ ] Write failing tests for submit idempotency, optimistic version conflict, withdraw-before-review, and immutable workflow rounds.
- [ ] Implement transactional submit/review/withdraw with `version` checking and idempotency keys.
- [ ] Write failing tests proving non-compensation supervisor approval reaches `approved`, compensation reaches `awaiting_director`, and only the snapshotted director can finish it.
- [ ] Implement return, reject, approve, execute, close, reopen/admin proxy reason, and immutable events.
- [ ] Run focused workflow tests.

### Task 7: Implement DingTalk outbox and retry

**Files:**
- Create: `backend/app/aftersales/notification_service.py`
- Test: `backend/tests/test_aftersales_notifications.py`

- [ ] Write failing tests proving workflow commits survive DingTalk failures, duplicate business events produce one notification row, and retries stop after three automatic attempts.
- [ ] Create notification rows inside the business transaction and deliver only after commit.
- [ ] Use existing `get_work_notifier()` and persist pending/success/failed, attempt count, next retry, and sanitized error summary.
- [ ] Log failures with both `logger.warning` and `print(..., flush=True)`.
- [ ] Implement manual retry for administrators without creating duplicates.
- [ ] Run focused tests.

### Task 8: Expose authenticated API endpoints

**Files:**
- Create: `backend/app/aftersales/router.py`
- Create: `backend/app/aftersales/__init__.py`
- Modify: `backend/app/routers.py`
- Modify: `backend/app/auth/service.py`
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_aftersales_api.py`

- [ ] Write failing API tests for unified response envelopes, permissions, data scope, current-reviewer identity, upload/download authorization, and validation errors.
- [ ] Implement thin endpoints from section 14 of the requirement, including analytics summary and authenticated evidence download.
- [ ] Seed `aftersales:read`, `aftersales:write`, `aftersales:admin`, and `aftersales:read_all` with correct kind metadata.
- [ ] Register the router once at `/api/aftersales`.
- [ ] Add Settings fields for storage root and detail URL; never read environment variables directly.
- [ ] Run API tests and the full backend test suite.

### Task 9: Register the frontend API and navigation

**Files:**
- Create: `frontend/src/api/aftersales.js`
- Modify: `frontend/src/api/clients.js`
- Modify: `frontend/src/config/navigation.js`

- [ ] Register one after-sales API client through the existing client factory.
- [ ] Add typed-by-convention request functions for every implemented endpoint.
- [ ] Add the four navigation entries; use `aftersales:read` for visible pages and `aftersales:admin` for SOP management.
- [ ] Use global permission directives for buttons; do not add page-local permission logic.

### Task 10: Build the list and case workspace

**Files:**
- Create: `frontend/src/views/aftersales/AfterSalesList.vue`
- Create: `frontend/src/views/aftersales/AfterSalesWorkspace.vue`
- Create: `frontend/src/views/aftersales/composables/useAfterSalesWorkspace.js`
- Create: `frontend/src/views/aftersales/components/CaseRegistration.vue`
- Create: `frontend/src/views/aftersales/components/EvidencePanel.vue`
- Create: `frontend/src/views/aftersales/components/AiDecisionPanel.vue`
- Create: `frontend/src/views/aftersales/components/ApprovalRoute.vue`
- Create: `frontend/src/views/aftersales/components/ReviewActions.vue`

- [ ] Reproduce the approved prototype hierarchy using project tokens and Element Plus, not prototype-only CSS or React components.
- [ ] Implement the list with `useListPage`, `.table-card`, `.list-table`, `min-width`, overflow tooltips, pagination, and no striped/centered columns.
- [ ] Implement linked customer/order/product selectors, custom spec modes, date/amount validation, and unsaved-change warning.
- [ ] Integrate `AppUpload` with evidence types and per-type limits; show server-derived completeness and missing items.
- [ ] Implement AI progress, failure/manual fallback, citations, responsibility difference, action selection, compensation breakdown, and editable English reply.
- [ ] Lock all business fields after submission; enable reply copy only after final approval.
- [ ] Implement reviewer mode, required return/reject reasons, compensation confirmation, execution, close, and audit timeline.
- [ ] Keep `AfterSalesWorkspace.vue` under 500 lines by placing all state and methods in the composable.

### Task 11: Build SOP management and analytics

**Files:**
- Create: `frontend/src/views/aftersales/SopManagement.vue`
- Create: `frontend/src/views/aftersales/AfterSalesAnalytics.vue`

- [ ] Build SOP version upload, parse result preview, problem mapping confirmation, activation, and active-state display.
- [ ] Build first-phase metrics for issue type, responsibility, grade, product/batch, compensation total, and cycle time.
- [ ] Make partial/empty states actionable and keep one primary action per surface.

### Task 12: Verify the complete system

**Files:**
- Modify: `docs/api-reference.md`
- Modify: `docs/database.md`
- Modify: `docs/module-notes.md`
- Modify: `docs/requirements/2026-07-10-customer-after-sales-management.md` only if implementation decisions differ.

- [ ] Run `cd backend && alembic upgrade head` against the local development database.
- [ ] Upload the real SOP from `C:/Users/windb/Downloads/09_Documents_Notes/2026-07-10_售后问题解决sop-评估与优化版_02.docx`, preview it, and activate it.
- [ ] Run the full no-compensation path: create → evidence → AI → decision → submit → supervisor approve → execute → close.
- [ ] Run the full compensation path: create → evidence → AI → compensation → submit → supervisor approve → director approve → copy English reply → execute → close.
- [ ] Verify return, reject, withdraw, duplicate submit/review, stale version, AI failure, and DingTalk failure/retry paths.
- [ ] Run `cd backend && pytest`, `cd frontend && npm run build`, and `python scripts/check_conventions.py`.
- [ ] Compare the rendered workspace against `docs/requirements/customer-after-sales-prototype/` and `DESIGN.md`.
- [ ] Review motion against `review-animations/STANDARDS.md`; reject `transition: all`, `scale(0)`, `ease-in`, layout animation, missing reduced motion, or ungated hover motion.
- [ ] Dispatch an independent adversarial review focused on boundary conditions, concurrent writes, idempotency, migration safety, and frontend/backend contract consistency; resolve every P0/P1/P2 finding.
- [ ] Update API/database/module documentation with the actual implementation and verification evidence.

## Completion criteria

The module is complete only when every acceptance criterion in section 18 of the requirement has direct automated or runtime evidence, both approval branches reach closure, no value-bearing action can bypass the director, all notifications are auditable and retryable, the real SOP is active locally, and the full test/build/convention gates pass.
