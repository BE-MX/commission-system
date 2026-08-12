# MCP Agent Token Management Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and ship a permission-protected UI for issuing, inspecting, rotating, and revoking external Agent MCP credentials.

**Architecture:** Extend the existing `/api/mcp` admin router with candidate summaries and atomic token rotation, while keeping plaintext secrets response-only. Add one focused Vue management page backed by a small API module and pure presentation helpers, then register it in the existing navigation source of truth.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, pytest, Vue 3 Composition API, Element Plus, Axios, Node test runner, Vite.

---

## File map

- `backend/app/mcp/token_admin.py`: MCP admin query, issue, rotate, and revoke endpoints.
- `backend/tests/test_mcp_token_admin.py`: API behavior and security regression coverage.
- `frontend/src/api/clients.js`: shared authenticated MCP API client.
- `frontend/src/api/mcpTokens.js`: token-management request wrappers.
- `frontend/src/views/system/mcpTokenManagement.js`: pure formatting, filtering, readiness, and connection-config helpers.
- `frontend/src/views/system/McpTokenManagement.vue`: complete management workflow UI.
- `frontend/src/config/navigation.js`: permission-protected route and menu entry.
- `frontend/tests/mcpTokenManagement.test.mjs`: frontend behavior and secret-handling contract tests.

### Task 1: Lock down backend behavior with failing tests

**Files:**
- Create: `backend/tests/test_mcp_token_admin.py`
- Modify: `backend/app/mcp/token_admin.py`

- [ ] Create an in-memory FastAPI test app containing auth, knowledge membership, and MCP token tables.
- [ ] Add tests proving candidate search returns only active users plus `has_knowledge_read`, `knowledge_library_count`, and `active_token_count`.
- [ ] Add tests proving issue rejects inactive users and blank labels and returns plaintext only on creation.
- [ ] Add tests proving rotate creates a replacement and revokes the old row in one request.
- [ ] Run `python -m pytest tests/test_mcp_token_admin.py -q` from `backend`; expect failures before implementation.
- [ ] Implement grouped metadata lookup, strict request validation, active-user validation, and `POST /tokens/{id}/rotate` in `token_admin.py`.
- [ ] Re-run the focused test; expect all cases to pass.

### Task 2: Add testable frontend behavior

**Files:**
- Create: `frontend/tests/mcpTokenManagement.test.mjs`
- Create: `frontend/src/views/system/mcpTokenManagement.js`
- Create: `frontend/src/api/mcpTokens.js`
- Modify: `frontend/src/api/clients.js`
- Modify: `frontend/src/config/navigation.js`

- [ ] Write tests for knowledge readiness, token filtering, fixed MCP endpoint, generated Agent JSON config, menu permission, and absence of browser persistence APIs.
- [ ] Run `node --test tests/mcpTokenManagement.test.mjs` from `frontend`; expect failure because helpers and page do not exist.
- [ ] Implement pure helpers with `MCP_ENDPOINT = 'https://leshine.work/mcp/'` and JSON config using an `Authorization: Bearer <token>` header.
- [ ] Add authenticated API wrappers for list, candidates, issue, rotate, and revoke.
- [ ] Register `/system/mcp-tokens` under System Management and include `mcp:admin` in group visibility.
- [ ] Re-run the Node test; expect helper and navigation assertions to pass.

### Task 3: Implement the management page

**Files:**
- Create: `frontend/src/views/system/McpTokenManagement.vue`

- [ ] Build the compact endpoint header, summary metrics, filters, token table, and empty state with existing Element Plus and `GlassButton` primitives.
- [ ] Build remote account search and display separate permission and membership readiness signals.
- [ ] Disable issuance for accounts not ready for knowledge access and link to role and knowledge administration pages.
- [ ] Implement revoke and atomic rotate confirmations without optimistic mutations.
- [ ] Implement a one-time secret dialog with copy-token and copy-config actions; clear the token object on `closed` and never write it to URL, logs, or storage.
- [ ] Add only 160–200ms state/reveal transitions and disable them under `prefers-reduced-motion`.
- [ ] Run `node --test tests/mcpTokenManagement.test.mjs`; expect all cases to pass.

### Task 4: Verify and document the finished slice

**Files:**
- Modify only files required by failures discovered in this feature.

- [ ] Run `python -m pytest tests/test_mcp_token_admin.py tests/test_mcp_knowledge.py -q` from `backend`; expect pass.
- [ ] Run `node --test tests/mcpTokenManagement.test.mjs` from `frontend`; expect pass.
- [ ] Run `npm run build` from `frontend`; expect Vite production build success.
- [ ] Run `python scripts/check_conventions.py`; expect pass.
- [ ] Run `git diff --check` and inspect `git status --short`; expect no whitespace errors or unrelated files.
- [ ] Review the UI against the approved design and animation standards, fixing only requirement gaps.
- [ ] Commit the implementation with an English intent-focused message.

### Task 5: Land, deploy, and live verify

**Files:**
- No source changes unless live verification exposes a feature defect.

- [ ] Confirm the main worktree has no overlapping/unowned changes; do not stash or include them.
- [ ] Fast-forward merge the feature branch into `main`.
- [ ] Run the project deployment command `deploy\\deploy.bat` only from a clean deployable tree.
- [ ] Verify the deployed API rejects unauthenticated access and the authenticated page loads for an `mcp:admin` session.
- [ ] Verify endpoint copy, candidate search, readiness blocking, one-time secret clearing, rotate, and revoke interactions without retaining a production test token.
- [ ] Run `python scripts/git_sweep.py --json` and report any unrelated dirty worktree separately.
