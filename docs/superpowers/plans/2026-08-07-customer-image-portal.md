# Customer Image Portal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a customer-facing product image portal where salespeople issue revocable product-scoped invitation links and customers upload one reusable logo, choose product presets, submit optional requirements, generate recoverable AI images, and revisit results during the invitation lifetime.

**Architecture:** Add an isolated `customer_image` domain for products, invitations, assets, quota, and customer generation records. Extract only provider invocation, image response decoding, usage/cost parsing, and error classification from the existing design-image worker into `app.ai.image_job_runtime`; each domain keeps its own ownership, lease, and persistence logic. The customer SPA route uses an invitation-only API client backed by `sessionStorage`, while internal administration remains under normal RBAC.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, APScheduler, MySQL/SQLite tests, Vue 3, Vue Router, Element Plus, Axios, Vite 5, Node test runner.

---

## Preconditions And Locked Decisions

- Work only in a `codex/*` worktree. Before every commit run `git branch --show-current`.
- Before creating the migration, rerun `git log --all --oneline -- backend/alembic/versions/`; the current observed head is `097_salary_calc_flags`, but the plan must use the latest head at execution time.
- The external customer source is read-only `lsordertest.customer_info`. Sales ownership is the current row in `customer_commission_snapshot`; the salesperson ID there is an OKKI `user_basic.user_id`.
- Map the logged-in `ark_users.id` to OKKI through active primary `ArkUserExternalBinding(provider="okki")`. Do not compare Ark user IDs with OKKI user IDs.
- A product publication copies selected source images into `customer-image` private storage. Published products must not break when an internal reference-library item is deleted.
- Public requests use `Authorization: Invite <token>`. The first `/create/:token` route stores the token in `sessionStorage`, replaces the URL with `/create`, and all subsequent API calls use the header.
- Invitation plaintext is returned only by the create response. Store only SHA-256 digest and a six-character suffix.
- Quota is consumed atomically with generation creation. A generation may be refunded once only when no provider request was sent or the provider explicitly proves no charge.
- V1 retention is fixed: customer access stops immediately on expiration/revocation; assets are eligible for cleanup 30 days after invitation expiry.
- The public UI is named “莱莎产品效果图” and the route is `/create/:token?`.

## File Map

### Shared Image Runtime

- Create `backend/app/ai/image_job_runtime.py`: immutable provider request/result contracts; provider call; response decoding to validated bytes/MIME; usage/cost parsing; customer-safe error classification. It must not import `app.design_image` or `app.customer_image`.
- Modify `backend/app/design_image/worker.py`: delegate provider-neutral work to the shared runtime while retaining design-image claim, session/message creation, and persistence.
- Modify `backend/tests/test_design_image_worker.py`: regression tests proving extraction does not change current jobs.
- Create `backend/tests/test_ai_image_job_runtime.py`: direct unit tests for the extracted contract.

### Customer Image Backend

- Create `backend/app/customer_image/__init__.py`.
- Create `backend/app/customer_image/models.py`: product, product asset, option, option value, invitation, invitation-product, asset, generation.
- Create `backend/app/customer_image/schemas.py`: internal and public request schemas with strict validators.
- Create `backend/app/customer_image/token_service.py`: issue/hash/resolve invite tokens.
- Create `backend/app/customer_image/file_service.py`: wrapper over normalized private storage using invitation IDs as storage owners.
- Create `backend/app/customer_image/prompt_service.py`: validate selections and build frozen prompt snapshots.
- Create `backend/app/customer_image/service.py`: products, customer scope, invitations, logo, quota, listings, cleanup.
- Create `backend/app/customer_image/router.py`: RBAC internal API.
- Create `backend/app/customer_image/public_router.py`: invitation-authenticated customer API.
- Create `backend/app/customer_image/worker.py`: lease customer generations, call shared runtime, finalize or fail/refund.
- Create `backend/alembic/versions/102_customer_image_portal.py`: eight domain tables and indexes.
- Modify `backend/app/core/config.py`: preset, concurrency, lease, rate limit and retention settings.
- Modify `backend/app/auth/service.py`: `customer_image:read/write/admin` permission metadata.
- Modify `backend/app/routers.py`: register internal and public routers in literal-before-parameter order.
- Modify `backend/app/schedulers/registry.py`: run the customer queue and daily retention cleanup.

### Backend Tests And Docs

- Create `backend/tests/test_customer_image_models.py`.
- Create `backend/tests/test_customer_image_tokens.py`.
- Create `backend/tests/test_customer_image_service.py`.
- Create `backend/tests/test_customer_image_api.py`.
- Create `backend/tests/test_customer_image_worker.py`.
- Create `backend/tests/test_customer_image_cleanup.py`.
- Modify `docs/api-reference.md`, `docs/database.md`, `docs/module-notes.md`, and `docs/runbook.md`.

### Frontend

- Modify `frontend/src/api/request.js`: allow a client-supplied auth injector and disable Ark-login redirect for invite clients.
- Modify `frontend/src/api/clients.js`: register `customerImageClient` and `customerImagePublicClient`.
- Create `frontend/src/api/customerImage.js`: internal API calls.
- Create `frontend/src/api/customerImagePublic.js`: invitation API calls and blob reads.
- Create `frontend/src/views/customer-image/inviteSession.js`: token capture, header generation, and clearing.
- Create `frontend/src/views/customer-image/state.js`: pure public portal state helpers.
- Create `frontend/src/views/customer-image/CustomerImagePortal.vue`.
- Create `frontend/src/views/customer-image/CustomerProductCatalog.vue`.
- Create `frontend/src/views/customer-image/CustomerProductEditor.vue`.
- Create focused public components under `frontend/src/views/customer-image/components/`.
- Create internal admin pages under `frontend/src/views/customer-image/admin/`.
- Modify `frontend/src/router/index.js` and `frontend/src/config/navigation.js`.
- Create `frontend/tests/customerImageInvite.test.mjs`, `customerImageState.test.mjs`, `customerImageRouting.test.mjs`, and `customerImageLayout.test.mjs`.

## Task 1: Extract The Shared Image Provider Runtime

**Files:**
- Create: `backend/app/ai/image_job_runtime.py`
- Modify: `backend/app/design_image/worker.py`
- Test: `backend/tests/test_ai_image_job_runtime.py`
- Test: `backend/tests/test_design_image_worker.py`

- [ ] **Step 1: Write failing contract tests**

Add tests for a provider-neutral request, edit/generate routing, decoded PNG/JPEG/WebP responses, URL host allowlist, usage parsing, cost overflow protection, and error mapping:

```python
def test_call_image_provider_routes_edit_when_inputs_exist(db, monkeypatch):
    request = ImageJobRequest(
        preset_name="design_image_generation",
        prompt="keep logo exact",
        caller_module="customer_image",
        caller_user_id=7,
        size="1024x1024",
        quality="medium",
        input_images=(ImageInput("logo.png", b"png", "image/png"),),
        expected_config_version=None,
        download_hosts=frozenset(),
        pricing_snapshot=None,
    )
    monkeypatch.setattr(runtime.ai_service, "edit_image", lambda **kwargs: {"content": VALID_PNG_B64})
    result = runtime.call_image_provider(db, request)
    assert result.image.declared_mime == "image/png"
    assert result.image.content.startswith(b"\x89PNG\r\n\x1a\n")

def test_classify_image_error_marks_moderation_as_not_refundable():
    exc = make_http_error(400, "content_policy")
    failure = classify_image_error(exc)
    assert failure.code == "moderation_blocked"
    assert failure.refund_eligible is False
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `cd backend; pytest tests/test_ai_image_job_runtime.py -q`

Expected: collection fails because `app.ai.image_job_runtime` does not exist.

- [ ] **Step 3: Implement the immutable runtime contract**

Create these public types and functions:

```python
@dataclass(frozen=True, slots=True)
class ImageInput:
    filename: str
    content: bytes
    content_type: str

@dataclass(frozen=True, slots=True)
class ImageJobRequest:
    preset_name: str
    prompt: str
    caller_module: str
    caller_user_id: int
    size: str | None
    quality: str | None
    input_images: tuple[ImageInput, ...]
    expected_config_version: dict | None
    download_hosts: frozenset[str]
    pricing_snapshot: dict | None

@dataclass(frozen=True, slots=True)
class ImagePayload:
    content: bytes
    declared_mime: str

@dataclass(frozen=True, slots=True)
class ImageJobResult:
    image: ImagePayload
    log_id: int | None
    provider_attempt_count: int
    billing_certainty: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    estimated_cost_microusd: int | None

@dataclass(frozen=True, slots=True)
class ImageJobFailure:
    code: str
    customer_message: str
    provider_attempt_count: int
    log_id: int | None
    refund_eligible: bool
```

Move the existing `_decode_provider_content`, `_usage_values`, `_safe_nonnegative_bigint`, `_estimated_cost`, and `_map_error` behavior without changing semantics. `_decode_provider_content` returns `ImagePayload` after base64/URL host, byte limit and file-magic validation; it does not normalize or store files. `call_image_provider(db, request)` calls only `app.ai.service.generate_image/edit_image`, then returns `ImageJobResult`. The shared module must not import either business domain.

- [ ] **Step 4: Adapt the design-image worker without changing persistence**

Keep claim/lease/recovery and `_finalize_success/_finalize_failure` in `design_image.worker`. Convert `_JobSnapshot` to `ImageJobRequest`, call the runtime, pass `result.image.content/declared_mime` through existing `design_image.file_service.normalize_upload`, save it, and copy result fields into the existing job.

- [ ] **Step 5: Run extraction regression tests**

Run:

```powershell
cd backend
pytest tests/test_ai_image_job_runtime.py tests/test_design_image_worker.py tests/test_design_image_orphan_recovery.py -q
```

Expected: all pass; existing late-response, stale-lease, missing-log, and cost tests remain green.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/ai/image_job_runtime.py backend/app/design_image/worker.py backend/tests/test_ai_image_job_runtime.py backend/tests/test_design_image_worker.py
git commit -m "refactor(ai): extract shared image job runtime"
```

## Task 2: Add Customer Image Schema And Configuration

**Files:**
- Create: `backend/app/customer_image/__init__.py`
- Create: `backend/app/customer_image/models.py`
- Create: `backend/alembic/versions/102_customer_image_portal.py`
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_customer_image_models.py`

- [ ] **Step 1: Recheck the migration head and select the revision**

Run:

```powershell
git log --all --oneline -- backend/alembic/versions/
cd backend
alembic heads
```

Expected after integration: exactly one head at `101_knowledge_poc`. Create `102_customer_image_portal.py` with `revision = "102_customer_image_portal"` and `down_revision = "101_knowledge_poc"`, then immediately `git add` it; never create a second `102` or a second Alembic head.

- [ ] **Step 2: Write failing model and settings tests**

Assert table names, unique constraints, no plaintext token column, generation idempotency, and fixed settings:

```python
def test_invitation_never_persists_plaintext_token():
    columns = CustomerImageInvite.__table__.columns.keys()
    assert "token_hash" in columns
    assert "token_suffix" in columns
    assert "token" not in columns

def test_customer_image_generation_idempotency_is_invite_scoped():
    names = {c.name for c in CustomerImageGeneration.__table__.constraints}
    assert "uq_ci_generation_invite_request" in names
```

- [ ] **Step 3: Create the domain models**

Use these eight tables:

```text
ark_customer_image_products
ark_customer_image_product_assets
ark_customer_image_product_options
ark_customer_image_option_values
ark_customer_image_invites
ark_customer_image_invite_products
ark_customer_image_assets
ark_customer_image_generations
```

Important columns and constraints:

- Product: `id`, `name`, `category`, `description`, `fixed_prompt`, `output_prompt`, `config_version`, `is_published`, `sort`, audit columns.
- Product asset: `product_id`, `role` (`cover/reference`), private path and image metadata, `position`; unique `(product_id, role, position)`.
- Option: `product_id`, `key`, `label`, `control_type`, `required`, `default_value`, `sort`; unique `(product_id, key)`.
- Value: `option_id`, `value`, `label`, `prompt_fragment`, `color_hex`, `pantone_code`, `sort`, `is_active`; unique `(option_id, value)`.
- Invite: `customer_id` string, customer-name snapshot, `created_by` Ark user FK, OKKI salesperson snapshot, `token_hash CHAR(64) UNIQUE`, suffix, `starts_at`, `expires_at`, `quota_total`, `quota_used`, nullable `current_logo_asset_id`, `revoked_at`, `created_at`. Add `current_logo_asset_id` after the asset table exists in the migration to avoid a circular create-order dependency.
- Invite-product: unique `(invite_id, product_id)`.
- Asset: `invite_id`, `asset_type`, private image metadata, `created_at`, `deleted_at`.
- Generation: invite/product/logo/output references, request ID, product/config/options/prompt snapshots, frozen ordered `reference_asset_ids` JSON, status and lease fields, provider/audit/cost fields, `quota_refunded_at`; unique `(invite_id, request_id)`.

Do not store a separate invite status column. Add check constraints for positive quota and nonnegative used count.

- [ ] **Step 4: Add explicit settings**

Add positive validated settings:

```python
CUSTOMER_IMAGE_PRESET_NAME: str = "design_image_generation"
CUSTOMER_IMAGE_WORKER_CONCURRENCY: _PositiveInt = 2
CUSTOMER_IMAGE_LEASE_SECONDS: _PositiveInt = 420
CUSTOMER_IMAGE_STALE_SECONDS: _PositiveInt = 480
CUSTOMER_IMAGE_RETENTION_DAYS: _PositiveInt = 30
CUSTOMER_IMAGE_PUBLIC_RATE_PER_MINUTE: _PositiveInt = 30
CUSTOMER_IMAGE_MAX_REQUIREMENT_CHARS: _PositiveInt = 500
```

Validate stale seconds greater than lease seconds. Reuse `DESIGN_IMAGE_STORAGE_ROOT`, upload byte and pixel limits; do not introduce a second filesystem root.

- [ ] **Step 5: Implement the migration and run schema tests**

The migration must use exact FK types, create tables in dependency order, and drop in reverse order. Run:

```powershell
cd backend
pytest tests/test_customer_image_models.py -q
alembic upgrade head --sql > ../tmp/customer-image-migration.sql
```

Expected: tests pass and offline SQL renders one linear migration without multiple heads.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/customer_image backend/app/core/config.py backend/alembic/versions backend/tests/test_customer_image_models.py
git commit -m "feat(customer-image): add portal persistence schema"
```

## Task 3: Implement Invite Tokens And Sales-Owned Customer Search

**Files:**
- Create: `backend/app/customer_image/token_service.py`
- Create: `backend/app/customer_image/schemas.py`
- Create: `backend/app/customer_image/service.py`
- Modify: `backend/app/auth/service.py`
- Test: `backend/tests/test_customer_image_tokens.py`
- Test: `backend/tests/test_customer_image_service.py`

- [ ] **Step 1: Write failing token and customer-scope tests**

Cover one-time plaintext, digest lookup, expired/revoked rejection, admin all-customer search, salesperson private-customer search, and missing OKKI binding:

```python
def test_salesperson_only_lists_current_owned_customers(db, salesperson):
    bind_okki(db, salesperson.id, "1007")
    seed_customer_snapshot(db, customer_id="c1", salesperson_id="1007", current=True)
    seed_customer_snapshot(db, customer_id="c2", salesperson_id="1008", current=True)
    assert [row["id"] for row in list_available_customers(db, salesperson.id, False, "")] == ["c1"]

def test_resolve_invite_uses_digest_not_plaintext(db):
    plaintext, row = issue_invite_token(db, invite)
    assert row.token_hash == hashlib.sha256(plaintext.encode()).hexdigest()
    assert plaintext not in repr(row.__dict__)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `cd backend; pytest tests/test_customer_image_tokens.py tests/test_customer_image_service.py -q`

Expected: modules or functions are missing.

- [ ] **Step 3: Implement token issuance and resolution**

Use `secrets.token_urlsafe(32)`, SHA-256 digest, `hmac.compare_digest` where raw comparisons occur, and a dependency-friendly resolver:

```python
def issue_token() -> IssuedToken:
    plaintext = secrets.token_urlsafe(32)
    return IssuedToken(
        plaintext=plaintext,
        digest=hashlib.sha256(plaintext.encode("utf-8")).hexdigest(),
        suffix=plaintext[-6:],
    )

def resolve_active_invite(db, plaintext: str, now: datetime) -> CustomerImageInvite:
    digest = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    row = db.scalar(select(CustomerImageInvite).where(CustomerImageInvite.token_hash == digest))
    if row is None or row.revoked_at is not None or not (row.starts_at <= now < row.expires_at):
        raise InviteUnavailableError("此链接已失效，请联系您的业务经理重新获取")
    return row
```

Never log plaintext or include it in exception messages.

- [ ] **Step 4: Implement customer search with the correct identity mapping**

Resolve Ark user to OKKI through `ArkUserExternalBinding(provider="okki")`. For non-admin callers, join current `CustomerCommissionSnapshot` to `CustomerInfo` and filter `salesperson_id == str(okki_user_id)`. Admin callers may search all `CustomerInfo` rows. Return only `company_id`, name, country, and origin.

If a non-admin has no active numeric OKKI binding, return an actionable 409 error: “请先在系统管理 -> 外部账号绑定中绑定 OKKI 账号”.

- [ ] **Step 5: Add permissions and validate schemas**

Add `customer_image:read/write/admin` to `seed_role_permissions`. Invitation create schema requires nonempty customer ID, at least one unique product ID, future `expires_at`, and positive quota. Public requirement max length comes from Settings at service validation as well as a Pydantic hard ceiling of 500.

- [ ] **Step 6: Run focused tests**

Run:

```powershell
cd backend
pytest tests/test_customer_image_tokens.py tests/test_customer_image_service.py tests/test_design_image_permissions.py -q
```

Expected: all pass; design-image permission metadata remains unchanged.

- [ ] **Step 7: Commit**

```powershell
git add backend/app/customer_image backend/app/auth/service.py backend/tests/test_customer_image_tokens.py backend/tests/test_customer_image_service.py
git commit -m "feat(customer-image): add scoped invitation service"
```

## Task 4: Implement Product Templates And Stable Product Assets

**Files:**
- Create: `backend/app/customer_image/file_service.py`
- Modify: `backend/app/customer_image/service.py`
- Modify: `backend/app/customer_image/schemas.py`
- Test: `backend/tests/test_customer_image_service.py`
- Test: `backend/tests/test_customer_image_files.py`

- [ ] **Step 1: Add failing product lifecycle tests**

Test create/update, supported controls only, default value membership, publication requiring a cover and reference, source-library deletion independence, and inactive option filtering.

```python
def test_published_product_keeps_copied_asset_after_library_delete(db, image_bytes):
    product = create_product_from_upload(db, admin_id=1, file=image_bytes)
    publish_product(db, product.id, admin_id=1)
    delete_source_library_asset(db, source_id=44)
    assert open_product_asset(db, product.id, "cover").read() == normalized_bytes(image_bytes)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `cd backend; pytest tests/test_customer_image_service.py tests/test_customer_image_files.py -q`

Expected: product/file service behavior missing.

- [ ] **Step 3: Implement customer-image storage wrapper**

Reuse `design_image.file_service.normalize_upload`, path boundary validation, thumbnail generation, and deletion. Store product assets under synthetic owner directory `product_id` with kind `customer-product`; invitation assets under `invite.id` with kinds `customer-logo` and `customer-output`. This is path partitioning only; authorization always comes from database ownership.

- [ ] **Step 4: Implement product transactions**

One update payload replaces product options and values in a transaction. Reject unsupported `control_type`, duplicate keys/values, missing required defaults, invalid `#RRGGBB`, empty prompt fragments, and publication without at least one cover and one reference asset. Increment `config_version` for any prompt/asset/option change. Replacing a product asset retires the old database row but does not physically delete its file in V1, because queued and historical generations freeze reference asset IDs. Product-asset deletion requires a later audited cleanup that proves no generation snapshot references the asset.

For “choose from internal library”, read and normalize the library file, then save a new customer-product copy before committing the product asset. Roll back and delete copied files if database persistence fails.

- [ ] **Step 5: Run product and file tests**

Run: `cd backend; pytest tests/test_customer_image_service.py tests/test_customer_image_files.py -q`

Expected: all pass, including file rollback cleanup and path traversal rejection.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/customer_image backend/tests/test_customer_image_service.py backend/tests/test_customer_image_files.py
git commit -m "feat(customer-image): add publishable product templates"
```

## Task 5: Add Internal RBAC API For Products And Invitations

**Files:**
- Create: `backend/app/customer_image/router.py`
- Modify: `backend/app/routers.py`
- Test: `backend/tests/test_customer_image_api.py`
- Test: `backend/tests/test_customer_image_permissions.py`
- Modify: `docs/api-reference.md`

- [ ] **Step 1: Write failing router contract tests**

Assert every endpoint has the intended dependency and envelope, business users see only their invites, admin sees all, and plaintext token appears only in create response:

```python
EXPECTED = {
    ("get", "/customers"): "customer_image:write",
    ("get", "/products"): "customer_image:read",
    ("post", "/products"): "customer_image:admin",
    ("post", "/invites"): "customer_image:write",
    ("post", "/invites/{invite_id}/revoke"): "customer_image:write",
    ("get", "/generations"): "customer_image:read",
}
```

- [ ] **Step 2: Run tests and verify failure**

Run: `cd backend; pytest tests/test_customer_image_api.py tests/test_customer_image_permissions.py -q`

- [ ] **Step 3: Implement thin internal routes**

Routes call service functions and return `ok(...)`. Use `v-permission` compatible permission codes; never put business logic in the router. Product mutation is admin-only. Invite list/revoke and generation list accept an `is_admin` flag derived from claims, but service still scopes non-admin rows by `created_by`.

Create response shape:

```json
{
  "invite": {"id": 12, "customer_name": "Acme", "expires_at": "2026-08-14T12:00:00", "quota_total": 5},
  "invite_url": "https://leshine.work/create/<plaintext>"
}
```

Do not return `token_hash`; subsequent list responses return only `token_suffix`.

- [ ] **Step 4: Register routes and document endpoints**

Register internal prefix `/api/customer-image`. Keep the later public router on `/api/customer-image/public`. Update API reference with auth mode, schemas, error codes, and “plaintext once” behavior.

- [ ] **Step 5: Run API tests**

Run: `cd backend; pytest tests/test_customer_image_api.py tests/test_customer_image_permissions.py -q`

Expected: all pass; unauthorized users receive 401/403 and cross-owner rows behave as 404.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/customer_image/router.py backend/app/routers.py backend/tests/test_customer_image_api.py backend/tests/test_customer_image_permissions.py docs/api-reference.md
git commit -m "feat(customer-image): expose internal management API"
```

## Task 6: Add Public Invite Context, Logo, And Catalog API

**Files:**
- Create: `backend/app/customer_image/public_router.py`
- Modify: `backend/app/customer_image/service.py`
- Modify: `backend/app/customer_image/schemas.py`
- Modify: `backend/app/routers.py`
- Test: `backend/tests/test_customer_image_public_api.py`

- [ ] **Step 1: Write failing public isolation tests**

Test missing/invalid/expired/revoked tokens, product binding and published state, cross-invite assets, hidden prompts, logo replacement, and response headers:

```python
def test_public_product_never_returns_prompt_fragments(client, invite_header):
    body = client.get("/api/customer-image/public/products", headers=invite_header).json()["data"]
    serialized = json.dumps(body, ensure_ascii=False)
    assert "fixed_prompt" not in serialized
    assert "prompt_fragment" not in serialized

def test_cross_invite_asset_is_not_found(client, invite_a_header, invite_b_asset):
    response = client.get(
        f"/api/customer-image/public/assets/{invite_b_asset.id}/content",
        headers=invite_a_header,
    )
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests and verify failure**

Run: `cd backend; pytest tests/test_customer_image_public_api.py -q`

- [ ] **Step 3: Implement the Invite authorization dependency**

Parse exactly `Authorization: Invite <token>`, resolve the current active invitation on every request, and attach it as a dependency result. Use one generic 401 detail for absent/invalid/expired/revoked credentials. Add per-invite plus trusted-real-IP sliding-window rate limiting to public write endpoints; read endpoints remain bounded by normal web-server limits.

- [ ] **Step 4: Implement context, catalog, logo, and asset endpoints**

Public context returns brand name, customer display name, expiry, quota total/used/remaining, current logo metadata, and visible product count. Catalog returns only invite-bound published products and visible labels/defaults. Logo upload normalizes and saves a new asset, atomically switches `current_logo_asset_id`, and leaves older versions for historical tasks.

Content responses set:

```text
Cache-Control: private, no-store
Referrer-Policy: no-referrer
X-Content-Type-Options: nosniff
```

- [ ] **Step 5: Run public API tests**

Run: `cd backend; pytest tests/test_customer_image_public_api.py tests/test_customer_image_files.py -q`

Expected: all pass; prompts and storage paths are absent from all customer JSON.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/customer_image/public_router.py backend/app/customer_image/service.py backend/app/customer_image/schemas.py backend/app/routers.py backend/tests/test_customer_image_public_api.py
git commit -m "feat(customer-image): add invitation customer API"
```

## Task 7: Implement Prompt Assembly, Atomic Quota, And Generation Submission

**Files:**
- Create: `backend/app/customer_image/prompt_service.py`
- Modify: `backend/app/customer_image/service.py`
- Modify: `backend/app/customer_image/public_router.py`
- Test: `backend/tests/test_customer_image_prompt.py`
- Test: `backend/tests/test_customer_image_quota.py`

- [ ] **Step 1: Write failing prompt and concurrency tests**

Test selection validation, fixed priority/order, optional requirement trimming, stale product version, duplicate request replay, concurrent last-slot submission, and task snapshots.

```python
def test_same_request_id_returns_original_without_second_quota_use(db, invite, payload):
    first = create_generation(db, invite, payload, request_id="req-1")
    second = create_generation(db, invite, payload, request_id="req-1")
    db.refresh(invite)
    assert first.id == second.id
    assert invite.quota_used == 1

def test_prompt_order_is_fixed(product, logo, selections):
    prompt = build_prompt(product, logo, selections, "make it festive")
    assert prompt.index("PRODUCT CONSTRAINTS") < prompt.index("PRESET SELECTIONS")
    assert prompt.index("PRESET SELECTIONS") < prompt.index("CUSTOMER REQUIREMENT")
```

- [ ] **Step 2: Run tests and verify failure**

Run: `cd backend; pytest tests/test_customer_image_prompt.py tests/test_customer_image_quota.py -q`

- [ ] **Step 3: Implement strict server-side prompt assembly**

`validate_and_build_prompt` loads the current published product with options/values, rejects unknown/missing/disabled selections, normalizes booleans and colors, and emits sections in locked order. Include an explicit sentence that customer requirements cannot override product identity, logo fidelity, or selected presets. Return both final prompt and a customer-safe option snapshot.

- [ ] **Step 4: Implement atomic submission**

Within one transaction:

1. Lock invite row with `with_for_update()`.
2. Revalidate active invite and bound published product.
3. Query `(invite_id, request_id)` and return existing row before quota checks.
4. Require current logo.
5. Require `quota_used < quota_total`.
6. Build frozen snapshots and increment `quota_used`.
7. Create queued generation with `preset_name`, model/config snapshot from the active preset, and a frozen ordered list of logo/reference asset IDs. The worker must use this list rather than re-reading the product's current assets.

Handle unique-race collision with a nested savepoint, then read and return the winning row without rolling back unrelated state.

- [ ] **Step 5: Expose submission and generation listing**

`POST /public/generations` returns 202 with status. `GET /public/generations` returns newest first with only customer-safe state, selected labels, error message, result URLs, and timestamps. `GET /public/generations/{id}` enforces invitation ownership.

- [ ] **Step 6: Run quota and public tests**

Run:

```powershell
cd backend
pytest tests/test_customer_image_prompt.py tests/test_customer_image_quota.py tests/test_customer_image_public_api.py -q
```

Expected: all pass; the concurrent test proves one final quota slot creates one generation.

- [ ] **Step 7: Commit**

```powershell
git add backend/app/customer_image/prompt_service.py backend/app/customer_image/service.py backend/app/customer_image/public_router.py backend/tests/test_customer_image_prompt.py backend/tests/test_customer_image_quota.py
git commit -m "feat(customer-image): queue quota-safe generations"
```

## Task 8: Implement Customer Generation Worker And Recovery

**Files:**
- Create: `backend/app/customer_image/worker.py`
- Modify: `backend/app/schedulers/registry.py`
- Test: `backend/tests/test_customer_image_worker.py`

- [ ] **Step 1: Write failing worker state tests**

Cover atomic `skip_locked` claim, immutable snapshot, logo first/reference images after it, heartbeat, stale recovery, success output, lease loss, provider failure, exactly-once refund, and missing AI log.

```python
def test_pre_provider_failure_refunds_once(db, queued_generation, monkeypatch):
    monkeypatch.setattr(runtime, "call_image_provider", Mock(side_effect=before_send_error()))
    execute_claimed_generation(queued_generation.id, claim_token)
    execute_failure_finalize_again(queued_generation.id, claim_token)
    db.refresh(queued_generation.invite)
    assert queued_generation.invite.quota_used == 0
    assert queued_generation.quota_refunded_at is not None

def test_uncertain_provider_failure_does_not_refund(db, queued_generation):
    failure = ImageJobFailure(
        code="provider_timeout",
        customer_message="图片服务响应超时，请稍后重试",
        provider_attempt_count=1,
        log_id=42,
        refund_eligible=False,
    )
    finalize_failure(queued_generation.id, claim_token="lease-1", failure=failure)
    assert queued_generation.invite.quota_used == 1
```

- [ ] **Step 2: Run tests and verify failure**

Run: `cd backend; pytest tests/test_customer_image_worker.py -q`

- [ ] **Step 3: Implement lease/claim and immutable snapshot**

Follow `design_image.worker`: short claim transaction, Provider I/O outside transactions, lease-token proof for terminal writes, heartbeat every lease/3, and stale recovery. Load logo first and product references in stable position order. Set `caller_module="customer_image"` and `caller_user_id=invite.created_by` for AI audit ownership.

- [ ] **Step 4: Implement success and failure finalization**

On success, normalize `result.image` through `customer_image.file_service`, save customer output, create `CustomerImageAsset(asset_type="generated")`, copy runtime usage/cost/log fields, and clear lease columns. On failure, copy customer-safe classification and provider attempt count. Refund only if `failure.refund_eligible`, generation has no `quota_refunded_at`, and invite quota is positive; lock generation and invite in the same transaction.

- [ ] **Step 5: Register one combined queue wake-up**

Add `process_customer_image_queue` to the existing design image interval, or register a separate stable job ID using the same interval. `max_instances=1` and `coalesce=True` are mandatory. Do not run Provider calls inside an open scheduler database session.

- [ ] **Step 6: Run worker regression tests**

Run:

```powershell
cd backend
pytest tests/test_customer_image_worker.py tests/test_design_image_worker.py tests/test_scheduler_jobs.py -q
```

Expected: all pass; both queues are registered once and internal design jobs behave unchanged.

- [ ] **Step 7: Commit**

```powershell
git add backend/app/customer_image/worker.py backend/app/schedulers/registry.py backend/tests/test_customer_image_worker.py backend/tests/test_scheduler_jobs.py
git commit -m "feat(customer-image): process recoverable customer jobs"
```

## Task 9: Add Invite-Aware Frontend API And Public Routing

**Files:**
- Modify: `frontend/src/api/request.js`
- Modify: `frontend/src/api/clients.js`
- Create: `frontend/src/api/customerImage.js`
- Create: `frontend/src/api/customerImagePublic.js`
- Create: `frontend/src/views/customer-image/inviteSession.js`
- Modify: `frontend/src/router/index.js`
- Test: `frontend/tests/customerImageInvite.test.mjs`
- Test: `frontend/tests/customerImageRouting.test.mjs`

- [ ] **Step 1: Write failing invite session and routing tests**

Test route token capture, URL replacement, tab-scoped storage, Invite header, no Ark JWT injection, no login redirect on public 401, and mobile public-page exemption.

```javascript
test('captureInviteToken removes it from the visible URL', () => {
  const history = { replaceState: mock.fn() }
  captureInviteToken('secret-token', { history, storage })
  assert.equal(storage.getItem(INVITE_KEY), 'secret-token')
  assert.deepEqual(history.replaceState.mock.calls[0].arguments.slice(1), ['', '/create'])
})
```

- [ ] **Step 2: Run tests and verify failure**

Run: `cd frontend; node --test tests/customerImageInvite.test.mjs tests/customerImageRouting.test.mjs`

- [ ] **Step 3: Generalize the existing API client narrowly**

Extend `createApiClient` options with:

```javascript
createApiClient({
  baseURL,
  timeout,
  getAuthorization: () => token ? `Invite ${token}` : null,
  redirectOnUnauthorized: false,
})
```

Default behavior stays exactly as today: Ark bearer injection and login redirect. Register normal internal `customerImageClient` and public `customerImagePublicClient`. Do not create Axios instances outside `clients.js`.

- [ ] **Step 4: Implement session and API modules**

Use `sessionStorage` key `ark_customer_image_invite`. `captureInviteToken` validates a nonempty token, stores it, and `history.replaceState` removes it from the URL. Public API methods use silent requests and blob response for assets.

- [ ] **Step 5: Add the public route before MainLayout**

Register `/create/:token?` with `meta.public=true`, `meta.customerImage=true`, and title “莱莎产品效果图”. Update the mobile login redirection guard so this public route never redirects to `/m/login.html`.

- [ ] **Step 6: Run tests and build**

Run:

```powershell
cd frontend
node --test tests/customerImageInvite.test.mjs tests/customerImageRouting.test.mjs
npm run build
```

Expected: tests pass and Vite builds without duplicate Axios bundles or router warnings.

- [ ] **Step 7: Commit**

```powershell
git add frontend/src/api/request.js frontend/src/api/clients.js frontend/src/api/customerImage.js frontend/src/api/customerImagePublic.js frontend/src/views/customer-image/inviteSession.js frontend/src/router/index.js frontend/tests/customerImageInvite.test.mjs frontend/tests/customerImageRouting.test.mjs
git commit -m "feat(customer-image): add invite-aware public client"
```

## Task 10: Build The Customer Catalog And Generation Workspace

**Files:**
- Create: `frontend/src/views/customer-image/CustomerImagePortal.vue`
- Create: `frontend/src/views/customer-image/CustomerProductCatalog.vue`
- Create: `frontend/src/views/customer-image/CustomerProductEditor.vue`
- Create: `frontend/src/views/customer-image/state.js`
- Create: `frontend/src/views/customer-image/composables/useCustomerImagePortal.js`
- Create: `frontend/src/views/customer-image/composables/useCustomerImageAssets.js`
- Create: `frontend/src/views/customer-image/components/CustomerLogoUpload.vue`
- Create: `frontend/src/views/customer-image/components/ProductOptionGroup.vue`
- Create: `frontend/src/views/customer-image/components/GenerationHistory.vue`
- Create: `frontend/src/views/customer-image/components/GenerationPreview.vue`
- Test: `frontend/tests/customerImageState.test.mjs`
- Test: `frontend/tests/customerImageLayout.test.mjs`

- [ ] **Step 1: Write failing pure-state tests**

Test single-product auto-selection, defaults, required-option completeness, idempotency key stability while submitting, status labels, remaining quota, and error-state preservation.

```javascript
test('single visible product opens editor automatically', () => {
  const next = applyContext(emptyState(), { products: [{ id: 9 }] })
  assert.equal(next.selectedProductId, 9)
  assert.equal(next.view, 'editor')
})

test('failed submission preserves logo and selected options', () => {
  const failed = applySubmitFailure(readyState, '服务暂不可用')
  assert.deepEqual(failed.selections, readyState.selections)
  assert.equal(failed.logo.id, readyState.logo.id)
})
```

- [ ] **Step 2: Run tests and verify failure**

Run: `cd frontend; node --test tests/customerImageState.test.mjs tests/customerImageLayout.test.mjs`

- [ ] **Step 3: Implement the portal state and data flow**

On mount: capture route token, load context/catalog/generations in parallel, select the only product automatically, start polling only while queued/running generations exist, and revoke blob URLs on replacement/unmount. Use one request ID per button action and keep it stable until the request resolves.

- [ ] **Step 4: Build the catalog**

Use category tabs, one search field, and real product image cards. Search product name and description client-side because the invitation product set is bounded. Cards use `aspect-ratio`, no nested cards, and an explicit “立即设计” command.

- [ ] **Step 5: Build the three-column desktop editor and single-column mobile flow**

Desktop tracks: `260px minmax(0, 1fr) 320px`; mobile below 760px uses normal document flow with a sticky safe-area action bar. Left: back, logo, result thumbnails. Center: product/latest result preview. Right: option groups, optional requirement, remaining quota, generate button.

Controls: radio-card groups for `single_choice`, actual color swatches for `color`, Element Plus switch for `boolean`. No free prompt editor and no model/quality controls.

- [ ] **Step 6: Implement feedback and motion**

Use explicit queued/running/succeeded/failed messages from the spec. Animate only opacity/transform at 160-200ms ease-out; button press 100-160ms. Add `@media (prefers-reduced-motion: reduce)` to remove transforms and nonessential transitions. The generation button stays disabled without logo, incomplete required options, exhausted quota, or active submission.

- [ ] **Step 7: Run state/layout tests and build**

Run:

```powershell
cd frontend
node --test tests/customerImageState.test.mjs tests/customerImageLayout.test.mjs
npm run build
```

Expected: all pass; no component exceeds 500 lines.

- [ ] **Step 8: Commit**

```powershell
git add frontend/src/views/customer-image frontend/tests/customerImageState.test.mjs frontend/tests/customerImageLayout.test.mjs
git commit -m "feat(customer-image): build customer generation portal"
```

## Task 11: Build Internal Product, Invite, And Usage Management

**Files:**
- Create: `frontend/src/views/customer-image/admin/CustomerImageAdmin.vue`
- Create: `frontend/src/views/customer-image/admin/ProductTemplateList.vue`
- Create: `frontend/src/views/customer-image/admin/ProductTemplateEditor.vue`
- Create: `frontend/src/views/customer-image/admin/InviteList.vue`
- Create: `frontend/src/views/customer-image/admin/InviteCreateDialog.vue`
- Create: `frontend/src/views/customer-image/admin/GenerationUsageList.vue`
- Create: `frontend/src/views/customer-image/admin/composables/useCustomerImageAdmin.js`
- Modify: `frontend/src/config/navigation.js`
- Test: `frontend/tests/customerImageAdmin.test.mjs`

- [ ] **Step 1: Write failing admin behavior tests**

Test permission-to-tab mapping, explicit expiry/quota requirement, at least one product, one-time link result, link copy, revoke action, and non-admin product mutation concealment.

- [ ] **Step 2: Run tests and verify failure**

Run: `cd frontend; node --test tests/customerImageAdmin.test.mjs`

- [ ] **Step 3: Build the admin shell and lists**

Follow `system/DictManagement.vue` for product metadata editing and `expo/ExpoLeads.vue` list/search/pagination patterns. Use tabs for Products, Invitations, Usage. Product mutation controls use `v-permission="'customer_image:admin'"`; invite actions use `customer_image:write`.

- [ ] **Step 4: Build product template editing**

Support name/category/description, cover/reference uploads or internal-library copy, three option control types, ordered values, default selection, prompt fragments, and publish toggle. Present hidden prompts only to admin. Reject publish client-side when cover/reference/default requirements are missing; backend remains authoritative.

- [ ] **Step 5: Build invitation creation**

Customer search is server-backed and scoped. Require explicit expiry and positive generation count; product selection is multi-select with thumbnails. After create, show the plaintext link in a one-time result dialog with Copy icon action and clear warning that it cannot be retrieved again. Closing the dialog removes plaintext from component state.

- [ ] **Step 6: Add navigation entry**

Add one `NAV_ENTRIES` item under Design Center with `anyPermission: ['customer_image:read','customer_image:write','customer_image:admin']`. Extend the Design group visibility permissions. Do not add public `/create` to navigation.

- [ ] **Step 7: Run tests and build**

Run:

```powershell
cd frontend
node --test tests/customerImageAdmin.test.mjs tests/permissionMatrix.test.mjs
npm run build
```

Expected: all pass; unauthorized actions are absent and route guard works.

- [ ] **Step 8: Commit**

```powershell
git add frontend/src/views/customer-image/admin frontend/src/config/navigation.js frontend/tests/customerImageAdmin.test.mjs
git commit -m "feat(customer-image): add portal administration"
```

## Task 12: Add Retention, Documentation, Adversarial Review, And Live Verification

**Files:**
- Modify: `backend/app/customer_image/service.py`
- Modify: `backend/app/customer_image/worker.py`
- Modify: `backend/app/schedulers/registry.py`
- Test: `backend/tests/test_customer_image_cleanup.py`
- Modify: `docs/database.md`
- Modify: `docs/module-notes.md`
- Modify: `docs/runbook.md`
- Modify: `docs/api-reference.md`
- Modify: `docs/architecture.md`

- [ ] **Step 1: Write failing retention tests**

Test exactly 30 days, active invite preservation, unfinished generation preservation, database soft-delete before file deletion, and retry after file deletion failure.

```python
def test_cleanup_waits_thirty_days_after_expiry(db, expired_invite, now):
    expired_invite.expires_at = now - timedelta(days=29, hours=23)
    assert cleanup_expired_invite_assets(db, now) == 0
    expired_invite.expires_at = now - timedelta(days=30)
    assert cleanup_expired_invite_assets(db, now) == 2
```

- [ ] **Step 2: Implement daily cleanup**

Select eligible invitation assets whose invite expired at least 30 days ago, is not extended, and has no queued/running generation dependency. Product assets follow product lifecycle and are not part of invitation retention. For invite assets, soft-delete/mark cleanup in the database first, commit, then delete exact original/thumbnail paths best-effort with visible warning logs. Register one daily scheduler job with a stable ID.

- [ ] **Step 3: Document schema, operations, and token logging**

Update:

- `docs/database.md`: all eight tables, constraints, ownership, quota/refund fields.
- `docs/api-reference.md`: complete internal/public endpoints and auth headers.
- `docs/module-notes.md`: prompt priority, customer scope, stable product assets, worker/refund rules.
- `docs/architecture.md`: customer domain and shared runtime boundary.
- `docs/runbook.md`: preset requirement, storage ACL, scheduler, cleanup, invite revocation, and smoke test.

Document Nginx requirements before issuing production links:

- Do not log plaintext `/create/{token}`. Update the live `leshine.work` config to use a server-wide safe log format that replaces both the request URI and HTTP Referer fields and does not record raw `$request`; a `/create`-only access log does not protect Referer values on later asset requests.
- Add a dedicated `location ~ ^/create(?:/[^/]+)?/?$` before the SPA fallback. Its HTML response must always send `Referrer-Policy: no-referrer` and `Cache-Control: private, no-store`, without changing cache headers for `/assets/*` or other static resources.
- The current server-level `/api` `client_max_body_size 5m` blocks valid 5-20 MiB LOGO uploads before the application can validate them. Add an exact-match `location = /api/customer-image/public/logo` with `client_max_body_size 21m` (20 MiB application maximum plus multipart overhead) and the same proxy/trusted-IP headers as the existing API location. Keep the existing 5m ceiling for every other public/API route. If the product limit is deliberately reduced below 20 MiB, set this exact location only high enough for that decided limit plus multipart overhead.
- Back up the live config outside `conf.d`, run `nginx -t`, reload, then live-test a LOGO larger than 5 MiB succeeds and a LOGO larger than the 20 MiB application limit is rejected with 413. These checks are a production launch gate, not optional smoke tests.

Do not commit secrets or live tokens.

- [ ] **Step 4: Run complete automated verification**

Run:

```powershell
cd backend
pytest tests/test_ai_image_job_runtime.py tests/test_design_image_worker.py tests/test_customer_image_models.py tests/test_customer_image_tokens.py tests/test_customer_image_service.py tests/test_customer_image_files.py tests/test_customer_image_api.py tests/test_customer_image_permissions.py tests/test_customer_image_public_api.py tests/test_customer_image_prompt.py tests/test_customer_image_quota.py tests/test_customer_image_worker.py tests/test_customer_image_cleanup.py tests/test_scheduler_jobs.py -q
cd ..\frontend
node --test tests/customerImageInvite.test.mjs tests/customerImageRouting.test.mjs tests/customerImageState.test.mjs tests/customerImageLayout.test.mjs tests/customerImageAdmin.test.mjs tests/permissionMatrix.test.mjs
npm run build
cd ..
python scripts/check_conventions.py
python scripts/git_sweep.py
```

Expected: every command exits 0. Record actual test counts and build output in the handoff.

- [ ] **Step 5: Perform required adversarial review**

Dispatch an independent review because this change includes a migration, a state machine, concurrency, public authorization, and more than three files. Fixed review lenses:

- Cross-invite/customer/product access.
- Concurrent quota consume/refund and idempotency.
- Lease loss, late Provider response, duplicate scheduler wake-ups.
- Plaintext token leakage in URLs, logs, exceptions, analytics, and list responses.
- Frontend/backend field and enum consistency.
- All existing design-image worker call sites after shared-runtime extraction.

Fix every P0/P1 finding and rerun the focused tests that prove the fix.

- [ ] **Step 6: Run local real-browser acceptance**

Start the project with its own commands. Create one admin product, one one-product invite, and one multi-product invite. In desktop 1440x900 and mobile 390x844 verify:

1. Single-product auto-entry.
2. Multi-product search/category selection.
3. Logo upload/replacement.
4. Generate, refresh while running, successful result, download, repeat generation.
5. Quota exhaustion preserves history.
6. Revocation invalidates the next request.
7. No overlap, double scroll, clipped labels, or safe-area obstruction.
8. Reduced-motion mode removes nonessential transforms.
9. With a one-time synthetic secret, browser Network evidence shows that only the initial HTML navigation contains it; every later URL path, query string, and Referer omits it.

Capture screenshots and inspect console/network errors. Verify the URL is `/create` after token capture and no request after the first HTML navigation includes the token in path or query.

- [ ] **Step 7: Deploy with the project command and live-verify**

Run the project deployment command from the main worktree only after merge approval:

```powershell
deploy\deploy.bat
```

Before issuing any production invite, apply the documented Nginx access-log redaction, `/create` HTML response headers, and exact LOGO upload location, run `nginx -t`, reload Nginx, and verify with one synthetic secret: neither the logged request URI nor logged HTTP Referer contains it; both response headers are present; and no browser request after the initial navigation contains it in path, query, or Referer. Also verify a LOGO larger than 5 MiB reaches the application and succeeds; a LOGO larger than 20 MiB is rejected with 413; all other public/API routes retain the 5m ceiling. Then repeat the one-product live chain on `https://leshine.work/create/<token>` and confirm the real generated asset downloads.

Do not push `main` unless explicitly instructed. Feature-branch push follows repository backup policy.

- [ ] **Step 8: Commit final implementation docs and cleanup**

```powershell
git add backend/app/customer_image backend/app/schedulers/registry.py backend/tests/test_customer_image_cleanup.py docs/api-reference.md docs/database.md docs/module-notes.md docs/runbook.md docs/architecture.md
git commit -m "docs(customer-image): add operations and verification"
```

## Completion Gate

Implementation is complete only when all conditions are true:

- One-product and multi-product invitation flows both work on desktop and mobile.
- Customer data is isolated by invitation on every API and asset read.
- Prompt internals and storage paths never appear in public JSON.
- Same request ID produces one generation, one quota use, and one Provider call.
- Refund happens once only under the frozen eligibility rules.
- Refresh and process restart recover running work.
- Revocation and expiration close access immediately; retention cleanup waits 30 days.
- Existing internal AI image studio tests remain green after runtime extraction.
- Migration has one head, conventions pass, frontend builds, and adversarial review has no open P0/P1.
- Production Nginx logs are proven to redact invitation tokens in both request URI and HTTP Referer, `/create` HTML sends no-referrer/private-no-store, and post-navigation browser requests contain no token before customer rollout.
