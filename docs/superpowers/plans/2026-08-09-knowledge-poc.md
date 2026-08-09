# Knowledge Base POC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a deployable native knowledge base with resource ACL, immutable approval revisions, a Tiptap editor, and MCP access to authorized published content.

**Architecture:** Add a focused `app.knowledge` domain whose service layer owns ACL, state transitions, revision snapshots, search visibility, and audit. HTTP and MCP adapters call the same service functions. The Vue workbench uses Tiptap JSON as canonical content and existing navigation, API, feedback, and design-system patterns.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, MySQL, pytest, FastMCP, Vue 3, Element Plus, Tiptap 3, Vite.

---

## File map

- `backend/app/knowledge/models.py`: six knowledge tables and constraints.
- `backend/app/knowledge/schemas.py`: request/response validation and enums.
- `backend/app/knowledge/content.py`: Tiptap JSON allowlist validation and plain-text extraction.
- `backend/app/knowledge/access.py`: platform permission and library membership decisions.
- `backend/app/knowledge/service.py`: libraries, members, tree, revisions, approvals, search, and audit transactions.
- `backend/app/knowledge/router.py`: authorized HTTP endpoints and `ok()` envelopes.
- `backend/app/mcp/knowledge_tools.py`: MCP adapters reusing knowledge services.
- `backend/alembic/versions/101_knowledge_poc.py`: additive schema migration.
- `backend/tests/test_knowledge_content.py`: content validation unit tests.
- `backend/tests/test_knowledge_service.py`: ACL and approval state-machine tests.
- `backend/tests/test_knowledge_api.py`: route wiring and authorization tests.
- `backend/tests/test_mcp_knowledge.py`: published-only MCP tests and tool registration.
- `frontend/src/api/clients.js`: knowledge API client.
- `frontend/src/config/navigation.js`: permission-gated menu and route.
- `frontend/src/views/knowledge/KnowledgeWorkbench.vue`: workbench orchestration.
- `frontend/src/views/knowledge/components/KnowledgeSidebar.vue`: libraries and document tree.
- `frontend/src/views/knowledge/components/KnowledgeEditor.vue`: Tiptap editor and workflow actions.
- `frontend/src/views/knowledge/components/ApprovalQueue.vue`: reviewer queue.
- `frontend/src/views/knowledge/knowledgeState.js`: status/role capabilities.
- `frontend/tests/knowledgeState.test.mjs`: deterministic state tests.
- `docs/api.md`, `docs/database.md`, `docs/modules/knowledge.md`: deployment-facing documentation.

### Task 1: Establish content and permission contracts

- [ ] Write `backend/tests/test_knowledge_content.py` with failing cases for a valid doc/paragraph/text tree, an unknown node, a script-like node, malformed roots, and deterministic plain-text extraction.
- [ ] Run `pytest tests/test_knowledge_content.py -v` from `backend`; verify failure is `ModuleNotFoundError: app.knowledge`.
- [ ] Create `backend/app/knowledge/__init__.py` and `content.py` with a recursive allowlist for `doc`, `paragraph`, `text`, `heading`, `bulletList`, `orderedList`, `listItem`, `blockquote`, `codeBlock`, `hardBreak`, `horizontalRule`, `table`, `tableRow`, `tableHeader`, `tableCell`, and `taskList`/`taskItem`; reject all other nodes and invalid attributes.
- [ ] Run the target test and verify all cases pass.

### Task 2: Add schema and migration

- [ ] Write failing model metadata assertions in `backend/tests/test_knowledge_service.py` for the six exact table names, unique membership, unique document version, and pending-approval guard.
- [ ] Run the target test and verify it fails because models are absent.
- [ ] Create `models.py` and `schemas.py`; use BigInteger IDs, Beijing-naive timestamps matching existing domains, soft delete only on library/document, JSON body on revision, and immutable revision rows.
- [ ] Create `backend/alembic/versions/101_knowledge_poc.py` with additive upgrade and exact reverse-order downgrade.
- [ ] Import knowledge models from the established model-loading location so Alembic and application metadata discover them.
- [ ] Re-run metadata tests and run `alembic heads`; verify one head.

### Task 3: Implement ACL and libraries

- [ ] Add failing service tests using SQLite StaticPool fixtures for: creator becomes admin, viewer sees only assigned libraries, revoked membership disappears immediately, editor cannot manage members, and unauthorized library lookup is indistinguishable from missing.
- [ ] Run the selected tests and verify expected missing-function failures.
- [ ] Implement `access.py` role ranks/capabilities and `service.py` library/member operations. Platform `knowledge:*` permissions are checked from current identity; library membership is queried for every operation. Super-admin follows the repository's existing role convention.
- [ ] Add `knowledge:read`, `knowledge:write`, `knowledge:review`, and `knowledge:admin` entries to `backend/app/auth/service.py` seed data and admin-role assignment.
- [ ] Run service tests until green, then run existing auth permission tests.

### Task 4: Implement document revisions and approval state machine

- [ ] Add failing tests for folder/document creation, editor saves immutable versions, one pending approval per document, submit binds the current revision, later saves do not change the approval revision, reviewer approves, reviewer rejects with a required reason, and viewer receives only the published revision.
- [ ] Verify failures before implementation.
- [ ] Implement tree validation, version allocation, revision creation, submit/approve/reject transitions, and same-transaction audit records in `service.py`.
- [ ] Use `409` domain errors for illegal transitions and `404` domain errors for unauthorized objects.
- [ ] Run the state-machine tests and complete a mutation check by temporarily changing approval to publish `draft_revision_id`; verify the frozen-revision test fails, then restore and verify green.

### Task 5: Add HTTP API

- [ ] Write failing TestClient tests for response envelope, platform permission dependencies, unauthorized 404 behavior, member update, document CRUD, submit/review, and published-only search.
- [ ] Create `router.py` with `/libraries`, tree, document, approval, and search endpoints. Every endpoint uses `require_permission` or `require_any_permission`; all success responses use `ok()`.
- [ ] Register the router in `backend/app/routers.py` before catch-all-like routes.
- [ ] Run API and convention-focused tests until green.

### Task 6: Add MCP knowledge tools

- [ ] Write failing tests for tool registration, token identity propagation, ACL-filtered search, draft exclusion, frozen published content, unauthorized detail, and hard search limit.
- [ ] Create `backend/app/mcp/knowledge_tools.py`; tool functions call `require_identity`, create a DB session using the existing MCP pattern, invoke the shared service, and return JSON-serializable results.
- [ ] Register tools in `backend/app/mcp/server.py` and update the mount log tool list.
- [ ] Run MCP knowledge tests and existing `test_mcp_tracking.py` to prevent gateway regression.

### Task 7: Build the knowledge workbench

- [ ] Install only `@tiptap/vue-3`, `@tiptap/starter-kit`, `@tiptap/extension-link`, `@tiptap/extension-table`, `@tiptap/extension-table-row`, `@tiptap/extension-table-header`, and `@tiptap/extension-table-cell`; lock them in `package-lock.json`.
- [ ] Add failing `frontend/tests/knowledgeState.test.mjs` cases for role capabilities and draft/pending/published action availability; verify failure before creating `knowledgeState.js`.
- [ ] Implement state helpers and verify target tests green.
- [ ] Add `knowledgeClient` methods to `frontend/src/api/clients.js` and a lazy `/knowledge` route/menu entry gated by `knowledge:read` in `navigation.js`.
- [ ] Create the workbench and three focused components. Use existing feedback helpers, Design Tokens, GlassButton, Element Plus dialogs/forms, responsive layout, and no decorative editor animation. Never render stored HTML with `v-html`.
- [ ] Add save/submit/review feedback and actionable error text. Prevent accidental navigation with unsaved changes using the existing router/browser guard pattern if present.
- [ ] Run frontend unit tests and `npm run build`.

### Task 8: Documentation, migration and deployability

- [ ] Document endpoint contracts in `docs/api.md`, six tables and invariants in `docs/database.md`, and module operation/deployment in `docs/modules/knowledge.md`.
- [ ] Run migration SQL validation and apply the additive migration using the repository's documented environment command only after checking the active database URL target.
- [ ] Run focused backend tests, full backend pytest, frontend tests, frontend production build, and `python scripts/check_conventions.py --base f23643b`.
- [ ] Start the local application with project commands and execute an HTTP/MCP smoke sequence covering create library, authorize a second user, edit, submit, approve, search, and read.
- [ ] Inspect `git diff --check`, changed-file scope, migration head, package license list, and repository status.
- [ ] Perform an adversarial review focused on ACL bypass, stale-token assumptions, search leakage, frozen revision integrity, unsafe Tiptap nodes, router registration, and deploy documentation; write a failing regression test before every code fix.
- [ ] Re-run the complete verification suite after all review fixes and record exact evidence in the completion report.
