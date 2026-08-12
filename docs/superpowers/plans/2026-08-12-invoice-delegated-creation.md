# Invoice Delegated Creation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an authorized assistant create invoices for selected salespeople while customer scope, invoice ownership, and OKKI performance attribution remain with the selected salesperson.

**Architecture:** Persist explicit delegate-to-salesperson grants. Centralize authorization and invoice visibility in a focused invoice delegation service; keep `sales_user_id` as business ownership and `created_by` as audit identity. Expose the same contract to invoice entry and the existing user-management editor.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, Pydantic, Vue 3, Element Plus, Node test runner, pytest.

---

### Task 1: Persistence and delegation service

**Files:**
- Create: `backend/alembic/versions/106_invoice_delegate_grants.py`
- Modify: `backend/app/invoice/models.py`
- Create: `backend/app/invoice/delegation_service.py`
- Test: `backend/tests/test_invoice_delegation.py`

- [ ] Write failing service tests for self-assignment, authorized assignees, invalid/inactive users, atomic grant replacement, and authorization checks.
- [ ] Run `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_invoice_delegation.py -q` and verify failures are caused by missing model/service.
- [ ] Add `InvoiceDelegateGrant` with unique `(delegate_user_id, sales_user_id)` and implement `list_assignees`, `replace_grants`, and `ensure_can_delegate`.
- [ ] Run the focused test and verify it passes.
- [ ] Commit migration, model, service, and tests.

### Task 2: Backend invoice contracts and data scope

**Files:**
- Modify: `backend/app/invoice/schemas.py`
- Modify: `backend/app/invoice/router.py`
- Modify: `backend/app/invoice/service.py`
- Test: `backend/tests/test_invoice_delegation.py`
- Test: `backend/tests/test_invoice_scope.py`
- Test: `backend/tests/test_invoice_customer_filters.py`

- [ ] Write failing HTTP/service tests proving B can select A only when granted, A-private search uses A's OKKI owner, forged salesperson IDs fail, and create persists `created_by=B` with `sales_user_id=A` and A-derived snapshots.
- [ ] Write failing visibility tests proving A sees delegated orders, B sees only orders B created for currently authorized assignees, unrelated users see none, and grant revocation removes B access without affecting A.
- [ ] Run the focused tests and verify the expected authorization/contract failures.
- [ ] Add assignee and grant-management endpoints, accept `sales_user_id` in private searches and create payloads, enforce authorization, derive salesperson snapshots server-side, and update list/detail guards to the new ownership rules.
- [ ] Run all three focused test modules and verify they pass.
- [ ] Commit backend API and data-scope behavior.

### Task 3: Frontend invoice entry

**Files:**
- Modify: `frontend/src/api/invoice.js`
- Modify: `frontend/src/views/invoice/composables/invoiceEditorState.js`
- Modify: `frontend/src/views/invoice/composables/useInvoiceEditor.js`
- Modify: `frontend/src/views/invoice/InvoiceManage.vue`
- Test: `frontend/tests/invoiceDelegation.test.mjs`

- [ ] Write failing frontend contract tests for assignee API functions, `sales_user_id` payload, assignee-aware private search, readonly salesperson snapshots, and customer reset when assignee changes.
- [ ] Run `node --test tests/invoiceDelegation.test.mjs` from `frontend` and verify it fails on missing behavior.
- [ ] Add the assignee selector, default it to the current user, pass it through customer/contact searches and create payload, reset customer-dependent state on change, and make salesperson contact fields readonly.
- [ ] Run the focused frontend test and verify it passes.
- [ ] Commit invoice-entry UI behavior.

### Task 4: User-management grant configuration

**Files:**
- Modify: `frontend/src/api/userManagement.js`
- Modify: `frontend/src/views/system/UserManagement.vue`
- Test: `frontend/tests/invoiceDelegation.test.mjs`

- [ ] Extend the failing frontend tests with grant read/write APIs and the user editor multiselect/save flow.
- [ ] Run the focused test and verify failure is caused by missing grant management.
- [ ] Add grant APIs and the “可代创建订单的业务员” multiselect to the existing user editor; load on edit and save after the user record, surfacing any failure.
- [ ] Run the focused test and verify it passes.
- [ ] Commit the administrator configuration UI.

### Task 5: Documentation and completion gates

**Files:**
- Modify: `docs/api-reference.md`
- Modify: `docs/database.md`
- Modify: `docs/module-notes.md`

- [ ] Document the new table, endpoints, identity semantics, authorization rules, and operational configuration path.
- [ ] Run backend invoice tests and auth/user-management tests affected by the changes.
- [ ] Run all frontend tests and `npm run build`.
- [ ] Run `python scripts/check_conventions.py` and `git diff --check`.
- [ ] Inspect the migration against all branches and run Alembic upgrade in the test/dev-compatible environment.
- [ ] Perform adversarial review for boundary conditions, privilege escalation, revoked grants, front/back contract drift, OKKI attribution, and every invoice visibility call site; fix every confirmed issue and rerun affected gates.
- [ ] Commit documentation and final fixes.

