# Design Image Studio Phase 1–5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Phase 0 已验证的 `gpt-image-2` Provider 能力上，交付可灰度上线的设计部 AI 生图工作台，包括私有文件、可恢复任务、连续编辑、额度治理、前端会话体验和运维证据。

**Architecture:** FastAPI 新增 `app/design_image` 领域，MySQL 保存会话、消息、资产和带租约的任务；共享 AI facade 负责 generation/edit、重试、usage 与脱敏日志；APScheduler 只负责周期唤醒 DB worker。Vue 页面通过现有 API Client 创建草稿资产和任务，用 guarded polling 恢复状态，鉴权图片统一加载为 Object URL。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2.0、Alembic、APScheduler、Pillow、httpx、Vue 3、Element Plus、Vite 5、Node test。

**Authoritative spec:** `docs/requirements/2026-08-05-design-image-studio.md`

---

## File map

| Responsibility | Files |
| --- | --- |
| Constitution and migration | `CLAUDE.md`, `backend/alembic/versions/089_design_image_studio.py` |
| Domain persistence | `backend/app/design_image/models.py`, `backend/app/models/__init__.py`, `backend/tests/conftest.py` |
| Configuration and permissions | `backend/app/core/config.py`, `backend/app/auth/service.py` |
| Shared image transport | `backend/app/ai/image_service.py`, `backend/app/ai/service.py`, `backend/app/ai/models.py` |
| Private image files | `backend/app/design_image/file_service.py` |
| Sessions, quota and jobs | `backend/app/design_image/service.py`, `backend/app/design_image/schemas.py` |
| Worker and recovery | `backend/app/design_image/worker.py`, `backend/app/schedulers/registry.py` |
| HTTP contract | `backend/app/design_image/router.py`, `backend/app/routers.py` |
| Frontend contract/state | `frontend/src/api/clients.js`, `frontend/src/api/designImage.js`, `frontend/src/views/design/image-studio/state.js` |
| Frontend experience | `frontend/src/config/navigation.js`, `frontend/src/views/design/image-studio/ImageStudio.vue`, `composables/useImageStudio.js`, `components/*.vue` |
| Operations and handoff | `docs/api-reference.md`, `docs/database.md`, `docs/architecture.md`, `docs/module-notes.md`, `docs/runbook.md`, `docs/requirements/2026-08-05-design-image-studio.md` |

## Task 1: Phase 1 constitution, schema, models, settings and permissions

**Files:**
- Modify: `CLAUDE.md`
- Create: `backend/alembic/versions/089_design_image_studio.py`
- Create: `backend/app/design_image/__init__.py`
- Create: `backend/app/design_image/models.py`
- Modify: `backend/app/ai/models.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/auth/service.py`
- Modify: `backend/tests/conftest.py`
- Create: `backend/tests/test_design_image_models.py`
- Create: `backend/tests/test_design_image_permissions.py`

- [x] **Step 1: Re-check migration topology before writing**

  Run:

  ```powershell
  git log --all --oneline -- backend/alembic/versions/
  cd backend; python -m alembic heads
  ```

  Expected: one head. If it is no longer `088_festival_first_sign`, stop and choose the next free numeric prefix/down revision from current evidence.

- [x] **Step 2: Write failing metadata, permission and settings tests**

  Tests must assert:

  ```python
  expected_tables = {
      "ark_design_image_sessions", "ark_design_image_messages",
      "ark_design_image_assets", "ark_design_image_jobs",
      "ark_design_image_job_assets",
  }
  assert expected_tables <= set(Base.metadata.tables)
  assert DesignImageSession.assets.property.lazy == "noload"
  assert settings.DESIGN_IMAGE_DAILY_LIMIT == 20
  assert settings.DESIGN_IMAGE_WORKER_CONCURRENCY == 3
  assert {"design_image:read", "design_image:write", "design_image:admin"} <= seeded_codes
  ```

  Run: `cd backend; python -m pytest tests/test_design_image_models.py -q`

  Expected: FAIL because the domain and fields do not exist.

- [x] **Step 3: Update the rule before the practice**

  Change the AI rule in `CLAUDE.md` to state that text calls use `app.ai.service.chat`, while business image calls import `generate_image/edit_image` from the same facade. Do not permit business modules to build their own model HTTP clients.

- [x] **Step 4: Implement schema and ORM models**

  Use revision `089_design_image_studio` (or the next free revision discovered in Step 1) and add nullable `ark_ai_call_logs.usage_detail` JSON plus the five tables from spec §6.2. Required database invariants:

  ```python
  UniqueConstraint("owner_user_id", "idempotency_key", name="uq_di_job_owner_idem")
  UniqueConstraint("job_id", "asset_id", name="uq_di_job_asset")
  CheckConstraint("position >= 0", name="ck_di_job_asset_position")
  Index("idx_di_job_claim", "status", "lease_expires_at", "created_at")
  Index("idx_di_job_owner_day", "owner_user_id", "created_at", "status")
  ```

  All ORM relationships must specify `lazy="noload"`. FKs for assets referenced by jobs use `RESTRICT`; owner/session ownership is enforced in services, not by trusting request IDs.

  `owner_user_id/created_by` must exactly match production `ark_users.id` as `mysql.INTEGER(unsigned=True)` in the migration. `ai_call_log_id` matches the existing signed BIGINT. Explicitly import the new domain models from both `backend/app/models/__init__.py` and `backend/tests/conftest.py`, because Alembic and isolated SQLite tests otherwise do not reliably register them.

- [x] **Step 5: Add settings and permission seed**

  Add typed settings with safe defaults:

  ```python
  DESIGN_IMAGE_STORAGE_ROOT: str = r"D:\WORKSOURCE\design-image"
  DESIGN_IMAGE_DAILY_LIMIT: int = 20
  DESIGN_IMAGE_WORKER_CONCURRENCY: int = 3
  DESIGN_IMAGE_WORKER_INTERVAL_SECONDS: int = 10
  DESIGN_IMAGE_LEASE_SECONDS: int = 420
  DESIGN_IMAGE_STALE_SECONDS: int = 480
  DESIGN_IMAGE_DRAFT_TTL_HOURS: int = 24
  DESIGN_IMAGE_MAX_UPLOAD_MB: int = 20
  DESIGN_IMAGE_MAX_PIXELS: int = 60_000_000
  ```

  Seed `read/write/admin` with permitted action names and stable metadata; test two seed runs for idempotence. `read` is the page permission and `write/admin` are action permissions. Preserve the repository's existing system-admin permission expansion, but do not auto-assign them to broad business roles.

- [x] **Step 6: Verify Phase 1 and apply the shared migration**

  Run:

  ```powershell
  cd backend
  python -m pytest tests/test_design_image_models.py tests/test_design_image_permissions.py tests/test_ai_preset_service.py -q
  python -m alembic upgrade head
  python -m alembic heads
  ```

  Expected: tests pass, upgrade succeeds, exactly one head. Inspect the live permission rows after `seed_role_permissions()` and record IDs only if useful; never record credentials.

- [x] **Step 7: Commit Phase 1**

  ```powershell
  git branch --show-current
  git add CLAUDE.md backend/alembic/versions backend/app/design_image backend/app/ai/models.py backend/app/models/__init__.py backend/app/core/config.py backend/app/auth/service.py backend/tests/conftest.py backend/tests/test_design_image_models.py backend/tests/test_design_image_permissions.py
  git commit -m "feat(ai): add design image domain schema"
  ```

## Task 2: Phase 2 shared Image API facade

**Files:**
- Modify: `backend/app/ai/image_service.py`
- Modify: `backend/app/ai/service.py`
- Modify: `backend/tests/test_ai_image_service.py`
- Modify: `backend/tests/test_ai_image_retry.py`

- [x] **Step 1: Write failing transport tests**

  Add tests for `generate_image()` JSON requests, edit repeated multipart images preserving order, `b64_json`/URL/data-URL parsing, detailed usage, request IDs, and provider attempt count. Assert `design_image_generation` never sends `input_fidelity`, while an Expo preset retaining it is unchanged.

  Error matrix must cover 400, 429, 502, 503, 504 and `httpx.ReadTimeout`; only existing fast-failure policy may retry. Tests must assert response snapshots and logs contain neither raw base64 nor Authorization.

  Run: `cd backend; python -m pytest tests/test_ai_image_service.py tests/test_ai_image_retry.py -q`

  Expected: FAIL on missing `generate_image`, usage detail and attempt count.

- [x] **Step 2: Refactor one shared transport result**

  Introduce a typed result compatible with existing callers:

  ```python
  class ImageCallResult(TypedDict):
      content: str
      tokens_used: int | None
      usage_detail: dict
      duration_ms: int
      log_id: int
      provider_attempt_count: int
      request_id: str | None
  ```

  `_send_with_retry()` must return `(response_json, attempts, request_id)` without logging bodies that may include base64. Generation and edit share provider lookup, timeout, headers, retries, usage extraction, AiCallLog state and sanitization.

  Preserve the actual retry contract: 502/503 and eligible transport failures retry; 400/429/504/ReadTimeout do not. Correct stale test comments that claim 504 retries. The shared AI call must not leave a long-lived worker transaction open across HTTP; persist `running` before the call, then finalize in a new transaction/Session so `edit_image()` commit/rollback cannot undo the claim.

- [x] **Step 3: Implement `generate_image()` and facade exports**

  `generate_image()` sends `POST /images/generations` JSON through `build_image_url(provider.api_base, "generations")`. Request parameters are whitelisted; the caller cannot pass model/provider/key. Add `usage_detail` to AiCallLog and re-export both image functions from `app.ai.service`.

- [x] **Step 4: Verify compatibility**

  Run:

  ```powershell
  cd backend
  python -m pytest tests/test_ai_image_service.py tests/test_ai_image_retry.py tests/test_expo_display_image.py tests/test_expo_color_scene.py -q
  ```

  Expected: all pass, proving the existing Expo edit chain is not changed.

- [x] **Step 5: Commit shared transport**

  ```powershell
  git add backend/app/ai backend/tests/test_ai_image_service.py backend/tests/test_ai_image_retry.py
  git commit -m "feat(ai): add shared image generation facade"
  ```

## Task 3: Phase 2 private file service

**Files:**
- Create: `backend/app/design_image/file_service.py`
- Create: `backend/tests/test_design_image_files.py`

- [x] **Step 1: Write failing validation and storage tests**

  Cover JPEG/PNG/WebP magic bytes, fake MIME, decompression bomb/over 60MP, over 20MB, EXIF orientation, metadata stripping, longest edge 2048, SHA-256, UUID relative paths, thumbnails and path traversal. Provider URL tests must cover HTTPS allowlist, every redirect hop, DNS resolving to private/loopback/link-local/metadata addresses, rebinding between validation/connect, missing content length and streamed body over limit.

  Run: `cd backend; python -m pytest tests/test_design_image_files.py -q`

  Expected: FAIL because file service is missing.

- [x] **Step 2: Implement private normalization and atomic storage**

  Public API:

  ```python
  normalize_upload(content: bytes, declared_mime: str) -> NormalizedImage
  save_private_image(image: NormalizedImage, *, owner_user_id: int, kind: str) -> StoredImage
  resolve_private_path(relative_path: str) -> Path
  delete_private_file(relative_path: str) -> None
  download_provider_image(url: str, *, allowed_hosts: set[str]) -> bytes
  ```

  Write to a same-directory temporary file then `os.replace`; validate `Path.resolve().is_relative_to(root.resolve())`; never expose storage paths as public URLs. Remote download must not forward Provider Authorization.

- [x] **Step 3: Verify and commit**

  Run: `cd backend; python -m pytest tests/test_design_image_files.py -q`

  Then:

  ```powershell
  git add backend/app/design_image/file_service.py backend/tests/test_design_image_files.py
  git commit -m "feat(ai): add private design image storage"
  ```

## Task 4: Phase 3 domain services, idempotency and quota

**Files:**
- Create: `backend/app/design_image/schemas.py`
- Create: `backend/app/design_image/service.py`
- Create: `backend/tests/test_design_image_service.py`

- [x] **Step 1: Write failing service tests**

  Cover owner-only session pagination/detail, draft upload attachment/deletion, base/reference ownership, size/quality whitelist, implicit session creation, prompt assembly, daily quota in Asia/Shanghai, one active job, retry creates a new job, and `UNIQUE(owner_user_id,idempotency_key)` race recovery.

  The key idempotency assertion is:

  ```python
  first = create_turn(db, owner_id, payload)
  second = create_turn(db, owner_id, payload)
  assert second.job.id == first.job.id
  assert db.query(DesignImageJob).count() == 1
  ```

  Run: `cd backend; python -m pytest tests/test_design_image_service.py -q`

  Expected: FAIL because service functions are missing.

- [x] **Step 2: Implement transactional turn creation**

  One transaction performs: read existing idempotency row; lock `ark_users`; validate ownership and quota; create/resolve session; create user message; attach drafts in input order; create queued job. On unique-key race, rollback the whole transaction and re-read by owner + idempotency key.

  Cross-user resources raise the same not-found domain exception as absent resources. Do not add an implicit “latest image” fallback.

- [x] **Step 3: Implement config/detail/usage projections**

  `/config` projection returns verified size/quality choices, max four attachments, effective daily quota and remaining quota. `/usage` derives counts, success rate, P50/P95 duration, tokens, error categories and estimated cost from jobs; it does not create a second aggregate truth table.

- [x] **Step 4: Verify and commit**

  Run: `cd backend; python -m pytest tests/test_design_image_service.py -q`

  Then:

  ```powershell
  git add backend/app/design_image/schemas.py backend/app/design_image/service.py backend/tests/test_design_image_service.py
  git commit -m "feat(ai): add design image sessions and quota"
  ```

## Task 5: Phase 3 leased worker and stale recovery

**Files:**
- Create: `backend/app/design_image/worker.py`
- Modify: `backend/app/schedulers/registry.py`
- Create: `backend/tests/test_design_image_worker.py`
- Modify: `backend/tests/test_scheduler_jobs.py`

- [x] **Step 1: Write failing worker concurrency tests**

  Cover atomic conditional claim, unique lease token, claim count, provider attempt count, generate/edit image ordering, success only after durable output storage, actionable error mapping, and scheduled draft cleanup. Simulate two workers and prove only one calls the Provider.

  Add a late-response test: expire lease, recover stale job, let the old worker finish, and assert it cannot write output asset/message or move status away from failed.

  Run: `cd backend; python -m pytest tests/test_design_image_worker.py tests/test_scheduler_jobs.py -q`

  Expected: FAIL because the worker/jobs are absent.

- [x] **Step 2: Implement claim, execute and conditional finalize**

  Public entry points:

  ```python
  claim_next_job(db, worker_id: str, lease_seconds: int) -> ClaimedJob | None
  execute_claimed_job(job_id: int, lease_token: str) -> None
  recover_stale_jobs(db, stale_before: datetime) -> int
  cleanup_expired_drafts(db, now: datetime) -> int
  process_design_image_queue() -> None
  ```

  The success/failure UPDATE must include both `status='running'` and the current `lease_token`. A losing/late worker may record an orphan warning but cannot publish files to an asset row; clean its temporary output only.

- [x] **Step 3: Register a bounded scheduler wake-up**

  Add one interval job with `max_instances=1`, `coalesce=True`; inside it, open `SessionLocal()` and process at most configured concurrency per wake-up. The worker exists only on the Phase 0 frozen office primary instance where `SCHEDULER_ENABLED=true` and private storage is local.

- [x] **Step 4: Verify and commit**

  Run: `cd backend; python -m pytest tests/test_design_image_worker.py tests/test_scheduler_jobs.py -q`

  Then:

  ```powershell
  git add backend/app/design_image/worker.py backend/app/schedulers/registry.py backend/tests/test_design_image_worker.py backend/tests/test_scheduler_jobs.py
  git commit -m "feat(ai): add recoverable design image worker"
  ```

## Task 6: Phase 3 API contract and authorization

**Files:**
- Create: `backend/app/design_image/router.py`
- Modify: `backend/app/routers.py`
- Create: `backend/tests/test_design_image_api.py`

- [x] **Step 1: Write failing endpoint tests**

  Cover every spec §7 endpoint with 401/403/404/422 and success cases. Each route must expose `Depends(require_permission(...))`, use `get_db`, return `ok()` envelopes, and preserve HTTP 202 with envelope `code=200` for turn creation. Asset content tests must assert same 404 for absent and cross-owner IDs and safe `Content-Disposition` for downloads. JSON success endpoints use `ok()`; the binary streaming endpoint is the documented exception and must not be wrapped in JSON. The service opens the authorized private file before the response is created so concurrent cleanup cannot turn a missing file into a 500. Existing framework error envelopes remain unchanged to avoid expanding scope into a global exception-handler rewrite.

  Run: `cd backend; python -m pytest tests/test_design_image_api.py -q`

  Expected: FAIL because the router is not registered.

- [x] **Step 2: Implement thin routes**

  Routes only parse schema/multipart inputs, call service/file service, translate domain errors and return responses. No Provider calls, business transitions, ownership query construction or direct `SessionLocal()` belong in `router.py`.

- [x] **Step 3: Register and verify API**

  Run:

  ```powershell
  cd backend
  python -m pytest tests/test_design_image_api.py tests/test_design_image_service.py tests/test_design_image_worker.py -q
  ```

  Then commit:

  ```powershell
  git add backend/app/design_image/router.py backend/app/routers.py backend/tests/test_design_image_api.py
  git commit -m "feat(ai): expose design image studio api"
  ```

## Task 7: Phase 4 frontend API and deterministic state

**Files:**
- Modify: `frontend/src/api/clients.js`
- Create: `frontend/src/api/designImage.js`
- Create: `frontend/src/views/design/image-studio/state.js`
- Create: `frontend/tests/designImageState.test.mjs`

- [ ] **Step 1: Write failing pure-state tests**

  Tests must cover monotonic status (`queued→running→succeeded/failed`, never backward), stale conversation generation guards, duplicate send/upload guards, concurrent attachment completion without loss, explicit base asset ID, restoring only active jobs, retry replacing active job ID while preserving history, and Object URL revocation registry.

  Run: `cd frontend; node --test tests/designImageState.test.mjs`

  Expected: FAIL because state helpers are absent.

- [ ] **Step 2: Implement pure transitions**

  Export small functions such as:

  ```javascript
  export function advanceJob(current, incoming) {}
  export function acceptConversationResponse(activeGeneration, responseGeneration) {}
  export function upsertAttachment(items, uploadId, patch) {}
  export function selectBaseAsset(asset) {}
  export function createObjectUrlRegistry(urlApi = URL) {}
  ```

  State helpers must not import Vue or axios, so Node tests execute without adding Vitest.

- [ ] **Step 3: Add the registered API module**

  Register the existing shared client in `clients.js`; do not call `axios.create()`. `getAssetBlob(id, download)` uses `responseType:'blob'`, and all long-task methods opt out of global loading/toast behavior as supported by the current client contract.

- [ ] **Step 4: Verify and commit**

  Run: `cd frontend; node --test tests/designImageState.test.mjs`

  Then:

  ```powershell
  git add frontend/src/api/clients.js frontend/src/api/designImage.js frontend/src/views/design/image-studio/state.js frontend/tests/designImageState.test.mjs
  git commit -m "feat(ai): add design image frontend state"
  ```

## Task 8: Phase 4 GPT-like workbench UI

**Files:**
- Modify: `frontend/src/config/navigation.js`
- Create: `frontend/src/views/design/image-studio/ImageStudio.vue`
- Create: `frontend/src/views/design/image-studio/composables/useImageStudio.js`
- Create: `frontend/src/views/design/image-studio/composables/useJobPolling.js`
- Create: `frontend/src/views/design/image-studio/composables/useAssetObjectUrls.js`
- Create: `frontend/src/views/design/image-studio/components/ConversationSidebar.vue`
- Create: `frontend/src/views/design/image-studio/components/MessageThread.vue`
- Create: `frontend/src/views/design/image-studio/components/PromptComposer.vue`
- Create: `frontend/src/views/design/image-studio/components/GenerationCard.vue`
- Create: `frontend/src/views/design/image-studio/components/ImageLightbox.vue`

- [ ] **Step 1: Add a failing navigation/static contract test**

  Extend the Node test to assert `/design/image-studio`, `design_image:read`, lazy view import, no naked hex in new files, no `transition: all`, no `ease-in`, no `.glass-card`, no unguarded `setInterval`, and `prefers-reduced-motion` handling.

  Run: `cd frontend; node --test tests/designImageState.test.mjs`

  Expected: FAIL because navigation/view files do not exist.

- [ ] **Step 2: Implement the thin page and composable**

  `ImageStudio.vue` owns layout only. `useImageStudio.js` owns sessions, drafts, active-job registry and submit/retry/download. `useJobPolling.js` combines recursive `setTimeout` with busy + generation + session/job snapshot guards; `useAssetObjectUrls.js` owns batch tokens and centralized revoke. It resumes `/jobs/active` on mount and releases every URL/timer on conversation change and unmount.

- [ ] **Step 3: Implement task-focused components**

  Required user-visible behavior: one-click new conversation, recent sessions, message thread, 1–4 uploaded references through `AppUpload show-list=false`, explicit “基于这张图修改” chip, size selector, quota, queued/running/succeeded/failed cards, actionable failure text, authenticated image/lightbox/download and AI text accuracy warning.

  Use `GlassButton`, `--dash-*`/global tokens and `.lg-*` material classes. No large-list backdrop filter or animated aurora. Main page and every component remain under 500 lines.

- [ ] **Step 4: Implement restrained motion**

  Only these motions are allowed:

  ```css
  /* press feedback */
  transform: scale(0.97);
  transition: transform 140ms cubic-bezier(0.23, 1, 0.32, 1);

  /* result state indication */
  opacity: 0;
  transform: scale(0.97);
  /* enter at 180ms using the same strong ease-out */
  ```

  Do not animate high-frequency session/message changes. Hover movement must be gated by `(hover: hover) and (pointer: fine)`. Reduced motion keeps opacity/color but removes translation/scale movement.

- [ ] **Step 5: Verify build and responsive behavior**

  Run:

  ```powershell
  cd frontend
  node --test tests/designImageState.test.mjs
  npm run build
  ```

  Manually verify 1366px, 1440px and narrow layout: conversation drawer has a visible trigger, closes on selection, only message pane scrolls, composer stays visible, keyboard-safe padding exists, and no dual scroll.

- [ ] **Step 6: Run motion review and commit**

  Review every new or modified transition against `review-animations`; findings use the required Before/After/Why table and must be fixed before approval. Do not expand this feature review into unrelated historical motion debt in shared `GlassButton` or `MainLayout` unless this task edits those lines.

  Then:

  ```powershell
  git add frontend/src/config/navigation.js frontend/src/views/design/image-studio
  git commit -m "feat(ai): build design image studio workbench"
  ```

## Task 9: Phase 5 operations, documentation and pilot controls

**Files:**
- Modify: `docs/api-reference.md`
- Modify: `docs/database.md`
- Modify: `docs/architecture.md`
- Modify: `docs/module-notes.md`
- Modify: `docs/runbook.md`
- Modify: `docs/requirements/2026-08-05-design-image-studio.md`
- Create: `docs/requirements/evidence/<date>-design-image-phase5-pilot.json`
- Create or modify: the applicable auto-memory project note if the repository provides that mechanism

- [ ] **Step 1: Document exact deployed contracts**

  Add all endpoints, tables/indexes/FKs, facade/worker flow, Provider capability/error observations, office-primary topology, storage permissions, environment settings, scheduler job IDs, quota semantics, log correlations, alert thresholds, rollback procedure and orphan-file recovery.

- [ ] **Step 2: Configure pilot without broad role assignment**

  Confirm effective Settings: daily limit 20, worker concurrency 3, lease 420s, stale 480s (or a value proven greater than actual timeout + download + buffer). Assign `design_image:read/write` only to a dedicated pilot role containing 2–3 named design users; do not grant `admin` unless required. Record IDs/names but no personal contact data or credentials.

- [ ] **Step 3: Run a real low-quality continuity smoke test**

  Through the business API and worker, perform one first generation then three edits, always selecting the previous result explicitly. Record sanitized request IDs, job IDs, AiCallLog IDs, asset IDs, durations and usage. Do not retain base64 or Provider keys in evidence.

- [ ] **Step 4: Reconcile evidence**

  Prove for all four calls that job status, output file metadata, AiCallLog usage and job token snapshots agree. Verify a second user receives the same 404 for the asset content route as an absent asset. Verify refresh/session switch restores the active job and does not leak Object URLs.

- [ ] **Step 5: Run complete verification**

  ```powershell
  python scripts/check_conventions.py --base (git merge-base main HEAD)
  cd backend; python -m pytest
  cd ..\frontend; node --test tests/designImageState.test.mjs
  npm run build
  cd ..; python scripts/git_sweep.py
  ```

  Also run `git diff --check`, secret/base64 scans, `alembic heads`, and a requirement-by-requirement audit of spec §17. Evidence must cover the full scope rather than extrapolating from targeted tests.

- [ ] **Step 6: Final adversarial review and Phase 5 commit**

  A fresh reviewer checks ownership, concurrent writes, idempotency, lease races, stale/late workers, migration correctness, frontend/backend contract, private file boundaries, billing uncertainty and motion accessibility. Fix every material finding and re-run the relevant full verification.

  Then:

  ```powershell
  git add docs
  git commit -m "docs(ai): finalize design image studio rollout"
  ```

## Completion audit

Phase 5 is complete only when every unchecked item in spec §17 has direct evidence. In particular, passing unit tests alone does not prove the four-call real Provider chain, office-primary storage topology, pilot role assignment, responsive/manual UI behavior or usage reconciliation. Do not mark the goal complete or offer branch integration until those external and manual gates have been run and recorded.
