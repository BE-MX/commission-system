# Customer Picker Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let design-appointment users find an allowed customer by customer name or contact name without exposing customer IDs in the picker.

**Architecture:** Keep the existing customer-media endpoint and appointment submission contract. Extend the customer-scope query with a correlated `EXISTS` against `customer_contacts`, and add a separate exact-ID lookup for server-side access validation so removing ID autocomplete cannot break submission.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, pytest, Vue 3, Element Plus, Node test runner.

---

## File map

- `backend/app/customer_image/service.py`: owns scoped customer search and exact scoped lookup.
- `backend/app/customer_media/service.py`: validates the submitted internal customer ID through the exact scoped lookup.
- `backend/tests/test_customer_image_service.py`: proves customer/contact search, no ID autocomplete, deduplication, and ownership scope.
- `backend/tests/test_design_request_contract.py`: proves appointment submission can still validate the internal customer ID.
- `frontend/src/views/design/appointmentContract.js`: formats a customer option without an ID.
- `frontend/src/components/design/CustomerInfoPicker.vue`: presents name/contact search copy and ID-free labels.
- `frontend/tests/designAppointmentContract.test.mjs`: locks the customer picker display contract.

### Task 1: Backend customer search and exact validation

**Files:**
- Modify: `backend/tests/test_customer_image_service.py`
- Modify: `backend/tests/test_design_request_contract.py`
- Modify: `backend/app/customer_image/service.py`
- Modify: `backend/app/customer_media/service.py`

- [ ] **Step 1: Add failing search tests**

Add a `_seed_contact` fixture helper and tests that seed two customers and contacts, then assert:

```python
assert [row["id"] for row in list_available_customers(db, 99, True, "Alpha")] == ["c1"]
assert [row["id"] for row in list_available_customers(db, 99, True, "Alice")] == ["c2"]
assert list_available_customers(db, 99, True, "c2") == []
```

Add duplicate matching contacts for one customer and scoped snapshots for owned/unowned customers; assert each allowed customer appears once and unowned customers never appear.

- [ ] **Step 2: Add a failing appointment validation test**

Seed an allowed customer, patch `customer_media_service.user_identity` to return the test user, and assert:

```python
customer = customer_media_service.validate_customer_access(
    db,
    {"sub": "99", "roles": ["super_admin"]},
    "c1",
)
assert customer["id"] == "c1"
```

This test must remain green after ID matching is removed from autocomplete.

- [ ] **Step 3: Run the focused backend tests and verify RED**

Run:

```powershell
& 'D:\MyProgram\commission-system\backend\.venv\Scripts\python.exe' -m pytest tests/test_customer_image_service.py tests/test_design_request_contract.py -q
```

Expected: new contact-name/no-ID assertions fail because the current query matches only company name or company ID.

- [ ] **Step 4: Implement scoped search and exact lookup**

In `customer_image/service.py`, define a lightweight SQLAlchemy table expression for the existing read-only `customer_contacts` table:

```python
customer_contacts = table(
    "customer_contacts",
    column("company_id"),
    column("name"),
    schema=CustomerInfo.__table__.schema,
)
```

Extract the existing ownership-filtered customer statement into `_available_customer_statement`. Filter autocomplete with customer-name matching or a correlated contact-name `EXISTS`; do not include `CustomerInfo.company_id` in that filter. Add `get_available_customer` that applies an exact `company_id` predicate to the same scoped base statement and returns the existing `{id, name, country, origin}` shape.

In `customer_media/service.py`, replace the autocomplete-based exact validation with:

```python
customer = get_available_customer(db, user_id, is_admin(payload), customer_id)
if not customer:
    raise CustomerMediaForbidden("所选客户不存在或不在当前用户负责范围内")
return customer
```

- [ ] **Step 5: Run focused backend tests and verify GREEN**

Run the Step 3 command again. Expected: all tests pass with zero failures.

- [ ] **Step 6: Commit the backend behavior**

```powershell
git add -- backend/app/customer_image/service.py backend/app/customer_media/service.py backend/tests/test_customer_image_service.py backend/tests/test_design_request_contract.py
git commit -m "feat(design): search customers by contact name"
```

### Task 2: ID-free picker presentation

**Files:**
- Modify: `frontend/tests/designAppointmentContract.test.mjs`
- Modify: `frontend/src/views/design/appointmentContract.js`
- Modify: `frontend/src/components/design/CustomerInfoPicker.vue`

- [ ] **Step 1: Add failing frontend contract tests**

Import `readFileSync` and the new formatter, then assert:

```javascript
assert.equal(
  formatCustomerOptionLabel({ id: 'c1', name: 'Alpha Hair', country: 'US' }),
  'Alpha Hair · US',
)
assert.equal(
  formatCustomerOptionLabel({ id: 'c1', name: 'Alpha Hair', country: '' }),
  'Alpha Hair · 未知国家',
)
```

Read `CustomerInfoPicker.vue` and assert it contains `输入客户名称或联系人名称搜索` and does not contain `客户ID`, `客户 ID`, or the old `ID ${item.id}` label fragment.

- [ ] **Step 2: Run the frontend test and verify RED**

Run:

```powershell
node --test tests/designAppointmentContract.test.mjs
```

Expected: import/assertion failure because the formatter and new picker copy do not exist.

- [ ] **Step 3: Implement the minimal picker change**

Add to `appointmentContract.js`:

```javascript
export function formatCustomerOptionLabel(customer) {
  const country = String(customer?.country || '').trim() || '未知国家'
  return `${String(customer?.name || '').trim()} · ${country}`
}
```

Use the formatter for `el-option :label`, change the placeholder to `输入客户名称或联系人名称搜索`, and change the field hint to `客户来自 OKKI，提交后将关联到所选客户`.

- [ ] **Step 4: Run the frontend test and verify GREEN**

Run the Step 2 command again. Expected: all tests pass with zero failures.

- [ ] **Step 5: Commit the frontend behavior**

```powershell
git add -- frontend/src/views/design/appointmentContract.js frontend/src/components/design/CustomerInfoPicker.vue frontend/tests/designAppointmentContract.test.mjs
git commit -m "fix(design): hide customer ids in appointment picker"
```

### Task 3: Final verification, review, merge, and push

**Files:**
- Verify all files changed by Tasks 1 and 2.

- [ ] **Step 1: Run focused regression tests**

Run both focused commands from Tasks 1 and 2. Expected: zero failures.

- [ ] **Step 2: Run repository-required checks**

Run:

```powershell
# From backend/
& 'D:\MyProgram\commission-system\backend\.venv\Scripts\python.exe' -m pytest
# From frontend/
npm run build
# From the repository root
$mergeBase = git merge-base main HEAD
python scripts/check_conventions.py --base $mergeBase
```

Expected: pytest, Vite build, and convention checks exit successfully.

- [ ] **Step 3: Review the final diff**

Check `git diff main...HEAD`, all callers of `list_available_customers`, exact-ID validation, permission scope, deduplication, picker copy, and accidental unrelated changes. Because the change crosses more than three files, run the repository-required independent adversarial review before merging.

- [ ] **Step 4: Rebase and push the feature branch**

Fetch current refs, rebase onto the latest local `main`, rerun focused tests if the rebase changes the base, then push `codex/customer-picker-search`.

- [ ] **Step 5: Fast-forward main and push**

From `D:\MyProgram\commission-system`, preserve unrelated dirty files, fast-forward `main` to `codex/customer-picker-search`, verify the merged commit, and push `main` only after the fast-forward succeeds.
