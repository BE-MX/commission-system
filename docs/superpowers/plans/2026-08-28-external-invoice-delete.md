# CODEX External Invoice Deletion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow an unsynced CODEX-origin invoice to be deleted from Ark and allow the same App plus `external_order_id` to create a fresh invoice afterward.

**Architecture:** Keep the existing `DELETE /api/invoice/invoices/{id}` route and transaction boundary. Extend `app.invoice.service.delete_invoice` so an `external_api` invoice deletes its linked `InvoiceIngestRequest` only after all existing OKKI and inventory guards pass, then deletes the invoice in the same transaction. No schema, public endpoint, or frontend change is needed.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, Pytest, MySQL production with SQLite test fixtures.

---

## File Map

- Modify `backend/tests/test_integration_api.py`: replace the old permanent-recovery assertion with the end-to-end create, delete, recreate, and replay contract.
- Modify `backend/tests/test_invoice_pricing.py`: replace the old source-only deletion block test with the historical-orphan case where no ingest row exists.
- Modify `backend/app/invoice/service.py`: remove the absolute `external_api` block and delete linked ingest rows after all safety guards pass.
- Modify `docs/requirements/2026-08-26-external-invoice-integration.md`: distinguish “no external delete API” from authorized deletion in Ark.
- Modify `docs/integrations/invoice-api.md`: document that Ark-side deletion releases the idempotency key.
- Modify `docs/api-reference.md`: state the exact delete guards and external resync effect.
- Modify `docs/database.md`: document the service-layer paired deletion lifecycle.
- Modify `docs/handoff.md`: remove the superseded tombstone-only deletion rule.

### Task 1: Lock deletion and recreation behavior with failing tests

**Files:**
- Modify: `backend/tests/test_integration_api.py:1229-1253`
- Modify: `backend/tests/test_invoice_pricing.py:383-401`

- [ ] **Step 1: Replace the external integration deletion test**

Replace `test_external_invoice_cannot_be_deleted_and_remains_replayable` with:

```python
def test_external_invoice_can_be_deleted_and_recreated_with_same_order_id(api):
    client, db = api
    from app.invoice import service as invoice_service

    created = client.post(
        "/api/integrations/v1/invoices", json=_submission(), headers=_headers(),
    )
    assert created.status_code == 201, created.text
    original = created.json()["data"]
    invoice = invoice_service.get_invoice(db, original["invoice_id"])

    invoice_service.delete_invoice(db, invoice)
    db.commit()

    assert db.get(Invoice, original["invoice_id"]) is None
    assert db.query(InvoiceIngestRequest).count() == 0

    recreated = client.post(
        "/api/integrations/v1/invoices", json=_submission(), headers=_headers(),
    )
    assert recreated.status_code == 201, recreated.text
    current = recreated.json()["data"]
    assert current["replayed"] is False
    assert current["request_id"] != original["request_id"]
    assert current["external_order_id"] == original["external_order_id"]
    assert db.query(Invoice).count() == 1
    request_row = db.query(InvoiceIngestRequest).one()
    assert request_row.status == "created"
    assert request_row.invoice_id == current["invoice_id"]

    replay = client.post(
        "/api/integrations/v1/invoices", json=_submission(), headers=_headers(),
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["data"]["invoice_id"] == current["invoice_id"]
```

The test intentionally uses HTTP 201 plus a new request ID as the portable proof of recreation. SQLite may reuse an integer primary-key value after physical deletion; production MySQL AUTO_INCREMENT does not.

- [ ] **Step 2: Replace the source-only unit test**

Replace `test_delete_invoice_blocked_for_external_api_source` with:

```python
def test_delete_external_api_invoice_without_ingest_record(db):
    _seed_okki(db)
    body = InvoiceCreate(
        customer_id="CUST001", customer_name="客户A", order_type="production",
        invoice_date=date(2026, 7, 7),
        items=[_custom_item(price_per_piece=Decimal("10"))],
    )
    invoice = service.create_invoice(db, body, user_id=1)
    invoice.source_type = "external_api"
    db.flush()

    service.delete_invoice(db, invoice)
    db.flush()

    assert db.query(Invoice).count() == 0
    assert db.query(InvoiceItem).count() == 0
```

This locks the approved compatibility rule: a historical `external_api` invoice without a matching ingest row is still deletable.

- [ ] **Step 3: Run both tests and verify RED**

Run from `backend`:

```powershell
D:\MyProgram\commission-system\backend\.venv\Scripts\python.exe -m pytest tests/test_integration_api.py::test_external_invoice_can_be_deleted_and_recreated_with_same_order_id tests/test_invoice_pricing.py::test_delete_external_api_invoice_without_ingest_record -q
```

Expected: two failures with `ValueError: 站点接入发票不允许删除，以保留外部订单的幂等查询结果`. Failures must occur at `delete_invoice`, not during fixture setup or API creation.

### Task 2: Delete the ingest record and invoice atomically

**Files:**
- Modify: `backend/app/invoice/service.py:210-232`
- Test: `backend/tests/test_integration_api.py`
- Test: `backend/tests/test_invoice_pricing.py`

- [ ] **Step 1: Remove the absolute source guard and add paired deletion**

Keep the OKKI and inventory checks in their current order. After the allocation safety check passes and before deleting allocations or the invoice, add:

```python
    if invoice.source_type == "external_api":
        from app.integration.models import InvoiceIngestRequest

        ingest_rows = db.query(InvoiceIngestRequest).filter(
            InvoiceIngestRequest.invoice_id == invoice.id,
        ).all()
        for row in ingest_rows:
            db.delete(row)
```

The complete ordering inside `delete_invoice` must be:

```python
    if invoice.xiaoman_order_id or invoice.sync_status in {"synced", "sync_uncertain"}:
        raise ValueError("该发票已同步或同步结果待核对，不允许删除，请先在小满侧确认")

    # Query and reject unsafe InvoiceAllocation rows here, unchanged.

    if invoice.source_type == "external_api":
        from app.integration.models import InvoiceIngestRequest

        ingest_rows = db.query(InvoiceIngestRequest).filter(
            InvoiceIngestRequest.invoice_id == invoice.id,
        ).all()
        for row in ingest_rows:
            db.delete(row)

    for row in allocations:
        db.delete(row)
    db.delete(invoice)
```

Do not call `commit()` in the service. The existing router owns the transaction boundary, so a later failure rolls back both deletions.

- [ ] **Step 2: Run the focused tests and verify GREEN**

Run from `backend`:

```powershell
D:\MyProgram\commission-system\backend\.venv\Scripts\python.exe -m pytest tests/test_integration_api.py::test_external_invoice_can_be_deleted_and_recreated_with_same_order_id tests/test_invoice_pricing.py::test_delete_external_api_invoice_without_ingest_record -q
```

Expected: `2 passed`.

- [ ] **Step 3: Verify preserved safety guards**

Run from `backend`:

```powershell
D:\MyProgram\commission-system\backend\.venv\Scripts\python.exe -m pytest tests/test_invoice_pricing.py::test_delete_invoice_blocked_when_synced tests/test_invoice_okki_push.py::test_delete_invoice_blocked_by_okki_order_id -q
```

Expected: `2 passed`; neither blocked path may delete an invoice or its ingest record.

- [ ] **Step 4: Commit the behavior change**

```powershell
git add backend/app/invoice/service.py backend/tests/test_integration_api.py backend/tests/test_invoice_pricing.py
git commit -m "fix: allow external invoice deletion"
```

### Task 3: Update the authoritative contract and operational docs

**Files:**
- Modify: `docs/requirements/2026-08-26-external-invoice-integration.md:86-92`
- Modify: `docs/integrations/invoice-api.md:216-248`
- Modify: `docs/api-reference.md:167-173`
- Modify: `docs/database.md:141-143`
- Modify: `docs/handoff.md:9`

- [ ] **Step 1: Clarify the requirements boundary**

Change the external-integration non-goal to:

```markdown
- 外部 REST API 不提供发票更新、删除、作废或提成字段。方舟人员仍可在“订单发票”页面删除尚未同步 OKKI、且没有未恢复库存的站点接入发票；删除会同时释放该 App + external_order_id，允许独立站重新同步。
```

- [ ] **Step 2: Document the public integration behavior**

After the idempotency bullets in `docs/integrations/invoice-api.md`, add:

```markdown
方舟人员可以在“订单发票”页面删除尚未同步 OKKI、且没有未恢复库存的站点接入发票。删除会同时移除该 App + external_order_id 的接入结果；独立站之后再次提交同一订单号时按首次创建处理，返回 HTTP 201，并建立新的幂等记录。外部 REST API 本身不提供删除端点。
```

- [ ] **Step 3: Update API and database reference truth**

Set the invoice delete entry in `docs/api-reference.md` to:

```markdown
- `DELETE /invoices/{id}` — 删除发票（invoice:write；已有 xiaoman_order_id、sync_status 为 synced/sync_uncertain、或存在未恢复半成品库存时拒绝；删除 external_api 发票会同事务删除接入记录，原 App + external_order_id 可重新同步）
```

Append this lifecycle sentence to the `ark_invoice_ingest_requests` entry in `docs/database.md`:

```markdown
方舟删除符合安全条件的 external_api 发票时，service 层在同一事务先删除关联接入记录再删除发票，释放 App + external_order_id 供重新同步；不依赖 FK SET NULL 留下 created 孤儿记录。
```

- [ ] **Step 4: Replace the superseded handoff rule**

Replace only the final deletion statement in the external-integration callout with:

```markdown
普通 UI/API 允许删除尚未同步 OKKI 且无未恢复库存的 external_api 发票；删除会同时释放 App + external_order_id，独立站可重新同步。
```

Do not rewrite unrelated deployment claims in the handoff callout.

- [ ] **Step 5: Verify documentation consistency**

Run from the repository root:

```powershell
rg -n "external_api|external_order_id|站点接入发票|重新同步|tombstone" docs/requirements/2026-08-26-external-invoice-integration.md docs/integrations/invoice-api.md docs/api-reference.md docs/database.md docs/handoff.md
git diff --check
```

Expected: all five documents describe Ark-side deletion and resync consistently; `docs/handoff.md` no longer says external invoices are permanently undeletable or require a tombstone workflow; `git diff --check` exits 0.

- [ ] **Step 6: Commit documentation**

```powershell
git add docs/requirements/2026-08-26-external-invoice-integration.md docs/integrations/invoice-api.md docs/api-reference.md docs/database.md docs/handoff.md
git commit -m "docs: document external invoice resync"
```

### Task 4: Full verification and adversarial review

**Files:**
- Review: `backend/app/invoice/service.py`
- Review: `backend/tests/test_integration_api.py`
- Review: `backend/tests/test_invoice_pricing.py`
- Review: all documentation modified in Task 3

- [ ] **Step 1: Run the focused invoice and integration suites**

Run from `backend`:

```powershell
D:\MyProgram\commission-system\backend\.venv\Scripts\python.exe -m pytest tests/test_integration_api.py tests/test_invoice_pricing.py tests/test_invoice_okki_push.py -q
```

Expected: all selected tests pass with zero failures.

- [ ] **Step 2: Run the full backend suite**

Run from `backend`:

```powershell
D:\MyProgram\commission-system\backend\.venv\Scripts\python.exe -m pytest -q
```

Expected: exit code 0 with zero failures. Report the actual pass and skip counts; do not reuse the historical count in `docs/handoff.md`.

- [ ] **Step 3: Run repository convention checks**

Run from the repository root:

```powershell
$base = git merge-base main HEAD
D:\MyProgram\commission-system\backend\.venv\Scripts\python.exe scripts/check_conventions.py --base $base
```

Expected: exit code 0 and no red violations.

- [ ] **Step 4: Dispatch the required independent invoice review**

Because this changes invoice logic and more than three files, dispatch a read-only reviewer with this exact scope:

```text
Review the external invoice deletion diff against main. Check boundary conditions, transaction rollback, concurrent delete versus external replay/create, idempotency-key release, missing/multiple ingest rows, retained OKKI and inventory guards, circular imports, all callers of delete_invoice, tests, and docs/API contract consistency. Report only concrete issues with file and line evidence; do not edit files.
```

Verify every reported issue against the diff. Fix confirmed issues using a failing regression test first, rerun the affected focused command, and commit with an English message describing the correction. If no issue is confirmed, make no review-only code changes.

- [ ] **Step 5: Re-run final evidence after review**

Run from the repository root after all fixes:

```powershell
$base = git merge-base main HEAD
Push-Location backend
D:\MyProgram\commission-system\backend\.venv\Scripts\python.exe -m pytest tests/test_integration_api.py tests/test_invoice_pricing.py tests/test_invoice_okki_push.py -q
Pop-Location
D:\MyProgram\commission-system\backend\.venv\Scripts\python.exe scripts/check_conventions.py --base $base
git diff --check "$base..HEAD"
git status --short
```

Expected: focused tests and conventions exit 0, diff check is clean, and `git status --short` is empty.

- [ ] **Step 6: Run the worktree sweep and push the feature backup**

```powershell
D:\MyProgram\commission-system\backend\.venv\Scripts\python.exe scripts/git_sweep.py
git branch --show-current
git push
```

Expected: current branch is `codex/external-invoice-delete`; the feature branch is backed up. Do not merge to or push `main` without the user's explicit instruction.
