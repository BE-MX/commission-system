# Domestic Membership Pricing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver automatic domestic-customer membership, maintainable base prices, authoritative member quoting, discounted balance charging, and the corresponding admin/order UI.

**Architecture:** Keep all business logic inside `app.domestic`: `pricing_service.py` owns membership and quotes, existing balance/order services own transactions, and a single normalized base-price table avoids duplicating prices across full SKUs. The frontend requests batch quotes and sends the complete expected quote back; the server recomputes and rejects stale quotes before writing or charging.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic/MySQL, pytest/SQLite, Vue 3, Element Plus, Vite, Node contract tests.

---

## File map

- Create `backend/app/domestic/pricing_service.py`: membership thresholds, fixed-price rules, normalized price lookup, quote comparison.
- Create `backend/alembic/versions/130_domestic_member_pricing_a.py`: base-price/pricing-request tables, customer and nullable order-item snapshots, confirmed seed prices and historical backfill.
- Create `backend/alembic/versions/131_domestic_member_pricing_b.py`: final order-item NOT NULL and pricing CHECK constraints after all write paths fill snapshots.
- Create `backend/tests/test_domestic_member_pricing.py`: money boundaries, mappings, stale quotes, recharge, order charging, API contracts.
- Modify `backend/app/domestic/models.py`: `DomesticBasePrice`, `DomesticOrderPricingRequest`, customer/order-item pricing fields.
- Modify `backend/app/domestic/schemas.py`: required recharge request ID, quote/base-price/order payloads.
- Modify `backend/app/domestic/balance_service.py`: update membership only for a newly created recharge ledger.
- Modify `backend/app/domestic/customer_service.py`: remove manual membership writes and expose recharge basis.
- Modify `backend/app/domestic/product_service.py`: join/list/upsert/delete shared base prices.
- Modify `backend/app/domestic/order_service.py`: server-side quoting, snapshots, stale-quote conflict, draft repricing and charging.
- Modify `backend/app/domestic/router.py`: quote/base-price APIs and updated order contracts.
- Modify `backend/app/domestic/export_service.py`: export original and discounted unit prices.
- Modify `frontend/src/api/domestic.js`: price and quote endpoints/contracts.
- Modify `frontend/src/views/domestic/DomesticCustomers.vue`: derived membership and recharge preview/result.
- Modify `frontend/src/views/domestic/DomesticProducts.vue`: base-price column, filter, edit/delete dialog.
- Modify `frontend/src/views/domestic/composables/useDomesticOrderCreate.js`: quote state, invalidation, stale-price retry.
- Modify `frontend/src/views/domestic/DomesticOrderCreate.vue`: read-only original/discounted prices and membership context.
- Modify `frontend/src/views/domestic/composables/useDomesticOrders.js`: draft repricing confirmation.
- Modify `frontend/src/views/domestic/DomesticOrders.vue`: historical price snapshot display.
- Create `frontend/tests/domesticMemberPricing.test.mjs`: frontend pricing-state and source-contract tests.
- Modify `docs/api-reference.md`, `docs/database.md`, `docs/auto-memory/project_domestic.md`, `docs/handoff.md`.

### Task 1: Pricing domain and membership rules

- [ ] **Step 1: Write failing unit tests**

Create `backend/tests/test_domestic_member_pricing.py` with table-driven assertions for membership thresholds, three fixed-price rows, `member_fixed_capped`, every other priced SKU reduction, cap-nine-part six-length mapping, and piece-spin/full matrix equality.

```python
@pytest.mark.parametrize(("amount", "level"), [
    ("9999.99", None), ("10000", "silver"), ("30000", "black"),
    ("100000", "supreme"),
])
def test_membership_uses_latest_single_recharge(amount, level):
    assert pricing_service.resolve_membership(Decimal(amount)) == level

def test_fixed_price_precedes_reduction():
    quote = pricing_service.resolve_discount(_cap("递针顶", "20厘米"), Decimal("1798"), "black")
    assert quote == (Decimal("1598.00"), "member_fixed")
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest backend/tests/test_domestic_member_pricing.py -q`

Expected: import failure because `app.domestic.pricing_service` does not exist.

- [ ] **Step 3: Implement minimal pricing service**

Implement explicit constants and pure functions. No generic rule engine.

```python
MEMBERSHIP_REDUCTIONS = {"silver": Decimal("70"), "black": Decimal("120"), "supreme": Decimal("130")}
FIXED_CAP_PRICES = {
    ("递针旋全头套", "15厘米"): {"silver": "1048", "black": "998", "supreme": "960"},
    ("递针旋九分头", "15厘米"): {"silver": "1048", "black": "998", "supreme": "960"},
    ("递针顶", "20厘米"): {"silver": "1698", "black": "1598", "supreme": "1548"},
    ("递针顶", "25厘米"): {"silver": "2098", "black": "1998", "supreme": "1948"},
}
```

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest backend/tests/test_domestic_member_pricing.py -q`

Expected: pure pricing tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/domestic/pricing_service.py backend/tests/test_domestic_member_pricing.py
git commit -m "feat: add domestic membership pricing rules"
```

### Task 2: Schema, models, and confirmed base-price seed

- [ ] **Step 1: Add failing persistence tests**

Test the `(product_type, craft, length)` unique pricing dimensions, merged piece craft-size codes, snapshot fields, confirmed `1040`, nine-part semantics, and piece-spin/full copies through real SQLAlchemy models.

- [ ] **Step 2: Run RED**

Run: `python -m pytest backend/tests/test_domestic_member_pricing.py -q`

Expected: missing `DomesticBasePrice` and snapshot columns.

- [ ] **Step 3: Add models and migration**

Create revision `130_domestic_member_pricing_a` on top of `129_domestic_order_attributes` after verifying all branches. Add `ark_domestic_base_prices` with unique key `(product_type, craft, length)`, `ark_domestic_order_pricing_requests`, customer recharge snapshots, and nullable order-item price snapshots without server defaults. Seed exact confirmed merged piece codes and current cap codes; backfill legacy order snapshots. Leave final NOT NULL/CHECK constraints for revision 131 after Task 4 updates every write path.

- [ ] **Step 4: Verify migration and GREEN**

Run:

```bash
python -m alembic heads
python -m pytest backend/tests/test_domestic_member_pricing.py -q
python -m pytest backend/tests/test_domestic_optimizations.py -q
```

Expected: one Alembic head; all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/130_domestic_member_pricing_a.py backend/app/domestic/models.py backend/tests/test_domestic_member_pricing.py
git commit -m "feat: persist domestic member pricing"
```

### Task 3: Recharge, base-price, and quote APIs

- [ ] **Step 1: Write failing service/API tests**

Cover required recharge `request_id`, upgrade/downgrade, old-request replay after a newer recharge, current versus ledger balances, product shared-price propagation, delete-to-missing, batch quote, and missing-price responses.

- [ ] **Step 2: Run RED**

Run: `python -m pytest backend/tests/test_domestic_member_pricing.py -q`

Expected: current manual membership and absent endpoints fail assertions.

- [ ] **Step 3: Implement services and routes**

Remove membership from customer create/update writes. Update membership only after a non-replayed recharge ledger. Add `POST /pricing/quote` plus admin base-price PUT/DELETE. Confirmed poster rows are migration seeds only: every persisted standard or special SKU can form an exact `(product_type, craft, length)` key, remains missing until an admin maintains it, and then uses the normal member reduction unless it matches a fixed-price rule. Keep `domestic:admin` for price mutations and existing recharge permissions.

- [ ] **Step 4: Run GREEN and regressions**

Run: `python -m pytest backend/tests/test_domestic_member_pricing.py backend/tests/test_domestic_optimizations.py -q`

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/domestic/{schemas.py,balance_service.py,customer_service.py,product_service.py,router.py,pricing_service.py} backend/tests/test_domestic_member_pricing.py
git commit -m "feat: expose domestic pricing and membership APIs"
```

### Task 4: Authoritative order pricing and balance settlement

- [ ] **Step 1: Write failing order tests**

Cover server-authoritative create/add, complete expected-quote comparison, HTTP 409 detail, formal order discounted charge, draft reprice after recharge, quantity delta, termination refund, missing-price rollback, and create/add/submit idempotency.

- [ ] **Step 2: Run RED**

Run: `python -m pytest backend/tests/test_domestic_member_pricing.py -q`

Expected: order still trusts incoming `unit_price` and lacks snapshots.

- [ ] **Step 3: Implement transaction changes**

Replace incoming manual price with `expected_quote`; lock customer then matching base-price rows ordered by ID; recompute; raise a typed quote-conflict exception; persist snapshots; charge existing balance ledger with discounted totals. Draft submit reprices current membership and stores a persistent pricing-request idempotency record. Add revision `131_domestic_member_pricing_b` only after all write paths fill snapshots; it enforces final NOT NULL/CHECK constraints and remains chained after revision 130.

- [ ] **Step 4: Update export/detail and run GREEN**

Run: `python -m pytest backend/tests/test_domestic_member_pricing.py backend/tests/test_domestic_optimizations.py backend/tests/test_domestic_export.py -q`

Expected: pass with historical and new price semantics.

- [ ] **Step 5: Commit**

```bash
git add backend/app/domestic/{order_service.py,export_service.py,router.py,schemas.py,pricing_service.py} backend/tests/test_domestic_member_pricing.py
git commit -m "feat: charge domestic orders at member prices"
```

### Task 5: Frontend membership and pricing UX

- [ ] **Step 1: Write failing frontend contracts**

Add `frontend/tests/domesticMemberPricing.test.mjs` to assert quote invalidation, complete expected quote payloads, membership labels, missing-price blocking, and source contracts for read-only prices/admin maintenance.

- [ ] **Step 2: Run RED**

Run: `node --test frontend/tests/domesticMemberPricing.test.mjs`

Expected: absent pricing API/state/UI markers fail.

- [ ] **Step 3: Implement customer/product/order UI**

Remove manual membership input; add tier/recharge basis and preview. Add shared original-price maintenance and missing-price filter. Quote after all pricing attributes are selected; display original/discounted prices and rule; block missing or loading lines; handle 409 without losing form content. Show historical snapshots in order detail.

- [ ] **Step 4: Run GREEN and build**

Run:

```bash
node --test frontend/tests/domesticMemberPricing.test.mjs
npm run build
```

Expected: pass/build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/domestic.js frontend/src/views/domestic frontend/tests/domesticMemberPricing.test.mjs
git commit -m "feat: add domestic member pricing experience"
```

### Task 6: Documentation and final verification

- [ ] **Step 1: Synchronize platform docs**

Document new table/columns, endpoint contracts, money invariants, and rollout requirement in API/database/auto-memory/handoff docs.

- [ ] **Step 2: Run all required verification**

```bash
cd backend && python -m pytest
cd ../frontend && npm run build
cd .. && python scripts/check_conventions.py
python scripts/git_sweep.py
```

- [ ] **Step 3: Run migration dry checks**

Verify one head, migration import, upgrade/downgrade on disposable MySQL-compatible environment if available, and inspect generated DDL. Do not apply the stop-write production migration without an explicit deployment window.

- [ ] **Step 4: Independent adversarial review**

Review boundary amounts, locks, idempotency, stale quotes, ledger conservation, frontend contract, and migration safety. Fix every actionable finding and rerun relevant tests.

- [ ] **Step 5: Commit and branch handoff**

```bash
git add docs
git commit -m "docs: document domestic member pricing"
git status --short
```

Expected: clean feature worktree with all gates green.
