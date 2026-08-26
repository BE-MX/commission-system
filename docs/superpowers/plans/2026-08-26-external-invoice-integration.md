# External Invoice Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Phase 1 REST invoice ingestion with per-site credentials, deterministic customer/product resolution, server-side monetary validation, idempotent creation and result lookup, then deliver Phase 2 OpenAPI/client integration assets for Codex-built sites.

**Architecture:** A new `app.integration` domain owns machine credentials, external request schemas, resolution and idempotency orchestration. It converts validated submissions into the existing `InvoiceCreate` service contract so invoice pricing, totals, delegation and OKKI state remain single-sourced; ordinary invoice routes cannot forge `external_api` provenance. The frontend only manages Integration Apps, while site runtimes call versioned REST endpoints from server-side code.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy 2, Alembic/MySQL, pytest, Vue 3, Element Plus, native Node tests, OpenAPI 3, TypeScript `fetch`.

---

## File map

- Create `backend/alembic/versions/125_invoice_integration.py`: Integration App/request tables and external invoice source schema.
- Create `backend/app/integration/models.py`: `IntegrationApp`, `InvoiceIngestRequest`.
- Create `backend/app/integration/schemas.py`: strict admin, resolver and invoice submission contracts.
- Create `backend/app/integration/auth.py`: opaque token authentication and `SubmissionPrincipal`.
- Create `backend/app/integration/service.py`: credentials, canonical resolution, validation, hashing and idempotent creation.
- Create `backend/app/integration/router.py`: `/admin/*` and `/v1/*` REST endpoints.
- Modify `backend/app/invoice/schemas.py`, `backend/app/invoice/service.py`: explicitly permit guarded `external_api` provenance.
- Modify `backend/app/auth/service.py`, `backend/app/routers.py`: seed `integration:admin` and register routes.
- Create `backend/tests/test_integration_models.py`, `test_integration_admin.py`, `test_integration_api.py`: migration/model, auth/admin and transactional API behavior.
- Modify `frontend/src/api/clients.js`, create `frontend/src/api/integrationApps.js`: authenticated admin client.
- Create `frontend/src/views/system/IntegrationAppManagement.vue` and `integrationAppManagement.js`: site credential management.
- Modify `frontend/src/config/navigation.js`, create `frontend/tests/integrationAppManagement.test.mjs`: menu and UI logic.
- Create `docs/requirements/2026-08-26-external-invoice-integration.md`: authoritative product/contract design.
- Create `docs/integrations/invoice-api.md`: user-facing server-side integration guide.
- Create `docs/integrations/ark-invoice-client.ts`: copyable TypeScript helper with stable retry/query behavior.
- Create `docs/integrations/codex-site-prompt.md`: copyable Codex site modification prompt.
- Modify `docs/api-reference.md`, `docs/database.md`, `docs/module-notes.md`: endpoint, schema and operational truth.

## Task 1: Persist Integration Apps and request identity

**Files:**
- Create: `backend/tests/test_integration_models.py`
- Create: `backend/alembic/versions/125_invoice_integration.py`
- Create: `backend/app/integration/__init__.py`
- Create: `backend/app/integration/models.py`

- [ ] **Step 1: Write failing model and migration tests**

```python
def test_integration_models_enforce_app_scoped_external_order_identity(db):
    app = IntegrationApp(public_id="app_a", name="Site A", owner_user_id=1,
                         token_hash="a" * 64, token_suffix="123456")
    db.add(app); db.flush()
    db.add(InvoiceIngestRequest(public_id="req_a", integration_app_id=app.id,
        external_order_id="GW-1", request_sha256="b" * 64, status="rejected"))
    db.flush()
    db.add(InvoiceIngestRequest(public_id="req_b", integration_app_id=app.id,
        external_order_id="GW-1", request_sha256="c" * 64, status="rejected"))
    with pytest.raises(IntegrityError):
        db.flush()
```

Also assert the migration is chained from `124_ai_chat_modes`, table/constraint names exist, revision length is within 32 characters, and every business timestamp uses `beijing_now`/database `CURRENT_TIMESTAMP` under the platform timezone policy.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_integration_models.py -q`

Expected: collection/import failure because `app.integration` and migration 125 do not exist.

- [ ] **Step 3: Implement minimal models and migration**

```python
class IntegrationApp(Base):
    __tablename__ = "ark_integration_apps"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    public_id = Column(String(32), nullable=False, unique=True)
    name = Column(String(100), nullable=False)
    owner_user_id = Column(USER_ID, ForeignKey("ark_users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(CHAR(64), nullable=False, unique=True)
    token_suffix = Column(String(6), nullable=False)
    scopes = Column(JSON, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    expires_at = Column(DateTime)
    last_used_at = Column(DateTime)
    created_by = Column(USER_ID, ForeignKey("ark_users.id", ondelete="SET NULL"))
    created_at = Column(DateTime, nullable=False, default=beijing_now)
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now)

class InvoiceIngestRequest(Base):
    __tablename__ = "ark_invoice_ingest_requests"
    # public_id is copied into ark_invoices.source_order_id.
    __table_args__ = (UniqueConstraint("integration_app_id", "external_order_id",
                                       name="uq_invoice_ingest_app_order"),)
```

Use `status in processing|created|rejected`, `attempt_count`, `request_sha256`, nullable `invoice_id`, error code/json and Beijing timestamps. Expand invoice `source_type` documentation/data allowance to `external_api`, but preserve existing screenshot uniqueness.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest tests/test_integration_models.py -q`

Expected: all model/migration tests pass.

- [ ] **Step 5: Stage and commit immediately**

```powershell
git add backend/alembic/versions/125_invoice_integration.py backend/app/integration backend/tests/test_integration_models.py
git commit -m "feat: add invoice integration persistence"
```

## Task 2: Integration App administration and token authentication

**Files:**
- Create: `backend/tests/test_integration_admin.py`
- Create: `backend/app/integration/auth.py`
- Create: `backend/app/integration/schemas.py`
- Create: `backend/app/integration/service.py`
- Create: `backend/app/integration/router.py`
- Modify: `backend/app/auth/service.py`
- Modify: `backend/app/routers.py`

- [ ] **Step 1: Write failing credential tests**

Cover five named cases: issuing returns one `ark_live_` secret while the ORM row stores only a 64-character hash; rotating changes the hash and makes the old token return 401; disabled App/disabled user/revoked `invoice:write` each return 401 or 403 without updating `last_used_at`; an App token sent to `/api/invoice/invoices` is rejected; and every admin endpoint returns 403 without `integration:admin`.

The desired dependency contract is:

```python
@dataclass(frozen=True)
class SubmissionPrincipal:
    actor_user_id: int
    sales_user_id: int
    idempotency_namespace: str
    scopes: frozenset[str]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_integration_admin.py -q`

Expected: missing admin router/auth service.

- [ ] **Step 3: Implement minimal credential service and routes**

Routes:

```text
GET    /api/integrations/admin/user-candidates
GET    /api/integrations/admin/apps
POST   /api/integrations/admin/apps
POST   /api/integrations/admin/apps/{id}/rotate
DELETE /api/integrations/admin/apps/{id}
```

Issue `ark_live_<urlsafe secret>`, persist only `hash_token(secret)`, return plaintext once, bind one active Ark user, and intersect fixed App scopes with the user's current `invoice:write`. Seed `integration:admin` and protect every admin route with `require_permission("integration:admin")`.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest tests/test_integration_admin.py -q`

Expected: all credential and permission tests pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/integration backend/app/auth/service.py backend/app/routers.py backend/tests/test_integration_admin.py
git commit -m "feat: manage site integration credentials"
```

## Task 3: Strict contract, customer/product resolution and validation

**Files:**
- Create/modify: `backend/tests/test_integration_api.py`
- Modify: `backend/app/integration/schemas.py`
- Modify: `backend/app/integration/service.py`
- Modify: `backend/app/integration/router.py`

- [ ] **Step 1: Write failing resolver/validation tests**

Cover strict `extra="forbid"`, ISO currency/date, max 200 rows, positive quantities/prices, negative-or-zero discounts, exact customer ID/email/phone/name rules, product ID+SKU validation, four-dimensional unique matching, multi-SKU ambiguity, canonical catalog text overwrite, optional declared-total reconciliation and no database writes from validation.

The sample test posts the seven de-identified lines from the workbook and asserts `product_amount == "1064.80"`, `total_amount == "1173.69"`, zero invoice rows and zero ingest rows. Ambiguity tests assert HTTP 422 with stable `CUSTOMER_NOT_UNIQUE` or `PRODUCT_NOT_UNIQUE` issue codes and exact `items[n]` field paths. The canonical snapshot test submits a valid ID pair with forged text and asserts the response contains the catalog text. The unknown-field test adds `sales_user_id` and asserts Pydantic rejects it instead of silently ignoring it.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_integration_api.py -k "resolve or validate or sample" -q`

Expected: public endpoints/service functions missing.

- [ ] **Step 3: Implement resolver and validation contract**

```python
class InvoiceSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    schema_version: Literal["1.0"]
    external_order_id: str = Field(min_length=1, max_length=64,
                                   pattern=r"^[A-Za-z0-9._:-]+$")
    order_type: Literal["stock", "production"]
    invoice_date: date
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    customer: CustomerSubmission
    delivery: DeliverySubmission
    fees: FeeSubmission = Field(default_factory=FeeSubmission)
    declared_totals: DeclaredTotals | None = None
    items: list[InvoiceLineSubmission] = Field(min_length=1, max_length=200)
```

Resolve stock items to canonical OKKI snapshots, preserve submitted `unit_price` as the成交价, reuse current standard/customer-price snapshot logic, and return stable issue codes plus warnings. `/invoices/validate` never creates an ingest row or invoice.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest tests/test_integration_api.py -k "resolve or validate or sample" -q`

Expected: all resolver/validation tests pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/integration backend/tests/test_integration_api.py
git commit -m "feat: validate external invoice submissions"
```

## Task 4: Idempotent creation, provenance and result recovery

**Files:**
- Modify: `backend/tests/test_integration_api.py`
- Modify: `backend/app/integration/service.py`
- Modify: `backend/app/integration/router.py`
- Modify: `backend/app/invoice/schemas.py`
- Modify: `backend/app/invoice/service.py`

- [ ] **Step 1: Write failing creation/concurrency tests**

Write seven tests with these exact outcomes: creation yields one invoice and one `created` ingest row with no OKKI call; identical replay returns HTTP 200 with `replayed=true`; changed content after creation returns HTTP 409 and preserves the original row; a `rejected` row accepts corrected content and increments `attempt_count`; two sessions racing the same order end with one invoice; GET lookup returns the created result after the response is discarded; and the ordinary JWT invoice route rejects `external_api` provenance.

Assert `source_type=external_api`, `source_order_id=request.public_id`, `sync_status=not_synced`, and no `xiaoman_service` call.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_integration_api.py -k "create or replay or concurrent or lookup" -q`

Expected: creation/query behavior missing.

- [ ] **Step 3: Implement one-transaction idempotency**

Canonicalize Pydantic JSON, hash with SHA-256, lock/reuse `(app_id, external_order_id)`, allow `rejected` attempts to replace digest, freeze `created` rows, and recover unique races by rollback then reread. Call:

```python
invoice_service.create_invoice(
    db,
    internal_payload,
    user_id=principal.actor_user_id,
    allow_external_source=True,
)
```

Ordinary invoice creation must reject `source_type=external_api`; only the integration service may pass the guard.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest tests/test_integration_api.py -q`

Expected: all integration API tests pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/integration backend/app/invoice backend/tests/test_integration_api.py
git commit -m "feat: create invoices idempotently from sites"
```

## Task 5: Admin UX and navigation

**Files:**
- Create: `frontend/tests/integrationAppManagement.test.mjs`
- Modify: `frontend/src/api/clients.js`
- Create: `frontend/src/api/integrationApps.js`
- Create: `frontend/src/views/system/integrationAppManagement.js`
- Create: `frontend/src/views/system/IntegrationAppManagement.vue`
- Modify: `frontend/src/config/navigation.js`

- [ ] **Step 1: Write failing frontend tests**

Test endpoint/config constants, filtering, token copy config, one-time secret state, status labels, `/system/integration-apps` navigation and `integration:admin` permission.

```javascript
test('builds a server-only environment snippet without exposing browser usage', () => {
  assert.match(buildServerEnvSnippet('ark_live_secret'), /ARK_INVOICE_API_TOKEN=/)
  assert.doesNotMatch(buildServerEnvSnippet('ark_live_secret'), /localStorage/)
})
```

- [ ] **Step 2: Run tests and verify RED**

Run: `node --test tests/integrationAppManagement.test.mjs`

Expected: module/navigation missing.

- [ ] **Step 3: Implement the management page**

Follow `McpTokenManagement.vue` interaction patterns but label the endpoint `https://leshine.work/api/integrations/v1`, explain “服务端调用，禁止放浏览器”, and support create, rotate, revoke, filter and one-time copy. Use `integrationClient = createApiClient({ baseURL: '/api/integrations/admin' })` and design tokens only.

- [ ] **Step 4: Run tests and build**

Run:

```powershell
node --test tests/integrationAppManagement.test.mjs tests/navigationLayout.test.mjs
npm run build
```

Expected: tests and Vite production build pass.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src frontend/tests/integrationAppManagement.test.mjs
git commit -m "feat: manage site invoice credentials"
```

## Task 6: Phase 2 contract and Codex integration kit

**Files:**
- Create: `docs/requirements/2026-08-26-external-invoice-integration.md`
- Create: `docs/integrations/invoice-api.md`
- Create: `docs/integrations/ark-invoice-client.ts`
- Create: `docs/integrations/codex-site-prompt.md`
- Create: `frontend/tests/integrationDocs.test.mjs`

- [ ] **Step 1: Write failing contract-asset test**

Test that every documented endpoint exists in FastAPI OpenAPI, the TypeScript helper uses the same external ID on retry, queries result after transport ambiguity, exports `validateInvoice`/`createInvoice`/`getInvoiceByExternalId`, never references browser storage, and the Codex prompt requires a server-side environment secret.

- [ ] **Step 2: Run and verify RED**

Run: `node --test tests/integrationDocs.test.mjs`

Expected: files/exports absent.

- [ ] **Step 3: Write the concrete Phase 2 assets**

The TypeScript public surface is:

```ts
export class ArkInvoiceClient {
  validateInvoice(payload: InvoiceSubmission): Promise<ValidationResult>;
  createInvoice(payload: InvoiceSubmission): Promise<CreateResult>;
  getInvoiceByExternalId(externalOrderId: string): Promise<CreateResult>;
}
```

Use `AbortController`, preserve the same `external_order_id`, query after timeout/network ambiguity, and never auto-generate a replacement business key. The Codex prompt must tell each site to map its order state to the JSON contract at invoice generation time and keep Excel as a human download only.

- [ ] **Step 4: Run and verify GREEN**

Run: `node --test tests/integrationDocs.test.mjs`

Expected: all contract assets pass.

- [ ] **Step 5: Commit**

```powershell
git add docs/requirements docs/integrations frontend/tests/integrationDocs.test.mjs
git commit -m "docs: publish invoice site integration kit"
```

## Task 7: Repository documentation and full verification

**Files:**
- Modify: `docs/api-reference.md`
- Modify: `docs/database.md`
- Modify: `docs/module-notes.md`
- Modify: `docs/handoff.md`

- [ ] **Step 1: Document deployed contract and operational rules**

Record exact endpoints, table fields/constraints, source provenance, credential lifecycle, stable error codes, no-OKKI-sync invariant, server-only secret rule, timeout recovery and the real management menu path.

- [ ] **Step 2: Run focused and full verification**

```powershell
cd backend
python -m pytest tests/test_integration_models.py tests/test_integration_admin.py tests/test_integration_api.py -q
python -m pytest
cd ..
python scripts/check_conventions.py --base (git merge-base main HEAD)
cd frontend
node --test tests/integrationAppManagement.test.mjs tests/integrationDocs.test.mjs tests/navigationLayout.test.mjs
npm run build
```

- [ ] **Step 3: Apply migration and verify schema**

Stop any conflicting writer only if the migration requires it, then run `backend/.venv/Scripts/python.exe -m alembic upgrade head` from `backend`. Verify one Alembic head, both new tables, unique constraints/FKs and `source_type=external_api` creation in a rollback-safe pilot transaction.

- [ ] **Step 4: Independent adversarial review**

Dispatch a read-only reviewer covering boundary values, concurrent writes, rejected-to-corrected retries, digest stability, token rotation/revocation, customer/product data scope, transaction rollback, external provenance, every caller of modified invoice functions, REST/frontend/docs contract and accidental OKKI sync. Fix every confirmed issue and rerun affected plus full verification.

- [ ] **Step 5: Commit and push feature backup**

```powershell
git add docs/api-reference.md docs/database.md docs/module-notes.md docs/handoff.md
git commit -m "docs: document invoice integration operations"
git push
```

## Task 8: Deploy and live-verify Phase 1/2

- [ ] **Step 1: Deploy through the repository command**

From the main deployment checkout, use `deploy\deploy.bat`; do not manually run uvicorn or copy individual static files.

- [ ] **Step 2: Issue one pilot Integration App in the real admin page**

Bind it to a test-capable Ark user with `invoice:write`. Store the plaintext only in a temporary process environment for the verification session, never in files or logs.

- [ ] **Step 3: Live verification**

Call resolver and validation with de-identified data, then create one explicitly marked pilot invoice. Verify the Ark invoice page shows canonical customer/product snapshots, server-computed totals, `source_type=external_api`, `sync_status=not_synced`, repeated create returns the same invoice, changed content returns 409, and result lookup works.

- [ ] **Step 4: Cleanup pilot business data**

Delete the unsynced pilot invoice through the normal Ark UI/API and revoke the pilot App. Confirm no OKKI order or sync log was created.

- [ ] **Step 5: Completion audit**

Map every Phase 1/2 requirement to current code, tests, OpenAPI, UI, docs, migration state and live evidence. Do not claim completion while deployment, one-time-token flow, idempotent replay, no-OKKI-sync or cleanup lacks direct evidence.
