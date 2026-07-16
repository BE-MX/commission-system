# Invoice Accessory Products Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real-OKKI accessory products to standard pricing and invoice entry, with separate accessory details, customer-adjusted pricing, read-only summaries, exports, and one-time discount accounting.

**Architecture:** Reuse `ark_std_prices` and `ark_invoice_items` with a backward-compatible `product_kind=hair/accessory` discriminator. Keep accessory-specific search and pricing in a focused invoice-domain service, while shared line math, OKKI identity handling, and exports continue through the existing invoice pipeline. The UI presents accessories in separate components but sends one combined item list to the API.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, MySQL, pytest, Vue 3, Element Plus, Vite, Node test runner.

---

## File map

**Create**

- `backend/alembic/versions/073_invoice_accessory_products.py` — backward-compatible schema expansion.
- `backend/app/invoice/accessory_price_service.py` — OKKI candidate search, accessory standard-price CRUD/listing, customer-adjusted options.
- `backend/tests/test_invoice_accessories.py` — focused backend regression coverage.
- `frontend/src/views/invoice/components/AccessoryPriceConfig.vue` — accessory price tab content.
- `frontend/src/views/invoice/components/InvoiceAccessoryTable.vue` — invoice accessory rows only.
- `frontend/src/views/invoice/composables/accessoryPricing.js` — pure row normalization and aggregation helpers.
- `frontend/tests/invoiceAccessories.test.mjs` — pure and source-contract tests.

**Modify**

- `backend/app/invoice/models.py` — discriminators, nullable hair-only fields, accessory price identity.
- `backend/app/invoice/schemas.py` — product-kind-aware item payloads.
- `backend/app/invoice/router.py` — accessory pricing endpoints.
- `backend/app/invoice/service.py` — validation, serialization, grouped summaries, total calculation.
- `backend/app/invoice/xiaoman_service.py` — retain real-product push semantics for accessory rows.
- `backend/app/invoice/export_service.py` — separate accessory section and grouped summary.
- `backend/tests/test_invoice_amounts.py` — mixed hair/accessory totals.
- `backend/tests/test_invoice_okki_push.py` — real accessory product/SKU payload.
- `backend/tests/test_invoice_module.py` — exports and API detail shape.
- `frontend/src/api/invoice.js` — accessory price/candidate API clients.
- `frontend/src/views/invoice/InvoicePriceConfig.vue` — hair/accessory tabs and child component.
- `frontend/src/views/invoice/InvoiceManage.vue` — filtered hair table, accessory child table, four summaries, colored footer.
- `frontend/src/views/invoice/composables/useInvoiceEditor.js` — accessory rows, price selection, totals, payload.
- `frontend/src/views/invoice/invoice-manage.css` — layout and token-based footer chips.
- `frontend/src/styles/tokens.css` — invoice summary semantic colors.
- `docs/api-reference.md`, `docs/database.md`, `docs/module-notes.md`, `docs/requirements/2026-07-07-invoice-order-pricing-okki-v2.md` — final contract and behavior.

## Task 1: Schema and model compatibility

**Files:**

- Create: `backend/alembic/versions/073_invoice_accessory_products.py`
- Modify: `backend/app/invoice/models.py`
- Modify: `backend/app/invoice/schemas.py`
- Create: `backend/tests/test_invoice_accessories.py`

- [ ] **Step 1: Write failing model/schema tests**

Add tests proving old rows default to hair and accessory rows accept empty hair-only attributes:

```python
def test_invoice_item_payload_accepts_accessory_without_length_or_weight():
    body = InvoiceItemPayload(
        product_kind="accessory",
        item_type="stock",
        product_id=104881553777436,
        sku_id=104881553777819,
        product_name="Hair Gripper",
        product_display="Hair Gripper",
        model="魔术贴",
        color="Hair Gripper",
        length=None,
        net_weight_grams=None,
        quantity=10,
        price_per_piece=Decimal("2.75"),
    )
    assert body.product_kind == "accessory"
    assert body.length is None


def test_invoice_item_payload_defaults_existing_lines_to_hair():
    body = InvoiceItemPayload(
        item_type="stock",
        product_id=1,
        sku_id=2,
        product_name="Genius/18/#1/20g",
        product_display="Genius",
        model="Genius",
        color="#1",
        length="18",
        net_weight_grams="20g",
        quantity=1,
        price_per_piece=Decimal("20.00"),
    )
    assert body.product_kind == "hair"
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest tests/test_invoice_accessories.py -q`  
Expected: FAIL because `product_kind` is missing and hair-only fields are still required.

- [ ] **Step 3: Add the migration**

Create revision `073_invoice_accessory_products` with `down_revision = "072_expo_wig_color_images"`. The upgrade must:

```python
op.add_column("ark_std_prices", sa.Column("product_kind", sa.String(16), nullable=False, server_default="hair"))
op.add_column("ark_std_prices", sa.Column("accessory_name", sa.String(256), nullable=True))
op.add_column("ark_std_prices", sa.Column("accessory_model", sa.String(128), nullable=True))
op.add_column("ark_std_prices", sa.Column("accessory_color", sa.String(128), nullable=True))
op.add_column("ark_std_prices", sa.Column("product_id", sa.BigInteger(), nullable=True))
op.add_column("ark_std_prices", sa.Column("sku_id", sa.BigInteger(), nullable=True))
op.alter_column("ark_std_prices", "series_grade", existing_type=sa.String(128), nullable=True)
op.alter_column("ark_std_prices", "length", existing_type=sa.String(32), nullable=True)
op.alter_column("ark_std_prices", "weight_unit", existing_type=sa.String(32), nullable=True)
op.alter_column("ark_std_prices", "color_type", existing_type=sa.String(16), nullable=True)
op.create_unique_constraint("uq_ark_std_accessory_sku", "ark_std_prices", ["product_kind", "product_id", "sku_id"])
op.add_column("ark_invoice_items", sa.Column("product_kind", sa.String(16), nullable=False, server_default="hair"))
op.alter_column("ark_invoice_items", "net_weight_grams", existing_type=sa.String(64), nullable=True)
op.alter_column("ark_invoice_items", "length", existing_type=sa.String(128), nullable=True)
```

Downgrade first deletes `product_kind='accessory'` invoice and standard-price rows, then drops the new constraint/columns and restores the four hair-only columns to non-null. This destructive downgrade is acceptable only for an explicit rollback; normal deployment never calls it. Keep revision ID under 32 characters.

- [ ] **Step 4: Stage and apply the migration immediately**

Run:

```powershell
git add backend/alembic/versions/073_invoice_accessory_products.py
cd backend
.\.venv\Scripts\python.exe -m alembic heads
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
```

Expected: one head and current revision `073_invoice_accessory_products`.

- [ ] **Step 5: Update ORM and Pydantic models**

Add `product_kind` to `InvoiceItemPayload` and ORM models. Make only `length` and `net_weight_grams` optional; keep `color` required. Extend `StdPrice` with the six accessory identity columns and the unique constraint. Add this payload to `schemas.py` for the write endpoint:

```python
class AccessoryPricePayload(BaseModel):
    id: int | None = None
    product_id: int
    sku_id: int
    accessory_name: str = Field(min_length=1, max_length=256)
    accessory_model: str = Field(min_length=1, max_length=128)
    accessory_color: str = Field(min_length=1, max_length=128)
    price: Decimal = Field(ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=8)
```

Do not add a second accessory invoice table.

- [ ] **Step 6: Run focused tests**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest tests/test_invoice_accessories.py tests/test_invoice_module.py -q`  
Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git branch --show-current
git add backend/alembic/versions/073_invoice_accessory_products.py backend/app/invoice/models.py backend/app/invoice/schemas.py backend/tests/test_invoice_accessories.py
git commit -m "feat: add invoice accessory data model"
```

## Task 2: Accessory standard pricing and real OKKI identities

**Files:**

- Create: `backend/app/invoice/accessory_price_service.py`
- Modify: `backend/app/invoice/router.py`
- Modify: `backend/app/invoice/schemas.py`
- Modify: `backend/tests/test_invoice_accessories.py`
- Modify: `docs/api-reference.md`

- [ ] **Step 1: Add failing service tests**

Cover the discovered real sample and price behavior:

```python
def test_accessory_candidate_returns_real_product_and_sku(db, monkeypatch):
    seed_okki_product(
        product_id=104881553777436,
        sku_id=104881553777819,
        name="Hair Gripper",
        model="魔术贴",
        color="Hair Gripper",
        size=None,
        unit=None,
    )
    result = search_accessory_candidates(db, keyword="Hair Gripper")
    assert result[0]["sku_id"] == 104881553777819


def test_accessory_option_applies_customer_rule(db):
    price = seed_accessory_price(price="2.50")
    seed_customer_rule(adjust_type="fixed", adjust_value="0.25")
    result = list_accessory_options(db, customer_id="88", keyword="Hair")
    assert result[0]["standard_price"] == Decimal("2.50")
    assert result[0]["customer_price"] == Decimal("2.7500")
```

Also test rejection of disabled/missing products, duplicate product+SKU, incomplete Name/Model/Color, and no reliance on `group_name`.

- [ ] **Step 2: Verify tests fail**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest tests/test_invoice_accessories.py -q`  
Expected: FAIL because accessory price service does not exist.

- [ ] **Step 3: Implement the focused service**

Implement these public functions in `accessory_price_service.py` using the existing `StdPrice`, `CustomerPriceRule`, and `price_service.apply_rule`:

```python
def search_candidates(db: Session, keyword: str, limit: int = 30) -> list[dict]:
    rows = db.execute(text("""
        SELECT p.product_id, s.sku_id, p.name AS accessory_name,
               p.model AS accessory_model, p.color AS accessory_color
        FROM lsordertest.okki_products p
        JOIN lsordertest.okki_product_skus s ON s.product_id = p.product_id
        WHERE p.disable_flag = 0 AND s.disable_flag = 0
          AND (p.name LIKE :keyword OR p.model LIKE :keyword OR p.color LIKE :keyword)
        ORDER BY p.name, p.model, p.color, s.sku_id
        LIMIT :limit
    """), {"keyword": f"%{keyword.strip()}%", "limit": limit}).mappings().all()
    return [dict(row) for row in rows]


def list_prices(db: Session, keyword: str | None = None) -> list[dict]:
    query = db.query(StdPrice).filter(StdPrice.product_kind == "accessory")
    if keyword:
        pattern = f"%{keyword.strip()}%"
        query = query.filter(or_(
            StdPrice.accessory_name.like(pattern),
            StdPrice.accessory_model.like(pattern),
            StdPrice.accessory_color.like(pattern),
        ))
    return [serialize_accessory_price(row) for row in query.order_by(StdPrice.accessory_name).all()]


def upsert_price(db: Session, payload: AccessoryPricePayload, user_id: int | None) -> dict:
    candidate = next((row for row in search_candidates(db, payload.accessory_name)
                      if row["product_id"] == payload.product_id and row["sku_id"] == payload.sku_id), None)
    if candidate is None:
        raise ValueError("所选 OKKI 配件产品或 SKU 已失效，请重新选择")
    duplicate = db.query(StdPrice).filter(
        StdPrice.product_kind == "accessory",
        StdPrice.product_id == payload.product_id,
        StdPrice.sku_id == payload.sku_id,
        StdPrice.id != (payload.id or 0),
    ).first()
    if duplicate:
        raise ValueError("该配件产品和 SKU 已配置标准价")
    row = db.get(StdPrice, payload.id) if payload.id else StdPrice(product_kind="accessory")
    if row is None or (payload.id and row.product_kind != "accessory"):
        raise ValueError("配件标准价不存在")
    for field in ("product_id", "sku_id", "accessory_name", "accessory_model", "accessory_color", "price", "currency"):
        setattr(row, field, getattr(payload, field))
    row.updated_by = user_id
    db.add(row)
    db.flush()
    return serialize_accessory_price(row)


def list_options(db: Session, customer_id: str | None, keyword: str | None = None) -> list[dict]:
    rule = price_service.get_customer_rule_row(db, customer_id) if customer_id else None
    options = list_prices(db, keyword)
    for option in options:
        option["standard_price"] = option.pop("price")
        option["customer_price"] = price_service.apply_rule(option["standard_price"], rule)
    return options
```

Add `serialize_accessory_price` as the single row serializer. If `price_service` lacks a public rule-row getter, expose its current private lookup as `get_customer_rule_row` without changing rule semantics. `search_candidates` returns one row per SKU and deliberately ignores `group_name`.

- [ ] **Step 4: Add permission-protected endpoints**

Add:

```text
GET  /invoices/price/accessory-candidates?keyword=
GET  /invoices/price/accessories?keyword=&customer_id=
POST /invoices/price/accessories
```

Use `_PRICE_PAGE_READ` for reads, `invoice_price:write` for mutation, `ok(...)` for responses, and route all business logic through the new service.

- [ ] **Step 5: Run tests and convention check**

Run:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_invoice_accessories.py tests/test_invoice_pricing.py -q
cd ..
python scripts/check_conventions.py
```

Expected: PASS and no convention red items.

- [ ] **Step 6: Commit**

```powershell
git branch --show-current
git add backend/app/invoice/accessory_price_service.py backend/app/invoice/router.py backend/app/invoice/schemas.py backend/tests/test_invoice_accessories.py docs/api-reference.md
git commit -m "feat: add accessory standard pricing"
```

## Task 3: Invoice totals, validation, OKKI sync, and exports

**Files:**

- Modify: `backend/app/invoice/service.py`
- Modify: `backend/app/invoice/xiaoman_service.py`
- Modify: `backend/app/invoice/export_service.py`
- Modify: `backend/tests/test_invoice_accessories.py`
- Modify: `backend/tests/test_invoice_amounts.py`
- Modify: `backend/tests/test_invoice_okki_push.py`
- Modify: `backend/tests/test_invoice_module.py`

- [ ] **Step 1: Add failing mixed-invoice amount tests**

Use hair gross 100, hair discount -10, accessory gross 30, accessory discount -2, packaging 3, shipping 7, handling 2. Assert:

```python
assert detail["hair_amount"] == Decimal("100.00")
assert detail["hair_discount"] == Decimal("-10.00")
assert detail["accessory_amount"] == Decimal("30.00")
assert detail["accessory_discount"] == Decimal("-2.00")
assert invoice.product_amount == Decimal("118.00")
assert invoice.total_amount == Decimal("130.00")
assert invoice.internal_discount == Decimal("-10.00")
```

Add validation tests proving accessory rows do not require length/weight but do require model/color/real IDs. Add settlement tests proving the balance changes when an accessory row changes.

- [ ] **Step 2: Add failing OKKI/export tests**

Assert accessory rows are pushed individually:

```python
accessory = next(row for row in payload["product_list"] if row["product_id"] == 104881553777436)
assert accessory["sku_id"] == 104881553777819
assert accessory["count"] == 10
assert accessory["unit_price"] == 2.75
assert accessory["cost_amount"] == 26.50
assert all(cost["cost_name"] != "Accessory Discount" for cost in payload["cost_list"])
```

Assert Excel/HTML/PDF contain a separate accessory header and Hair/Accessory summary values.

- [ ] **Step 3: Verify focused failures**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest tests/test_invoice_accessories.py tests/test_invoice_amounts.py tests/test_invoice_okki_push.py tests/test_invoice_module.py -q`  
Expected: FAIL on missing grouped summaries and accessory validation.

- [ ] **Step 4: Implement grouped calculations and validation**

Add a single grouping helper in `service.py`:

```python
def summarize_items(items) -> dict[str, Decimal]:
    hair = [item for item in items if item.product_kind != "accessory"]
    accessories = [item for item in items if item.product_kind == "accessory"]
    return {
        "hair_amount": gross(hair),
        "hair_discount": discounts(hair),
        "accessory_amount": gross(accessories),
        "accessory_discount": discounts(accessories),
    }
```

`_refresh_invoice_totals` sets `product_amount` to the net total of all rows, sets legacy `internal_discount` to hair discount only, and never adds either discount summary again. `_serialize_item` includes `product_kind`; `serialize_detail` includes the four summaries.

Validation branches by `product_kind`. Accessory rows require `item_type=stock`, real IDs, product name/display, model, color, quantity and positive price; hair rules remain unchanged.

- [ ] **Step 5: Preserve real-product OKKI behavior**

Update product-list building only where required to accept nullable length/weight. Do not merge accessory rows. Reuse edit `unique_id`, removal snapshots, duplicate-new-SKU protection, and `cost_amount=item.total_price`.

- [ ] **Step 6: Add separate export sections**

Render hair rows in the existing table and accessory rows in a new table with Name/Model/Color/standard/customer/quantity/discount/total. Summary order must be Hair Price, Hair Discount, Accessory Amount, Accessory Discount, Packaging Quantity, Packaging, Shipping Fee, Handling Fee, Total.

- [ ] **Step 7: Run focused tests**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest tests/test_invoice_accessories.py tests/test_invoice_amounts.py tests/test_invoice_okki_push.py tests/test_invoice_module.py -q`  
Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git branch --show-current
git add backend/app/invoice/service.py backend/app/invoice/xiaoman_service.py backend/app/invoice/export_service.py backend/tests/test_invoice_accessories.py backend/tests/test_invoice_amounts.py backend/tests/test_invoice_okki_push.py backend/tests/test_invoice_module.py
git commit -m "feat: add accessories to invoice workflow"
```

## Task 4: Accessory standard-price UI

**Files:**

- Modify: `frontend/src/api/invoice.js`
- Create: `frontend/src/views/invoice/components/AccessoryPriceConfig.vue`
- Modify: `frontend/src/views/invoice/InvoicePriceConfig.vue`
- Create: `frontend/tests/invoiceAccessories.test.mjs`

- [ ] **Step 1: Add failing source-contract tests**

Read the Vue/API sources and assert:

```javascript
assert.match(priceConfig, /头发价格/)
assert.match(priceConfig, /配件价格/)
assert.match(accessoryConfig, /Hair ExtensionsTools Fee/)
assert.match(accessoryConfig, /Name/)
assert.match(accessoryConfig, /Model/)
assert.match(accessoryConfig, /Color/)
assert.doesNotMatch(accessoryConfig, /Length|Net Weight|展开选填列/)
assert.match(api, /price\/accessory-candidates/)
assert.match(api, /price\/accessories/)
```

- [ ] **Step 2: Verify failure**

Run: `cd frontend && node --test tests/invoiceAccessories.test.mjs`  
Expected: FAIL because the component and clients do not exist.

- [ ] **Step 3: Add API functions**

Add `searchAccessoryCandidates(params)`, `listAccessoryPrices(params)`, and `saveAccessoryPrice(data)` using the existing invoice client and `unwrap` helper. Do not create another axios instance.

- [ ] **Step 4: Build the child price component**

`AccessoryPriceConfig.vue` owns its loading, keyword, rows, candidate search, dialog form, and save flow. The create/edit dialog requires selection of a real OKKI product/SKU; Name/Model/Color are readonly snapshots; price is a two-decimal input. The table uses `list-table`, border, min/max widths, no centered columns, and no bare colors.

- [ ] **Step 5: Add tabs without expanding the parent further**

Keep existing hair price content in the first tab and mount `<AccessoryPriceConfig />` in the second. Do not duplicate customer-rule or color-mapping panels.

- [ ] **Step 6: Run test and build**

Run:

```powershell
cd frontend
node --test tests/invoiceAccessories.test.mjs
npm run build
```

Expected: test PASS and Vite build succeeds.

- [ ] **Step 7: Commit**

```powershell
git branch --show-current
git add frontend/src/api/invoice.js frontend/src/views/invoice/InvoicePriceConfig.vue frontend/src/views/invoice/components/AccessoryPriceConfig.vue frontend/tests/invoiceAccessories.test.mjs
git commit -m "feat: add accessory price configuration"
```

## Task 5: Invoice accessory table, summaries, colored footer, and final verification

**Files:**

- Create: `frontend/src/views/invoice/components/InvoiceAccessoryTable.vue`
- Create: `frontend/src/views/invoice/composables/accessoryPricing.js`
- Modify: `frontend/src/views/invoice/InvoiceManage.vue`
- Modify: `frontend/src/views/invoice/composables/useInvoiceEditor.js`
- Modify: `frontend/src/views/invoice/invoice-manage.css`
- Modify: `frontend/src/styles/tokens.css`
- Modify: `frontend/tests/invoiceAccessories.test.mjs`
- Modify: `frontend/tests/invoiceSettlement.test.mjs`
- Modify: `docs/database.md`
- Modify: `docs/module-notes.md`
- Modify: `docs/requirements/2026-07-07-invoice-order-pricing-okki-v2.md`

- [ ] **Step 1: Add failing pure calculation tests**

Export helpers from `accessoryPricing.js` and test:

```javascript
const rows = [
  { product_kind: 'accessory', quantity: 10, price_per_piece: 2.75, discount_amount: -1, total_price: 26.5 },
]
assert.equal(accessoryGross(rows), 27.5)
assert.equal(accessoryDiscount(rows), -1)
assert.equal(accessoryNet(rows), 26.5)
```

Add source tests for the exact accessory columns, absence of Length/Net Weight/optional toggle, readonly four summaries, and footer summary chip classes.

- [ ] **Step 2: Verify failures**

Run: `cd frontend && node --test tests/invoiceAccessories.test.mjs tests/invoiceSettlement.test.mjs`  
Expected: FAIL because the accessory helpers and component are absent.

- [ ] **Step 3: Implement pure helpers and editor state**

`normalizeAccessoryRow` returns a stock row with `product_kind:'accessory'`, real IDs, Name/Model/Color, quantity 1, standard/customer/transaction prices, discount 0, and total. `useInvoiceEditor` exposes filtered `hairItems`, `accessoryItems`, four grouped totals, `addAccessory`, `selectAccessory`, and `removeAccessory`; payload combines both kinds in `items`.

When customer changes, re-resolve each configured accessory option through the backend rather than applying customer rules in JavaScript. All total and balance watches continue using the one combined net item total.

- [ ] **Step 4: Build the accessory table component**

Columns are exactly:

```text
# / Name / Model / Color / 标准价 / 客户价 / Quantity / 折扣 / TotalPrice / 操作
```

Name uses a remote configured-accessory selector; selecting a row fills Model/Color/IDs/prices. Model and Color display the selected identity and do not permit a combination that lacks a configured standard price. Quantity and discount remain editable; standard/customer prices are readonly; transaction price follows the existing customer-price behavior.

- [ ] **Step 5: Integrate layout and readonly summaries**

Bind the existing hair table to `hairItems`. Place `InvoiceAccessoryTable` immediately below it. Rename “折扣金额” to “头发折扣”; add readonly “配件金额” and “配件折扣”. Keep controls 36px high and use no animation.

- [ ] **Step 6: Add token-based footer chips**

Add named invoice summary foreground/background tokens in `tokens.css` for hair, hair discount, accessory, accessory discount, packaging, shipping, handling, and total. Use only those variables in `invoice-manage.css`. Each footer amount becomes a compact chip; labels/operators remain neutral; Total stays visually dominant.

- [ ] **Step 7: Update docs and run frontend checks**

Document schema, total formula, API behavior, real OKKI push, and the no-group-name rule. Then run:

```powershell
cd frontend
node --test tests/invoiceAccessories.test.mjs tests/invoiceSettlement.test.mjs tests/invoiceLayout.test.mjs tests/invoicePasteImport.test.mjs tests/invoicePricePrecision.test.mjs
npm run build
```

Expected: all tests PASS and build succeeds.

- [ ] **Step 8: Run full backend and project verification**

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m alembic heads
.\.venv\Scripts\python.exe -m alembic current
cd ..
python scripts/check_conventions.py
git diff --check
```

Expected: backend full suite PASS, exactly one Alembic head/current at 073, convention check clean, and no whitespace errors.

- [ ] **Step 9: Perform required independent adversarial review**

Dispatch an independent reviewer because the change spans invoice money, migration, frontend/backend contract, OKKI identities, and exports. Reviewer must check: discount counted once, old-code migration compatibility, accessory identity idempotency, duplicate SKU behavior, edit/delete unique_id propagation, disabled SKU behavior, settlement equality, export totals, and source/API field-name consistency. Fix every confirmed issue and rerun the affected plus full verification.

- [ ] **Step 10: Review animation standards**

Confirm no new keyframes/transitions were added to the high-frequency form. Check reduced-motion impact is unchanged. Record “no new motion; approved” in the handoff.

- [ ] **Step 11: Commit final UI/docs change**

```powershell
git branch --show-current
git add frontend/src/views/invoice/components/InvoiceAccessoryTable.vue frontend/src/views/invoice/composables/accessoryPricing.js frontend/src/views/invoice/InvoiceManage.vue frontend/src/views/invoice/composables/useInvoiceEditor.js frontend/src/views/invoice/invoice-manage.css frontend/src/styles/tokens.css frontend/tests/invoiceAccessories.test.mjs frontend/tests/invoiceSettlement.test.mjs docs/database.md docs/module-notes.md docs/requirements/2026-07-07-invoice-order-pricing-okki-v2.md
git commit -m "feat: add invoice accessory entry"
```

Do not push unless the user explicitly requests cross-device synchronization.
