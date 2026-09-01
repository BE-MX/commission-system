# Domestic Order Attributes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace domestic-order wig and piece attributes from the approved Excel sheet, support special-order-only custom options, rename the existing normal/special field to order category, and add required order type and order channel fields.

**Architecture:** Keep structural order category in code, keep descriptive order and attribute values in `sys_dict`, and centralize validation/custom-option creation in a domestic-domain service. Use a schema-only Alembic migration plus an explicit preflight/apply cutover command for production dictionary and route changes. Frontend conditional behavior lives in a pure helper module so it can be tested without mounting Vue.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, Vue 3, Element Plus, Node test runner, pytest.

---

## File map

- Create `backend/alembic/versions/129_domestic_order_attributes.py`: rename order category column, add order metadata and product attribute schema.
- Create `backend/app/domestic/attribute_service.py`: option reads, validation, special-value creation, and default-route mapping.
- Create `backend/scripts/domestic_attribute_cutover.py`: guarded standard dictionary and standard route replacement.
- Create `backend/tests/test_domestic_attributes.py`: domain validation, transaction, route, and API contract tests.
- Create `backend/tests/test_domestic_attribute_cutover.py`: preflight/apply/idempotency/history-preservation tests.
- Create `frontend/src/views/domestic/domesticAttributeRules.js`: pure conditional-option and payload-normalization functions.
- Create `frontend/tests/domesticOrderAttributes.test.mjs`: frontend behavior tests.
- Modify `backend/app/domestic/constants.py`: new structural/category constants, dictionary mapping, and default route names.
- Modify `backend/app/domestic/models.py`: renamed/additional order fields and product attribute nullability.
- Modify `backend/app/domestic/schemas.py`: discriminated conditional attributes and new order fields.
- Modify `backend/app/domestic/product_service.py`: new product identity/display and optional fields.
- Modify `backend/app/domestic/order_service.py`: validate options, persist new fields, rename filters and responses.
- Modify `backend/app/domestic/router.py`: options contract and three order filters.
- Modify `backend/app/domestic/report_service.py`: rename category label in scan/report output.
- Modify `backend/app/domestic/export_service.py`: new headers and attribute/order metadata.
- Modify `frontend/src/api/domestic.js`: renamed labels and stable field constants.
- Modify `frontend/src/views/domestic/DomesticOrderCreate.vue`: category/type/channel and conditional attribute controls.
- Modify `frontend/src/views/domestic/composables/useDomesticOrderCreate.js`: normalized state, validation, route preview, and payload.
- Modify `frontend/src/views/domestic/DomesticOrders.vue`: three filters/columns/detail labels.
- Modify `frontend/src/views/domestic/composables/useDomesticOrders.js`: three filter parameters.
- Modify `frontend/src/views/domestic/DomesticProducts.vue`: conditional labels/columns.
- Modify `frontend/src/views/domestic/print/printDocs.js`: category badge and new metadata.
- Modify `backend/tests/test_domestic_export.py`, `backend/tests/test_domestic_reporting.py`, `backend/tests/test_domestic_optimizations.py`, and `backend/tests/test_domestic_wxacode.py`: new schema fixtures and export expectations.
- Modify `docs/api-reference.md`, `docs/database.md`, and `docs/auto-memory/project_domestic.md`: public contract, schema, and stable decisions.

### Task 1: Schema and order-field contract

**Files:**
- Create: `backend/alembic/versions/129_domestic_order_attributes.py`
- Modify: `backend/app/domestic/constants.py`
- Modify: `backend/app/domestic/models.py`
- Modify: `backend/app/domestic/schemas.py`
- Test: `backend/tests/test_domestic_attributes.py`

- [ ] **Step 1: Write failing schema tests**

Add tests that instantiate `OrderCreate` with `order_category="special"`, `order_type="first_order"`, and `order_channel="wechat"`; assert missing order type/channel fails. Add ProductAttrs cases for a complete cap, a piece with only craft/length, a 15厘米 cap requiring density, and a non-15厘米 cap rejecting residual density.

```python
def test_new_order_fields_are_required():
    with pytest.raises(ValidationError):
        OrderCreate(**_order_payload(order_type=None))

def test_piece_has_one_combined_craft_size_attribute():
    attrs = ProductAttrs(product_type="piece", craft="U型13*15", length="20厘米")
    assert attrs.size is None
    assert attrs.density is None

def test_density_only_exists_for_15cm_cap():
    with pytest.raises(ValidationError, match="15厘米"):
        ProductAttrs(**_cap_attrs(length="15厘米", density=None))
    attrs = ProductAttrs(**_cap_attrs(length="20厘米", density="90%"))
    assert attrs.density is None
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && pytest tests/test_domestic_attributes.py -q`

Expected: failures because `order_category`, `order_channel`, `hair_style_series`, and conditional product attributes do not exist.

- [ ] **Step 3: Add migration and minimal model/schema implementation**

Use revision `129_domestic_order_attributes`, down revision `128_shipping_inspection`. Rename `ark_domestic_orders.order_type` to `order_category`; add nullable `order_type` and `order_channel`; add nullable `ark_domestic_products.hair_style_series`; make product `size` and `density` nullable. Keep the new order columns nullable only for existing rows, while Pydantic requires them for all new/updated orders.

Define:

```python
ORDER_CATEGORIES = {"normal": "普货", "special": "特单"}
ORDER_TYPE_DICT = "domestic_order_type"
ORDER_CHANNEL_DICT = "domestic_order_channel"
DEFAULT_ROUTE_NAMES = {
    "cap": "头套网帽（递针）",
    "piece": "发片网底（递针）",
}
```

Make `ProductAttrs.size`, `density`, and `hair_style_series` optional, then normalize irrelevant fields to `None` and raise for missing required cap fields.

- [ ] **Step 4: Run migration/schema tests and verify GREEN**

Run: `cd backend && pytest tests/test_domestic_attributes.py -q`

Expected: all Task 1 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/129_domestic_order_attributes.py backend/app/domestic/constants.py backend/app/domestic/models.py backend/app/domestic/schemas.py backend/tests/test_domestic_attributes.py
git commit -m "feat: define domestic order attribute schema"
```

### Task 2: Attribute dictionaries, special custom values, and routes

**Files:**
- Create: `backend/app/domestic/attribute_service.py`
- Modify: `backend/app/domestic/router.py`
- Modify: `backend/app/domestic/order_service.py`
- Modify: `backend/app/domestic/product_service.py`
- Test: `backend/tests/test_domestic_attributes.py`

- [ ] **Step 1: Write failing service tests**

Seed standard and special `SysDict` rows, then test:

```python
def test_normal_order_rejects_custom_attribute(db):
    payload = _order(order_category="normal", craft="自定义工艺")
    with pytest.raises(ValueError, match="切换为特单"):
        order_service.create_order(db, payload, 1)

def test_special_order_creates_reusable_special_option_and_route(db, default_routes):
    result = order_service.create_order(
        db, _order(order_category="special", craft="自定义工艺"), 1
    )
    assert result["id"]
    option = db.query(SysDict).filter_by(
        type="domestic_cap_craft_special", code="自定义工艺"
    ).one()
    mapping = db.query(DomesticCraftRoute).filter_by(
        product_type="cap", craft="自定义工艺"
    ).one()
    assert mapping.route_id == default_routes["cap"].id
```

Also test duplicate reuse, order-type/channel dictionary validation, rollback with an invalid later item, and options response separation between `standard_values` and `special_values`.

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && pytest tests/test_domestic_attributes.py -q`

Expected: failures because `attribute_service` and the new options contract are missing.

- [ ] **Step 3: Implement the domestic attribute service**

Expose focused functions:

```python
def get_order_options(db: Session) -> dict: ...
def validate_order_dimensions(db: Session, order_type: str, order_channel: str) -> None: ...
def prepare_item_attrs(
    db: Session, *, order_category: str, attrs: ProductAttrs, user_id: int
) -> ProductAttrs: ...
```

`prepare_item_attrs` validates every visible field against its standard type. For special orders it creates missing values in `<standard_type>_special` using a nested transaction. If the field is craft, it validates the fixed product-type route and creates/reuses `DomesticCraftRoute` in the same outer order transaction. It must call `flush`, never `commit`.

Call the service before product find-or-create. Update product key/display/name and list output to include `hair_style_series` and omit empty piece fields.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `cd backend && pytest tests/test_domestic_attributes.py -q`

Expected: all dictionary, validation, rollback, and route tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/domestic/attribute_service.py backend/app/domestic/router.py backend/app/domestic/order_service.py backend/app/domestic/product_service.py backend/tests/test_domestic_attributes.py
git commit -m "feat: support domestic special attribute options"
```

### Task 3: Guarded dictionary and route cutover

**Files:**
- Create: `backend/scripts/domestic_attribute_cutover.py`
- Create: `backend/tests/test_domestic_attribute_cutover.py`

- [ ] **Step 1: Write failing cutover tests**

Test that preflight reports exact Excel values, missing/disabled/empty routes block apply, apply replaces standard dictionaries and mappings, a second apply is idempotent, and existing products/order snapshots are unchanged.

```python
def test_apply_replaces_standard_options_without_touching_history(db, history, routes):
    plan = cutover.build_plan(db)
    cutover.apply_plan(db, plan)
    assert _codes(db, "domestic_cap_craft") == ["递旋", "中分界", "左分界", "大U型", "递顶"]
    assert history.product.route_id == history.original_route_id
    assert history.item.attrs_snapshot == history.original_attrs
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && pytest tests/test_domestic_attribute_cutover.py -q`

Expected: import failure because the cutover command does not exist.

- [ ] **Step 3: Implement preflight/apply**

Hard-code only the approved business data in the command: exact standard option lists, the two fixed route names, and obsolete domestic dictionary types. Preflight returns deterministic JSON. Apply requires an explicit `--apply` flag, revalidates inside the transaction, deletes/replaces only managed standard dictionary rows and standard craft mappings, and does not modify products or order items.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `cd backend && pytest tests/test_domestic_attribute_cutover.py -q`

Expected: all cutover tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/domestic_attribute_cutover.py backend/tests/test_domestic_attribute_cutover.py
git commit -m "feat: add domestic attribute cutover"
```

### Task 4: Frontend order-entry and list behavior

**Files:**
- Create: `frontend/src/views/domestic/domesticAttributeRules.js`
- Create: `frontend/tests/domesticOrderAttributes.test.mjs`
- Modify: `frontend/src/api/domestic.js`
- Modify: `frontend/src/views/domestic/DomesticOrderCreate.vue`
- Modify: `frontend/src/views/domestic/composables/useDomesticOrderCreate.js`
- Modify: `frontend/src/views/domestic/DomesticOrders.vue`
- Modify: `frontend/src/views/domestic/composables/useDomesticOrders.js`
- Modify: `frontend/src/views/domestic/DomesticProducts.vue`

- [ ] **Step 1: Write failing pure behavior tests**

```javascript
test('piece payload contains one combined craft-size and no inactive fields', () => {
  assert.deepEqual(normalizeAttrs({
    product_type: 'piece', craft: 'U型13*15', size: '13*15',
    length: '20厘米', density: '90%', net_color: '紫网全头套',
  }), {
    product_type: 'piece', craft: 'U型13*15', length: '20厘米',
    size: null, density: null, net_color: null, hair_style_series: null,
  })
})

test('switching special to normal clears only nonstandard values', () => {
  const attrs = { product_type: 'cap', craft: '自定义工艺', length: '20厘米' }
  assert.equal(clearSpecialValues(attrs, standardValues).craft, '')
  assert.equal(clearSpecialValues(attrs, standardValues).length, '20厘米')
})
```

Add source-contract assertions for `order_category`, `order_type`, `order_channel`, `allow-create`, the combined piece label, and density conditional rendering.

- [ ] **Step 2: Run tests and verify RED**

Run: `cd frontend && node --test tests/domesticOrderAttributes.test.mjs`

Expected: failure because helper exports and new source fields are absent.

- [ ] **Step 3: Implement pure rules and Vue wiring**

Pure helpers provide `attrOptions`, `normalizeAttrs`, `clearSpecialValues`, and `requiresDensity`. The composable owns all state and uses `order_category === 'special'` for `allow-create`. Add required category/type/channel controls and validation. Route preview falls back to the product-type default route returned by `/options` for a custom craft.

Add the three list filters/columns and query parameters. In products, label piece craft as “工艺/尺寸”, hide meaningless piece size/density, and show head hair-style series.

- [ ] **Step 4: Run tests and build**

Run: `cd frontend && node --test tests/domesticOrderAttributes.test.mjs`

Expected: all frontend feature tests pass.

Run: `cd frontend && npm run build`

Expected: Vite exits 0.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/domestic.js frontend/src/views/domestic frontend/tests/domesticOrderAttributes.test.mjs
git commit -m "feat: update domestic order entry attributes"
```

### Task 5: Read models, printing, and Excel export

**Files:**
- Modify: `backend/app/domestic/order_service.py`
- Modify: `backend/app/domestic/report_service.py`
- Modify: `backend/app/domestic/export_service.py`
- Modify: `frontend/src/views/domestic/print/printDocs.js`
- Modify: `backend/tests/test_domestic_export.py`
- Modify: `backend/tests/test_domestic_reporting.py`
- Modify: `backend/tests/test_domestic_optimizations.py`
- Modify: `backend/tests/test_domestic_wxacode.py`

- [ ] **Step 1: Update export/read tests first**

Assert list/detail/scan contracts return `order_category(_label)`, `order_type(_label)`, and `order_channel(_label)`. Update workbook expectations so the order header contains all three fields, “工艺/尺寸” replaces “工艺”, and “发型系列” has its own column.

- [ ] **Step 2: Run targeted tests and verify RED**

Run: `cd backend && pytest tests/test_domestic_export.py tests/test_domestic_reporting.py tests/test_domestic_optimizations.py -q`

Expected: contract and workbook assertions fail against old output.

- [ ] **Step 3: Implement consistent read/export/print output**

Resolve type/channel labels from `sys_dict` in batched queries, with “未填写” only for pre-clear historical rows. Rename every old normal/special response key to category. Update print special badge to `card.order_category === 'special'` and display type/channel rows.

- [ ] **Step 4: Run targeted tests and verify GREEN**

Run: `cd backend && pytest tests/test_domestic_export.py tests/test_domestic_reporting.py tests/test_domestic_optimizations.py -q`

Expected: all targeted domestic tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/domestic frontend/src/views/domestic/print backend/tests
git commit -m "feat: expose domestic order classifications"
```

### Task 6: Documentation and complete verification

**Files:**
- Modify: `docs/api-reference.md`
- Modify: `docs/database.md`
- Modify: `docs/auto-memory/project_domestic.md`

- [ ] **Step 1: Update authoritative docs**

Document the breaking `order_category` rename, new required type/channel fields and dictionary codes, options response, conditional product attributes, special-only creation transaction, migration 128, and cutover maintenance-window command. Explicitly state that historical deletion is not part of this change.

- [ ] **Step 2: Run convention checks**

Run: `python scripts/check_conventions.py`

Expected: no red items.

- [ ] **Step 3: Run all backend tests**

Run: `cd backend && pytest`

Expected: zero failures.

- [ ] **Step 4: Run frontend tests and build**

Run: `cd frontend && node --test tests/*.test.mjs`

Expected: zero failures.

Run: `cd frontend && npm run build`

Expected: Vite exits 0.

- [ ] **Step 5: Run migration checks and repository sweep**

Run: `cd backend && alembic heads`

Expected: one head, `129_domestic_order_attributes`.

Run: `python scripts/git_sweep.py`

Expected: command exits 0; unrelated repository debt is reported separately if present.

- [ ] **Step 6: Dispatch adversarial review and fix findings**

The independent reviewer must inspect boundary conditions, concurrent special-option creation, idempotent cutover, frontend/backend field consistency, migration safety, and every old `order_type=normal/special` call site. Re-run affected tests after every fix.

- [ ] **Step 7: Commit docs and review fixes**

```bash
git add docs backend frontend
git commit -m "docs: update domestic order attribute contract"
```
