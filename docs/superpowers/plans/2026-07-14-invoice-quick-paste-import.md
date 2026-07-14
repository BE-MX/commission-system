# Invoice Quick Paste Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe three-step Excel/WPS paste flow that batch-validates invoice lines and appends confirmed rows to the current invoice editor without saving or syncing.

**Architecture:** The frontend parses clipboard TSV into canonical rows and calls one side-effect-free backend preview endpoint. The backend normalizes values, builds in-memory indexes from batched product/SKU/price queries, returns row-level matches and warnings, and the existing invoice save path remains authoritative for totals and custom-product creation.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy 2.0, pytest, Vue 3 Composition API, Element Plus, Vite 5, Node built-in test runner.

---

## File Structure

- Create `backend/app/invoice/import_service.py`: normalization, batch product/SKU lookup, batch pricing, row statuses, fingerprint.
- Modify `backend/app/invoice/schemas.py`: preview request/response schemas.
- Modify `backend/app/invoice/router.py`: `POST /import/preview` with `invoice:write`.
- Modify `backend/app/invoice/service.py`: currency-safe price snapshots during final save.
- Create `backend/tests/test_invoice_paste_import.py`: import preview and currency regression tests.
- Create `frontend/src/views/invoice/composables/useInvoicePasteImport.js`: pure TSV parser plus import-session state.
- Create `frontend/src/views/invoice/components/InvoicePasteImport.vue`: three-step dialog.
- Modify `frontend/src/api/invoice.js`: preview API call.
- Modify `frontend/src/views/invoice/InvoiceManage.vue`: button, dialog, append callback.
- Modify `frontend/src/views/invoice/composables/useInvoiceEditor.js`: append normalized imported rows while preserving temporary batch fingerprints.
- Modify `frontend/src/views/invoice/invoice-manage.css`: import entry spacing only; component-specific styles stay with the component.
- Create `frontend/tests/invoicePasteImport.test.mjs`: parser, mapping, duplicate-session tests.
- Modify `frontend/package.json`: add `test:invoice-import` script.
- Modify `docs/api-reference.md`: document the preview endpoint.

### Task 1: Backend import normalization and deterministic product matching

**Files:**
- Create: `backend/app/invoice/import_service.py`
- Create: `backend/tests/test_invoice_paste_import.py`

- [ ] **Step 1: Write failing normalization tests**

Add tests covering canonical length, color, weight, positive quantity/price, and batch limit:

```python
def test_normalize_import_row_accepts_historical_formats():
    row = import_service.normalize_row({
        "source_row": 2,
        "product": "  Standard  Double Drawn Genius Weft ",
        "length": '18 inch',
        "color": " #1b ",
        "weight": "0.1kg",
        "quantity": 2,
        "unit_price": "36.00",
    })
    assert row["product"] == "Standard Double Drawn Genius Weft"
    assert row["length"] == "18"
    assert row["color"] == "#1B"
    assert row["weight"] == "100g"
    assert row["quantity"] == 2
    assert row["unit_price"] == Decimal("36.00")


@pytest.mark.parametrize("field,value", [
    ("quantity", 0), ("quantity", 1.5), ("unit_price", "0"), ("weight", "abc"),
])
def test_normalize_import_row_rejects_invalid_values(field, value):
    payload = valid_row()
    payload[field] = value
    with pytest.raises(ValueError):
        import_service.normalize_row(payload)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && pytest tests/test_invoice_paste_import.py -q`

Expected: collection fails because `app.invoice.import_service` does not exist.

- [ ] **Step 3: Implement minimal pure normalization helpers**

Create functions with these exact contracts:

```python
MAX_IMPORT_ROWS = 200

def normalize_row(raw: Mapping[str, object]) -> dict:
    """Return source_row/product/length/color/weight/quantity/unit_price."""

def normalize_rows(raw_rows: Sequence[Mapping[str, object]]) -> list[dict]:
    """Reject empty and >200 batches; preserve row order."""

def make_batch_fingerprint(rows: Sequence[Mapping[str, object]]) -> str:
    """SHA-256 over stable JSON of normalized source values, excluding customer context."""
```

Reuse `price_service.normalize_text`, `normalize_length`, and `normalize_color`; canonical weight must be `<integer>g`. Use `Decimal` for prices and reject booleans as quantities.

- [ ] **Step 4: Run normalization tests and verify GREEN**

Run: `cd backend && pytest tests/test_invoice_paste_import.py -q`

Expected: normalization tests pass.

- [ ] **Step 5: Write failing batch product-match tests**

Seed `lsordertest.okki_products` with unique, ambiguous, and no-SKU rows. Assert:

```python
result = import_service.preview_import(
    db,
    customer_id="CUST001",
    order_type="stock",
    currency="USD",
    raw_rows=[valid_row()],
)
assert result["rows"][0]["matched_product"]["product_id"] == 11
assert result["rows"][0]["matched_product"]["sku_id"] == 9011
assert result["rows"][0]["status"] == "passed"
```

Add separate assertions that ambiguous matches return candidates and `blocked`, stock no-match/no-SKU is blocked, and production no-match returns `can_create_custom=True` without writing `ark_custom_products`.

- [ ] **Step 6: Run match tests and verify RED**

Run: `cd backend && pytest tests/test_invoice_paste_import.py -q`

Expected: fails because `preview_import` is missing.

- [ ] **Step 7: Implement batched product and SKU indexes**

Implement these internal functions without calling `find_okki_by_attributes` inside the row loop:

```python
def _load_product_index(db: Session) -> dict[tuple[str, str, str, str], list[dict]]:
    """One product query keyed by normalized name-prefix/color/size/unit."""

def _load_sku_map(db: Session, product_ids: set[int]) -> dict[int, dict]:
    """One GROUP BY product_id query returning min sku_id and sku_count."""

def preview_import(db: Session, *, customer_id: str, order_type: str,
                   currency: str, raw_rows: list[dict]) -> dict:
    """Side-effect-free preview with summary, rows, and batch_fingerprint."""
```

For every row, retain all exact key hits. A unique product without SKU remains blocked for stock. Production no-match returns normalized data plus an explicit custom option, but does not create a custom product.

- [ ] **Step 8: Run match tests and verify GREEN**

Run: `cd backend && pytest tests/test_invoice_paste_import.py -q`

Expected: product-match tests pass.

- [ ] **Step 9: Commit backend matching slice**

```bash
git add backend/app/invoice/import_service.py backend/tests/test_invoice_paste_import.py
git commit -m "feat: add invoice import matching preview"
```

### Task 2: Batch pricing and currency-safe save behavior

**Files:**
- Modify: `backend/app/invoice/import_service.py`
- Modify: `backend/app/invoice/service.py`
- Modify: `backend/tests/test_invoice_paste_import.py`

- [ ] **Step 1: Write failing preview pricing tests**

Test same-price, manual-price, missing-price, and cross-currency behavior:

```python
assert same["price_source"] == "customer_rule"
assert same["price_difference"] == Decimal("0.00")
assert changed["price_source"] == "manual"
assert changed["unit_price"] == Decimal("36.00")
assert cross_currency["customer_price"] is None
assert cross_currency["price_difference"] is None
assert "无法直接比较" in cross_currency["warnings"][0]
```

- [ ] **Step 2: Run pricing tests and verify RED**

Run: `cd backend && pytest tests/test_invoice_paste_import.py -q`

Expected: row results do not yet contain authoritative pricing fields.

- [ ] **Step 3: Implement fixed-query batch pricing**

Add a batch loader that reads the customer rule once and loads all relevant standard-price/color rows once. Resolve each normalized row in memory. Only expose customer/standard price and numeric difference when the standard price currency equals the invoice currency.

```python
def _load_pricing_context(db: Session, *, customer_id: str, rows: list[dict]) -> dict:
    """Return one customer rule and maps for color types and standard prices."""

def _apply_pricing(row: dict, context: dict, invoice_currency: str) -> dict:
    """Preserve pasted unit_price; add same-currency snapshots and warnings."""
```

- [ ] **Step 4: Run preview pricing tests and verify GREEN**

Run: `cd backend && pytest tests/test_invoice_paste_import.py -q`

Expected: pricing tests pass.

- [ ] **Step 5: Write failing final-save currency regression test**

Create an EUR invoice while the resolved standard price is USD, then assert the saved item preserves the pasted amount and does not store a cross-currency comparable snapshot:

```python
invoice = service.create_invoice(db, eur_payload, user_id=1)
item = invoice.items[0]
assert item.price_per_piece == Decimal("36.00")
assert item.standard_price is None
assert item.customer_price is None
assert item.price_source == "missing_std"
```

- [ ] **Step 6: Run save test and verify RED**

Run: `cd backend && pytest tests/test_invoice_paste_import.py::test_save_does_not_compare_cross_currency_price -q`

Expected: current save stores the USD snapshot or classifies the price incorrectly.

- [ ] **Step 7: Implement minimal currency guard in final save**

In `_replace_items`, compare `pricing["currency"]` with `body.currency` before assigning snapshots. On mismatch, set `standard_price` and `customer_price` to `None`, preserve `price_per_piece`, and use `missing_std`.

- [ ] **Step 8: Run targeted and existing invoice pricing tests**

Run: `cd backend && pytest tests/test_invoice_paste_import.py tests/test_invoice_pricing.py tests/test_invoice_amounts.py -q`

Expected: all selected tests pass.

- [ ] **Step 9: Commit pricing slice**

```bash
git add backend/app/invoice/import_service.py backend/app/invoice/service.py backend/tests/test_invoice_paste_import.py
git commit -m "fix: keep invoice import pricing currency safe"
```

### Task 3: Preview schemas, endpoint, permission, and API documentation

**Files:**
- Modify: `backend/app/invoice/schemas.py`
- Modify: `backend/app/invoice/router.py`
- Modify: `backend/tests/test_invoice_paste_import.py`
- Modify: `docs/api-reference.md`

- [ ] **Step 1: Write failing schema and endpoint tests**

Assert Pydantic rejects over 200 rows and invalid order type, and the endpoint calls the service under `invoice:write` and returns the unified envelope. Use the existing test client/auth fixtures rather than bypassing dependencies.

- [ ] **Step 2: Run endpoint tests and verify RED**

Run: `cd backend && pytest tests/test_invoice_paste_import.py -q`

Expected: request schema and route are missing.

- [ ] **Step 3: Add exact Pydantic models**

```python
class InvoiceImportRow(BaseModel):
    source_row: int = Field(..., ge=1)
    product: str = Field(..., min_length=1, max_length=256)
    length: str = Field(..., min_length=1, max_length=128)
    color: str = Field(..., min_length=1, max_length=128)
    weight: str = Field(..., min_length=1, max_length=64)
    quantity: int = Field(..., gt=0)
    unit_price: Decimal = Field(..., gt=0)

class InvoiceImportPreviewRequest(BaseModel):
    customer_id: str = Field(..., min_length=1, max_length=64)
    order_type: str = Field(..., pattern="^(stock|production)$")
    currency: str = Field(..., min_length=1, max_length=16)
    rows: list[InvoiceImportRow] = Field(..., min_length=1, max_length=200)
```

- [ ] **Step 4: Add the side-effect-free route**

```python
@router.post("/import/preview", summary="Preview pasted invoice lines")
def preview_invoice_import(
    body: InvoiceImportPreviewRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("invoice:write")),
):
    return ok(import_service.preview_import(
        db,
        customer_id=body.customer_id,
        order_type=body.order_type,
        currency=body.currency,
        raw_rows=[row.model_dump() for row in body.rows],
    ))
```

- [ ] **Step 5: Run endpoint tests and verify GREEN**

Run: `cd backend && pytest tests/test_invoice_paste_import.py -q`

Expected: all import backend tests pass.

- [ ] **Step 6: Document request, response, permission, and no-write semantics**

Add `POST /api/invoice/import/preview` to `docs/api-reference.md`, including row statuses `passed/warning/blocked` and the cross-currency rule.

- [ ] **Step 7: Commit API slice**

```bash
git add backend/app/invoice/schemas.py backend/app/invoice/router.py backend/tests/test_invoice_paste_import.py docs/api-reference.md
git commit -m "feat: expose invoice import preview API"
```

### Task 4: Clipboard parser and import-session state

**Files:**
- Create: `frontend/src/views/invoice/composables/useInvoicePasteImport.js`
- Create: `frontend/tests/invoicePasteImport.test.mjs`
- Modify: `frontend/package.json`

- [ ] **Step 1: Write failing TSV parser tests**

Use `node:test` to assert English, Chinese, historical and headerless inputs:

```javascript
const parsed = parseInvoiceClipboard(`Product_name\tProduct\tNet Weight Grams\tLength\tColor\tQuantity\tPrice/Piece
组合名称\tStandard Double Drawn Genius Weft\t100g\t18\t#1B\t2\t36.00`)
assert.equal(parsed.rows[0].product, 'Standard Double Drawn Genius Weft')
assert.equal(parsed.rows[0].weight, '100g')
assert.equal(parsed.rows[0].unit_price, '36.00')
assert.deepEqual(parsed.ignoredHeaders, ['Product_name'])
```

Also test fixed six-column input without a header, empty lines, ignored extra columns, missing required headers, inconsistent column counts, and the 200-row limit.

- [ ] **Step 2: Add test script and verify RED**

Add `"test:invoice-import": "node --test tests/invoicePasteImport.test.mjs"`.

Run: `cd frontend && npm run test:invoice-import`

Expected: import fails because the composable does not exist.

- [ ] **Step 3: Implement pure parser exports**

```javascript
export const STANDARD_FIELDS = ['product', 'length', 'color', 'weight', 'quantity', 'unit_price']
const HEADER_ALIASES = new Map([
  ['product', ['product', 0]], ['产品名称product', ['product', 1]],
  ['product_name', ['product', 2]], ['产品名称', ['product', 3]], ['产品', ['product', 3]],
  ['length', ['length', 0]], ['长度', ['length', 1]],
  ['color', ['color', 0]], ['colour', ['color', 0]], ['颜色', ['color', 1]], ['色号', ['color', 1]],
  ['weight', ['weight', 0]], ['netweightgrams', ['weight', 0]], ['重量', ['weight', 1]], ['克重', ['weight', 1]],
  ['quantity', ['quantity', 0]], ['qty', ['quantity', 0]], ['数量', ['quantity', 1]],
  ['unitprice', ['unit_price', 0]], ['price/piece', ['unit_price', 0]], ['price', ['unit_price', 1]],
  ['单价', ['unit_price', 1]], ['成交价', ['unit_price', 1]],
])

function normalizeHeader(value) {
  return String(value || '').trim().toLowerCase().replace(/\s+/g, '')
}

function resolveHeaderMapping(headers) {
  const chosen = new Map()
  const ignoredHeaders = []
  headers.forEach((header, index) => {
    const alias = HEADER_ALIASES.get(normalizeHeader(header))
    if (!alias) return
    const [field, priority] = alias
    const previous = chosen.get(field)
    if (!previous || priority < previous.priority) {
      if (previous) ignoredHeaders.push(headers[previous.index])
      chosen.set(field, { index, priority })
    } else {
      ignoredHeaders.push(header)
    }
  })
  const hasHeader = chosen.size > 0
  const fields = hasHeader
    ? Object.fromEntries([...chosen].map(([field, value]) => [field, value.index]))
    : Object.fromEntries(STANDARD_FIELDS.map((field, index) => [field, index]))
  if (hasHeader) {
    const missing = STANDARD_FIELDS.filter(field => fields[field] == null)
    if (missing.length) throw new Error(`缺少必填列：${missing.join(', ')}`)
  }
  return { hasHeader, fields, ignoredHeaders, warnings: ignoredHeaders.length ? ['已忽略重复映射列'] : [] }
}

function mapCells(cells, mapping, sourceRow) {
  return Object.fromEntries([
    ['source_row', sourceRow],
    ...STANDARD_FIELDS.map(field => [field, String(cells[mapping.fields[field]] ?? '').trim()]),
  ])
}

export function parseInvoiceClipboard(text) {
  const matrix = text.split(/\r?\n/).filter(line => line.trim()).map(line => line.split('\t'))
  if (!matrix.length) throw new Error('请先粘贴 Excel 明细')
  const mapping = resolveHeaderMapping(matrix[0])
  const dataRows = mapping.hasHeader ? matrix.slice(1) : matrix
  if (!mapping.hasHeader && matrix[0].length !== STANDARD_FIELDS.length) {
    throw new Error('无法识别列结构，请复制包含表头的数据')
  }
  if (dataRows.length > 200) throw new Error('单次最多导入 200 行')
  return {
    rows: dataRows.map((cells, index) => mapCells(cells, mapping, index + (mapping.hasHeader ? 2 : 1))),
    mapping: mapping.fields,
    ignoredHeaders: mapping.ignoredHeaders,
    warnings: mapping.warnings,
  }
}

export function mapPreviewRowToInvoiceLine(row, batchFingerprint, orderType) {
  const matched = row.matched_product || {}
  return {
    item_type: matched.product_id ? 'stock' : (orderType === 'production' ? 'custom' : 'stock'),
    product_id: matched.product_id || null,
    sku_id: matched.sku_id || null,
    product_name: matched.product_name || '',
    product_display: row.normalized.product,
    net_weight_grams: row.normalized.weight,
    color: row.normalized.color,
    length: row.normalized.length,
    quantity: row.normalized.quantity,
    price_per_piece: Number(row.normalized.unit_price),
    price_source: row.price_source,
    _importBatchFingerprint: batchFingerprint,
  }
}

export function hasImportedBatch(items, fingerprint) {
  return items.some(item => item._importBatchFingerprint === fingerprint)
}
```

Parse `text/plain` TSV without requesting clipboard permission. Prefer exact `Product` over bilingual product, `Product_name`, and Chinese product headers. Keep source row numbers.

- [ ] **Step 4: Run parser tests and verify GREEN**

Run: `cd frontend && npm run test:invoice-import`

Expected: all parser tests pass.

- [ ] **Step 5: Write failing mapping and duplicate tests**

Assert matched stock lines receive product/SKU, price differences preserve pasted price with `manual`, production custom choice maps to `item_type=custom`, and a fingerprint is blocked only while at least one line carrying it remains.

- [ ] **Step 6: Run tests and verify RED**

Run: `cd frontend && npm run test:invoice-import`

Expected: mapping/session behavior is missing.

- [ ] **Step 7: Implement minimal mapping and session helpers**

Keep `_importBatchFingerprint` out of `buildPayload`; attach it only to editor rows. Do not introduce persistence or a global store.

- [ ] **Step 8: Run tests and verify GREEN**

Run: `cd frontend && npm run test:invoice-import`

Expected: parser and session tests pass.

- [ ] **Step 9: Commit parser slice**

```bash
git add frontend/src/views/invoice/composables/useInvoicePasteImport.js frontend/tests/invoicePasteImport.test.mjs frontend/package.json
git commit -m "feat: parse pasted invoice rows"
```

### Task 5: Three-step import UI and editor integration

**Files:**
- Create: `frontend/src/views/invoice/components/InvoicePasteImport.vue`
- Modify: `frontend/src/api/invoice.js`
- Modify: `frontend/src/views/invoice/InvoiceManage.vue`
- Modify: `frontend/src/views/invoice/composables/useInvoiceEditor.js`
- Modify: `frontend/src/views/invoice/invoice-manage.css`
- Modify: `frontend/tests/invoicePasteImport.test.mjs`

- [ ] **Step 1: Write failing source-contract tests**

Add checks that the editor exposes a visible-but-disabled paste button when context is incomplete, imports the component, calls `previewInvoiceImport`, and the component contains paste/preview/append states with a disabled append action while blocked rows remain.

- [ ] **Step 2: Run frontend tests and verify RED**

Run: `cd frontend && npm run test:invoice-import`

Expected: component and integration contracts are absent.

- [ ] **Step 3: Add API client method**

```javascript
export function previewInvoiceImport(data) {
  return unwrap(request.post('/import/preview', data, {
    loadingText: '正在校验导入明细...',
  }))
}
```

- [ ] **Step 4: Implement the component**

`InvoicePasteImport.vue` receives `customerId`, `orderType`, `currency`, and `existingItems`; emits `append` and `close`. It must:

- preserve pasted text after network failure;
- show context at the top;
- render summary counts and every row;
- provide a candidate select for ambiguous rows;
- provide an explicit “作为定制产品” action only for production rows;
- show Excel price, same-currency customer price, and difference;
- keep the append button disabled while any row is blocked;
- have no decorative entry animation; only existing Element Plus dialog motion and button press feedback apply.

- [ ] **Step 5: Integrate with the existing editor**

Add `appendImportedLines(previewRows, fingerprint)` to `useInvoiceEditor.js`, implemented via `normalizeLine`. Add “从 Excel 粘贴” beside “添加明细”. Disable it with an explanatory tooltip until customer/order type/currency exist. On append, check `hasImportedBatch(form.items, fingerprint)`, append lines, close the dialog, and show one success message.

- [ ] **Step 6: Keep payload clean and reset lifecycle correct**

Verify `buildPayload()` enumerates persisted fields and therefore excludes `_importBatchFingerprint`. `resetForm`, closing, new create, and edit replacement naturally discard temporary marks. If the import dialog is open and context changes, close it and discard its preview.

- [ ] **Step 7: Run frontend tests and verify GREEN**

Run: `cd frontend && npm run test:invoice-import && npm run test:invoice-layout`

Expected: both suites pass.

- [ ] **Step 8: Build frontend**

Run: `cd frontend && npm run build`

Expected: Vite exits 0 with no unresolved imports or Vue template errors.

- [ ] **Step 9: Commit UI slice**

```bash
git add frontend/src/api/invoice.js frontend/src/views/invoice/components/InvoicePasteImport.vue frontend/src/views/invoice/composables/useInvoiceEditor.js frontend/src/views/invoice/InvoiceManage.vue frontend/src/views/invoice/invoice-manage.css frontend/tests/invoicePasteImport.test.mjs
git commit -m "feat: add invoice paste import workflow"
```

### Task 6: End-to-end verification and adversarial review

**Files:**
- Modify only files required by verified findings.

- [ ] **Step 1: Run the complete backend suite**

Run: `cd backend && pytest`

Expected: 0 failures.

- [ ] **Step 2: Run frontend import/layout tests and production build**

Run: `cd frontend && npm run test:invoice-import && npm run test:invoice-layout && npm run build`

Expected: all tests pass and Vite exits 0.

- [ ] **Step 3: Run project convention checks**

Run: `python scripts/check_conventions.py`

Expected: no red items in the incremental diff.

- [ ] **Step 4: Verify real clipboard samples**

Copy the six-row standard workbook and the product table from the historical invoice template into the running page. Confirm unique matches, one ambiguous candidate flow, one price difference, duplicate batch blocking, and no save/sync during preview.

- [ ] **Step 5: Run independent invoice review**

Review the final diff for price authority, currency behavior, product/SKU ambiguity, N+1 queries, no-write preview semantics, duplicate lifecycle, and frontend/backend contract. Fix every blocking finding with a new failing test first.

- [ ] **Step 6: Run fresh verification after review fixes**

Repeat Steps 1-3. Do not report completion from an earlier run.

- [ ] **Step 7: Commit review fixes if any**

```bash
git add backend/app/invoice/import_service.py backend/app/invoice/service.py backend/tests/test_invoice_paste_import.py frontend/src/views/invoice/components/InvoicePasteImport.vue frontend/src/views/invoice/composables/useInvoicePasteImport.js frontend/tests/invoicePasteImport.test.mjs
git commit -m "fix: harden invoice paste import"
```
