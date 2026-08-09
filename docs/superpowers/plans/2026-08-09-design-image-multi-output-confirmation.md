# Design Image Multi-Output Confirmation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the internal image studio clarify ambiguous 2–4 image requests, then create either one composite job or up to four independently executable jobs without duplicate billing or duplicate confirmation.

**Architecture:** A deterministic backend parser classifies output intent without another AI call. Ambiguous turns persist a structured assistant interaction message and create no jobs; a dedicated idempotent action endpoint resolves that message under a row lock and atomically creates one or N jobs linked to the original user message. The existing message thread and active-job Map render and poll all jobs in the turn.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy 2, Alembic/MySQL, Vue 3 Composition API, Element Plus, Node test runner, pytest.

---

## File Responsibilities

- `backend/app/design_image/multi_output_intent.py`: pure deterministic number/mode/label parser and prompt suffix builder.
- `backend/app/design_image/models.py`: persisted `interaction_json` on messages.
- `backend/app/design_image/schemas.py`: turn/action request and union-like response contracts.
- `backend/app/design_image/service.py`: atomic turn classification, clarification persistence, batch capacity, resolution and idempotency.
- `backend/app/design_image/worker.py`: enforce the per-user running cap while multiple workers claim queued batch jobs.
- `backend/app/design_image/router.py`: thin serialization and action endpoint.
- `backend/alembic/versions/103_di_message_interact.py`: message interaction JSON migration with revision ID `103_di_message_interact`, re-chained after the customer portal migration landed at 102.
- `scripts/test_di_migration_mysql.ps1`: create, verify and always remove an isolated MySQL 8 container for the exact migration.
- `frontend/src/api/designImage.js`: resolve-action API method.
- `frontend/src/views/design/image-studio/components/OutputModeConfirmation.vue`: accessible inline confirmation card.
- `frontend/src/views/design/image-studio/components/MessageThread.vue`: render the structured interaction and emit action choices.
- `frontend/src/views/design/image-studio/composables/useImageStudio.js`: reconcile clarification or multiple jobs and handle resolution.
- `frontend/src/views/design/image-studio/state.js`: pure state helpers for multi-job send guards and interaction state.
- `backend/tests/test_design_image_worker.py`: multi-worker claim limits and independent same-message job outcomes.

### Task 1: Deterministic Multi-Output Intent Parser

**Files:**
- Create: `backend/app/design_image/multi_output_intent.py`
- Create: `backend/tests/test_design_image_multi_output_intent.py`

- [ ] **Step 1: Write failing parser tests**

Cover Arabic/Chinese counts, explicit composite/separate terms, ambiguous angle requests, named angles, standard labels, generic variants, false-positive protection and rejection above four:

```python
@pytest.mark.parametrize(
    ("prompt", "mode", "count", "labels"),
    [
        ("请生成3个角度的人像图", "clarify", 3, ("正面", "左侧 45°", "右侧 45°")),
        ("把正面侧面背面放在一张三视图里", "composite", 3, ("正面", "侧面", "背面")),
        ("分别生成三张：正面、左侧、右侧", "separate", 3, ("正面", "左侧", "右侧")),
        ("生成两个不同版本", "clarify", 2, ("独立变体 1/2", "独立变体 2/2")),
        ("生成1024×1024图片，参考图2", "single", 1, ()),
        ("生成5个角度", "reject", 5, ()),
    ],
)
def test_classify_multi_output_intent(prompt, mode, count, labels):
    intent = classify_multi_output_intent(prompt)
    assert (intent.mode, intent.count, intent.labels) == (mode, count, labels)
```

Also assert `build_output_prompt()` appends a locked angle/variant instruction without changing the original text, and `build_composite_prompt()` appends every resolved label plus an explicit same-canvas layout constraint.

Add explicit mismatch and false-positive cases: `分别生成3张：正面、背面` must become `clarify` with the standard three labels, while `人物年龄3岁`, `使用参考图2` and `尺寸1024×1024` must each remain `single` independently.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_design_image_multi_output_intent.py -q
```

Expected: collection fails because `app.design_image.multi_output_intent` does not exist.

- [ ] **Step 3: Implement the minimal pure parser**

Use immutable output and bounded regular expressions:

```python
@dataclass(frozen=True, slots=True)
class MultiOutputIntent:
    mode: Literal["single", "composite", "separate", "clarify", "reject"]
    count: int = 1
    labels: tuple[str, ...] = ()

STANDARD_ANGLES = {
    2: ("正面", "侧面 45°"),
    3: ("正面", "左侧 45°", "右侧 45°"),
    4: ("正面", "左侧 45°", "右侧 45°", "背面"),
}
```

Count detection must require nearby output nouns and exclude dimensions, ages, reference indices and color values. Do not call `app.ai.service.chat`.

- [ ] **Step 4: Run parser tests and existing service tests**

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_design_image_multi_output_intent.py tests/test_design_image_service.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/design_image/multi_output_intent.py backend/tests/test_design_image_multi_output_intent.py
git commit -m "feat(design-image): classify multi-output requests"
```

### Task 2: Persist Structured Clarification Messages

**Files:**
- Create: `backend/alembic/versions/103_di_message_interact.py`
- Create: `scripts/test_di_migration_mysql.ps1`
- Modify: `backend/app/design_image/models.py`
- Modify: `backend/app/design_image/schemas.py`
- Modify: `backend/app/design_image/router.py`
- Modify: `backend/tests/test_design_image_models.py`
- Create: `backend/tests/test_design_image_interactions_api.py`
- Modify: `docs/database.md`
- Modify: `docs/api-reference.md`

- [ ] **Step 1: Recheck the migration head across every branch**

```powershell
git log --all --oneline -- backend/alembic/versions/
cd backend
.\.venv\Scripts\python.exe -m alembic heads
```

Expected before creation: exactly one head. If another agent has already used `099`, choose the next available revision and update this plan's filename references in the implementation commit.

- [ ] **Step 2: Write failing model and serializer tests**

Assert the message table has `client_request_id` and `interaction_json`, old messages serialize interaction as `null`, the session/request pair is unique, and only public interaction keys are returned:

```python
def test_message_serializes_output_mode_confirmation():
    row = SimpleNamespace(
        id=7, role="assistant", content="请选择输出方式", status="normal",
        interaction_json={
            "type": "output_mode_confirmation", "status": "pending",
            "source_message_id": 6, "count": 3,
            "labels": ["正面", "左侧 45°", "右侧 45°"],
            "request": {"base_asset_id": None, "reference_asset_ids": [], "size": "1024x1024", "quality": "medium"},
            "selected_mode": None,
        },
        created_at=datetime(2026, 8, 9),
    )
    body = serialize_message(row)
    assert body["interaction"]["type"] == "output_mode_confirmation"
    assert "prompt_snapshot" not in json.dumps(body)
```

- [ ] **Step 3: Run tests and verify RED**

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_design_image_models.py tests/test_design_image_interactions_api.py -q
```

Expected: failures for the missing column/schema/serializer.

- [ ] **Step 4: Add the model, migration and strict schemas**

Migration upgrade/downgrade:

```python
def upgrade() -> None:
    op.add_column("ark_design_image_messages", sa.Column("client_request_id", sa.String(64), nullable=True))
    op.add_column("ark_design_image_messages", sa.Column("interaction_json", sa.JSON(), nullable=True))
    op.create_unique_constraint(
        "uq_di_message_session_client_request",
        "ark_design_image_messages",
        ["session_id", "client_request_id"],
    )

def downgrade() -> None:
    op.drop_constraint("uq_di_message_session_client_request", "ark_design_image_messages", type_="unique")
    op.drop_column("ark_design_image_messages", "interaction_json")
    op.drop_column("ark_design_image_messages", "client_request_id")
```

Add strict request types:

```python
class MessageActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    action: Literal["choose_output_mode"]
    mode: Literal["composite", "separate"]
```

Serializer must expose `interaction_json` as `interaction` after validating its known type and fields; malformed stored JSON is omitted and logged, not returned raw.

- [ ] **Step 5: Verify migration SQL and focused tests**

```powershell
cd backend
.\.venv\Scripts\python.exe -m alembic heads
.\.venv\Scripts\python.exe -m alembic upgrade 102_customer_image_portal:103_di_message_interact --sql
.\.venv\Scripts\python.exe -m pytest tests/test_design_image_models.py tests/test_design_image_interactions_api.py -q
```

Expected: one head at `103_di_message_interact`, exact `102_customer_image_portal`→`103_di_message_interact` MySQL DDL renders without inspection errors, and all focused tests pass.

Create `scripts/test_di_migration_mysql.ps1` as an executable isolation gate. It must:

1. start `mysql:8.4` with a unique container name, a Docker-assigned localhost port, database `commission_migration_test`, and temporary non-production credentials;
2. poll `mysqladmin ping` until healthy with a bounded timeout;
3. set only the child Alembic process's `COMMISSION_DB_HOST/PORT/USER/PASSWORD/NAME`, upgrade the empty schema to `102_customer_image_portal`, then upgrade exactly to `103_di_message_interact`;
4. query `information_schema.columns` and `information_schema.table_constraints` and fail unless both columns and `uq_di_message_session_client_request` exist;
5. remove the verified unique container in a `finally` block on success or failure.

Run it from the repository root:

```powershell
.\scripts\test_di_migration_mysql.ps1
```

The script must refuse an explicitly supplied production host and never read deployment `.env` credentials.

- [ ] **Step 6: Document and commit**

Document the new message field, turn response modes and action endpoint. Then:

```powershell
git add backend/alembic/versions/103_di_message_interact.py backend/app/design_image/models.py backend/app/design_image/schemas.py backend/app/design_image/router.py backend/tests/test_design_image_models.py backend/tests/test_design_image_interactions_api.py scripts/test_di_migration_mysql.ps1 docs/database.md docs/api-reference.md docs/superpowers/plans/2026-08-09-design-image-multi-output-confirmation.md
git commit -m "feat(design-image): persist clarification interactions"
```

### Task 3: Create Clarifications and Resolve Atomic Multi-Job Turns

**Files:**
- Modify: `backend/app/design_image/service.py`
- Modify: `backend/app/design_image/worker.py`
- Modify: `backend/app/design_image/router.py`
- Modify: `backend/app/design_image/schemas.py`
- Modify: `backend/tests/test_design_image_service.py`
- Modify: `backend/tests/test_design_image_api.py`
- Modify: `backend/tests/test_design_image_worker.py`
- Create: `backend/tests/test_design_image_multi_job_turns.py`

- [ ] **Step 1: Write RED service tests for all turn outcomes**

Tests must use the real SQLite session and assert database rows:

```python
def test_ambiguous_turn_persists_messages_without_job_or_usage(db, owner, session):
    result = create_turn(db, owner.id, TurnCreate(
        request_id="ambiguous-1", session_id=session.id,
        prompt="请生成3个角度的人像图",
    ))
    assert result.mode == "clarification"
    assert result.jobs == []
    assert result.clarification.interaction_json["count"] == 3
    assert db.query(DesignImageJob).count() == 0

def test_explicit_separate_turn_creates_three_jobs_atomically(db, owner, session):
    result = create_turn(db, owner.id, TurnCreate(
        request_id="separate-1", session_id=session.id,
        prompt="分别生成3张：正面、左侧45度、右侧45度",
    ))
    keys = [job.idempotency_key for job in result.jobs]
    assert len(keys) == len(set(keys)) == 3
    assert all(len(key) == 64 for key in keys)
    assert all(job.request_message_id == result.message.id for job in result.jobs)
```

Add tests for explicit composite, >4 rejection with zero rows, full-batch daily capacity, clarification-time attachment binding, and idempotent retry of clarification/one-job/multi-job turns through `(session_id, client_request_id)`. Include a 64-character request ID and reuse the same request ID in two sessions to prove derived job keys remain fixed-width and owner-unique. Clarification assets must be tested in four states: bound draft cannot be manually deleted, abandoned draft remains eligible for expiry cleanup, successful action changes it to `attached` and clears `expires_at`, and an expired/missing attachment makes action fail atomically.

- [ ] **Step 2: Run the tests and verify RED**

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_design_image_multi_job_turns.py tests/test_design_image_service.py -q
```

Expected: failures because `TurnResult` is single-job and no clarification branch exists.

- [ ] **Step 3: Refactor job construction into one internal helper**

Create a helper that receives already-validated session/assets/preset snapshot and creates one job per label. Derive every job key as a fixed 64-character SHA-256 digest of `session_id:request_id:position`, append separate angle/variant suffixes through `build_output_prompt()`, and use `build_composite_prompt()` for one-canvas output:

```python
def _create_jobs_for_intent(..., intent: MultiOutputIntent) -> list[DesignImageJob]:
    labels = intent.labels if intent.mode == "separate" else (None,)
    return [
        _create_job(
            idempotency_key=_job_key(session.id, payload.request_id, index),
            prompt=(
                build_output_prompt(payload.prompt, label, index, len(labels))
                if label is not None
                else build_composite_prompt(payload.prompt, intent.labels)
            ),
            ...,
        )
        for index, label in enumerate(labels, start=1)
    ]
```

The clarification branch writes `message_id=user_message.id` while deliberately keeping `status=draft` and the original `expires_at`, without creating a job or consuming quota. `delete_draft_asset` rejects any draft with a non-null `message_id`; expiry cleanup continues to delete it. Successful job creation alone changes it to `attached` and clears `expires_at`. Every job reuses the same validated references, and session recovery never restores clarification-owned drafts to the composer.

- [ ] **Step 4: Implement clarification creation and batch capacity**

Replace the single job `TurnResult` with:

```python
@dataclass(frozen=True, slots=True)
class TurnResult:
    mode: Literal["jobs", "clarification"]
    session: DesignImageSession
    message: DesignImageMessage
    jobs: tuple[DesignImageJob, ...]
    clarification: DesignImageMessage | None = None
```

For multi-job batches and confirmation actions only, owner-locked capacity validation requires zero pre-existing queued/running jobs, verifies daily remaining capacity for the full batch, and then atomically enqueues 2–4 rows. Ordinary single-image turns retain the existing per-session active check and per-user active capacity. `DESIGN_IMAGE_MAX_ACTIVE_PER_USER` becomes the worker running limit for batches; later turns remain blocked while that multi-job batch is active.

- [ ] **Step 5: Write RED confirmation/idempotency/concurrency tests**

Cover pending → composite/separate, same request retry, different request after resolution (409/domain conflict), cross-owner 404, two-session race, prior active owner jobs, expired/missing bound draft assets and insufficient capacity. Compile MySQL SQL to prove the clarification and owner queries include `FOR UPDATE`, because SQLite cannot enforce row-lock blocking.

Add a partial-batch test: after a four-root-job request has three terminal jobs and one queued/running job, a normal turn in another session is still rejected because the active job's `request_message_id` has more than one root job (`retry_of_job_id IS NULL`); after the fourth becomes terminal, normal turn creation succeeds. Also prove a failed ordinary single job plus its active retry has only one root job and does not trigger global batch blocking. No new batch table or compatibility field is added.

- [ ] **Step 6: Implement `resolve_message_action` transaction**

The service must lock owner/session/message, validate the stored interaction through the Pydantic schema, compare the stored resolved action request ID, create the entire batch with fixed-width derived job keys, update interaction status/selection/resolved request ID/resolved timestamp, and commit once. An `IntegrityError` race reloads the winning rows; it must not create duplicate jobs.

- [ ] **Step 7: Enforce the running cap during worker claims**

Enforce the global lock order `owner → job`, matching HTTP service paths. Worker claim first performs a non-locking candidate-owner lookup, acquires that owner with `FOR UPDATE SKIP LOCKED`, recounts running rows, and only then locks/claims that owner's oldest queued job. If the owner is at `DESIGN_IMAGE_MAX_ACTIVE_PER_USER`, skip that owner and continue looking for eligible work. Add two-worker tests proving concurrent claims never exceed the per-user cap and another owner is not starved; add a worker-vs-HTTP concurrency test proving the shared lock order neither deadlocks nor admits excess work.

Add worker outcome tests with three jobs sharing one request message: two succeed and one fails, every job receives its own response message/output asset, and retrying the failed job changes only that job.

- [ ] **Step 8: Add the thin action route and unified mutation envelope**

```python
@router.post("/sessions/{session_id}/messages/{message_id}/actions")
def resolve_message_action(...):
    result = service.resolve_message_action(...)
    return ok(serialize_turn_result(result))
```

All endpoints retain `design_image:write`; owner mismatch remains 404.

Create, resolve and retry all return `mode`, `jobs` and optional `clarification`. Retry returns `mode=jobs` and `jobs=[retried_job]`; remove the old single `job` field and update its API tests in the same change.

- [ ] **Step 9: Add stable safe business errors**

Return structured codes for `multi_output_limit`, `daily_limit_exceeded` and `attachment_unavailable`, with only safe public metadata (`max_outputs` or `remaining`). Tests must prove unknown validation/storage details are not exposed.

- [ ] **Step 10: Run backend regressions**

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_design_image_multi_output_intent.py tests/test_design_image_interactions_api.py tests/test_design_image_multi_job_turns.py tests/test_design_image_service.py tests/test_design_image_api.py tests/test_design_image_worker.py -q
```

Expected: all pass with no new warnings.

- [ ] **Step 11: Commit**

```powershell
git add backend/app/design_image backend/tests/test_design_image_multi_job_turns.py backend/tests/test_design_image_service.py backend/tests/test_design_image_api.py backend/tests/test_design_image_worker.py
git commit -m "feat(design-image): resolve multi-output turns"
```

### Task 4: Render and Resolve the Inline Confirmation Card

Before editing UI code, the implementer must read the applicable `animation-vocabulary` and `emil-design-eng` skills and compare the proposed card with the repository `DESIGN.md`; any intentional deviation must be documented in the task handoff.

**Files:**
- Create: `frontend/src/views/design/image-studio/components/OutputModeConfirmation.vue`
- Modify: `frontend/src/views/design/image-studio/components/MessageThread.vue`
- Modify: `frontend/src/views/design/image-studio/ImageStudio.vue`
- Modify: `frontend/src/views/design/image-studio/composables/useImageStudio.js`
- Modify: `frontend/src/views/design/image-studio/state.js`
- Modify: `frontend/src/api/designImage.js`
- Create: `frontend/tests/design-image-multi-output.test.mjs`

- [ ] **Step 1: Write RED pure state and source-contract tests**

Test multi-job merge, send guard with any active job in the session, pending/resolved labels, response reconciliation, retry reconciliation, safe business-error rendering, clarification-owned attachment recovery, and required accessibility/source contracts:

```javascript
test('turn clarification starts no polling and keeps action available', () => {
  const state = reconcileTurnResult({ jobs: [], clarification: { id: 8, interaction: { status: 'pending' } } })
  assert.deepEqual(state.pollJobIds, [])
  assert.equal(state.clarification.id, 8)
})

test('all jobs in a turn are merged and polled', () => {
  const state = reconcileTurnResult({ jobs: [{ id: 1 }, { id: 2 }, { id: 3 }] })
  assert.deepEqual(state.pollJobIds, [1, 2, 3])
})
```

- [ ] **Step 2: Run tests and verify RED**

```powershell
cd frontend
node --test tests/design-image-multi-output.test.mjs
```

Expected: failures for missing helpers/component/API.

- [ ] **Step 3: Add the action API and pure reconciliation helpers**

```javascript
export function resolveMessageAction(sessionId, messageId, data) {
  return designImageClient.post(
    `/sessions/${sessionId}/messages/${messageId}/actions`, data, SILENT_REQUEST,
  )
}

export function reconcileTurnResult(result = {}) {
  const jobs = Array.isArray(result.jobs) ? result.jobs : []
  return { jobs, clarification: result.clarification ?? null, pollJobIds: jobs.map(job => job.id) }
}
```

Do not preserve the removed single `result.job` field.

- [ ] **Step 4: Build the accessible inline card**

`OutputModeConfirmation.vue` receives a message interaction and `submitting` state, emits `choose`, uses native `<button type="button">`, shows exact cost text and standard labels, and keeps the selected state visible after resolution. It must not use a modal or preselect a mode.

Motion rules:

```css
.output-mode-confirmation {
  animation: confirmation-enter 180ms cubic-bezier(0.23, 1, 0.32, 1) both;
}
@keyframes confirmation-enter {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}
@media (prefers-reduced-motion: reduce) {
  .output-mode-confirmation { animation: none; }
}
```

No `transition: all`, layout-property animation or ungated hover transform.

- [ ] **Step 5: Connect message thread and composable**

`MessageThread` renders the card for `message.interaction?.type === 'output_mode_confirmation'` and emits `{ message, mode }`. `useImageStudio` submits a fresh action request ID, locks only that card, merges the returned messages/jobs, starts polling every returned job, and reloads the session on 409.

`submit()` must handle both response modes and only clear the composer/draft assets once the backend accepted the turn. A clarification keeps those assets represented by the persisted message interaction, so local draft chips are cleared after success to prevent a duplicate submit.

Session recovery must exclude every asset already attached to a clarification source message from composer draft chips. The confirmation card continues to reference those persisted attachments, and draft deletion must not remove them.

`retry()` consumes the same unified result, merges `result.jobs[0]`, and starts polling it. `safeRequestMessage()` may expose backend messages only for the whitelist `multi_output_limit`, `daily_limit_exceeded`, and `attachment_unavailable`, including the safe `max_outputs`/`remaining` metadata; all other 400/422/429 responses remain generic.

- [ ] **Step 6: Run frontend tests and build**

```powershell
cd frontend
node --test tests/design-image-multi-output.test.mjs tests/designImageConcurrency.test.mjs tests/designImageInteraction.test.mjs tests/designImageState.test.mjs tests/designImageStudioRecovery.test.mjs
npm.cmd run build
```

Expected: tests and production build pass.

- [ ] **Step 7: Commit**

```powershell
git add frontend/src/api/designImage.js frontend/src/views/design/image-studio frontend/tests/design-image-multi-output.test.mjs
git commit -m "feat(design-image): confirm multi-output mode"
```

### Task 5: End-to-End Verification, Motion Review and Documentation

**Files:**
- Modify: `docs/api-reference.md`
- Modify: `docs/runbook.md`
- Modify: `docs/superpowers/specs/2026-08-09-design-image-multi-output-confirmation-design.md` only if implementation required an approved contract correction
- Test: backend and frontend suites above

- [ ] **Step 1: Run migration, convention and full focused regression gates**

```powershell
cd backend
.\.venv\Scripts\python.exe -m alembic heads
.\.venv\Scripts\python.exe -m alembic upgrade 102_customer_image_portal:103_di_message_interact --sql
..\scripts\test_di_migration_mysql.ps1
.\.venv\Scripts\python.exe -m pytest tests/test_ai_image_job_runtime.py tests/test_ai_image_retry.py tests/test_ai_image_service.py tests/test_design_image_api.py tests/test_design_image_api_permissions.py tests/test_design_image_files.py tests/test_design_image_interactions_api.py tests/test_design_image_library.py tests/test_design_image_models.py tests/test_design_image_multi_job_turns.py tests/test_design_image_multi_output_intent.py tests/test_design_image_orphan_recovery.py tests/test_design_image_permissions.py tests/test_design_image_provider_probe.py tests/test_design_image_service.py tests/test_design_image_worker.py -q
cd ..
.\backend\.venv\Scripts\python.exe scripts/check_conventions.py
git diff --check origin/codex/customer-image-portal-spec...HEAD
```

Expected: one Alembic head, exact migration SQL renders, all tests pass, and there is no new convention violation or whitespace error. Before production deployment, run the repository deployment migration against its isolated pre-production schema, inspect the resulting columns/constraint, and only then execute the normal production `alembic upgrade head` gate.

- [ ] **Step 2: Run frontend regression and build**

```powershell
cd frontend
node --test tests/design-image-multi-output.test.mjs tests/designImageConcurrency.test.mjs tests/designImageInteraction.test.mjs tests/designImageState.test.mjs tests/designImageStudioRecovery.test.mjs
npm.cmd run build
```

Expected: all tests and build pass.

The commands must report a non-zero test count; an exit code 0 with zero discovered tests is a failed gate.

- [ ] **Step 3: Review motion against the selected skills**

Use `review-animations` on the actual diff. Approval requires: justified one-time card entrance, <=200ms, transform/opacity only, no `transition: all`, hover gated to fine pointers, and reduced-motion removing translation.

- [ ] **Step 4: Real-browser desktop and mobile verification**

Run the worktree backend/frontend with isolated ports and use a real authenticated test account. Verify:

1. ambiguous 3-angle prompt creates only the confirmation;
2. composite creates one card/job;
3. separate creates three cards/jobs;
4. refresh restores pending/resolved state;
5. rapid double click creates one batch;
6. 390px mobile layout has no horizontal overflow and 44px minimum action targets.

Capture screenshots to `tmp/design-image-multi-output-qa/`; do not commit generated screenshots.

- [ ] **Step 5: Update runbook and commit verification docs**

Document deterministic phrases, maximum four outputs, one-job-per-image billing, and operational checks for a stuck clarification/batch. Then:

```powershell
git add docs/api-reference.md docs/database.md docs/runbook.md
git commit -m "docs(design-image): document multi-output turns"
```

- [ ] **Step 6: Run independent specification and quality reviews**

Specification review checks every section of `docs/superpowers/specs/2026-08-09-design-image-multi-output-confirmation-design.md`. Only after approval, code-quality review checks parser false positives, transaction races, quota/capacity, response minimization, Vue state recovery, accessibility and motion.

Any finding returns to the original implementer and the same reviewer re-reviews until approved.

---

## Continuation Into Customer Portal Completion

After this plan passes both reviews, resume `docs/superpowers/plans/2026-08-07-customer-image-portal.md` at Task 7 and execute Tasks 7–12 in order with the same per-task TDD → spec review → quality review gates. Do not treat the internal multi-output feature as completion of the customer portal objective.
