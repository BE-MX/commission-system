# Domestic Conditional Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-unit conditional routing and audited step skipping to domestic reporting so split quantities can follow different processing, repair, and optional-finishing paths without fake labor reports.

**Architecture:** Keep the shared process route linear and attach domestic-only step rules keyed by route and process. Store actual work in existing report logs, store result allocation on report-unit mappings, and store skipped work in separate audited skip logs. Compute downstream eligibility from concrete unit identity sets (`reported ∪ skipped`) while preserving actual report quantities as the sole workload source.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic/MySQL, pytest/SQLite, Vue 3 + Element Plus, WeChat Mini Program JavaScript, Kotlin Android/PDA, JUnit 4.

---

## File Structure

- Create `backend/alembic/versions/127_domestic_route_rules.py`: schema for route rules, report outcomes, and skip audit tables.
- Modify `backend/app/domestic/models.py`: ORM models for route rules and skip logs/units; outcome columns on report mappings.
- Create `backend/app/domestic/route_rule_service.py`: rule validation, bulk save, serialization, and route-step metadata.
- Create `backend/app/domestic/routing_service.py`: unit-set eligibility, outcome allocation, skip creation, optional bypass, and downstream guards.
- Modify `backend/app/domestic/progress_service.py`: build progress from reported/skipped unit sets and complete items by effective passage.
- Modify `backend/app/domestic/unit_service.py`: delegate eligibility and exact-unit checks to routing state.
- Modify `backend/app/domestic/report_service.py`: accept outcomes, create automatic skips, replay exact results, and revoke safely across skipped steps.
- Modify `backend/app/domestic/schemas.py`: report outcome and manual-skip request contracts.
- Modify `backend/app/domestic/router.py`: route-rule and supervisor-skip endpoints; web reporting outcomes.
- Modify `backend/app/mini/router.py`: mini/PDA submission outcomes.
- Modify `backend/app/production/route_service.py`: remove orphaned domestic rules when steps are removed and expose validation errors without changing external reporting.
- Modify `backend/app/production/schemas.py`: route-step domestic rule response shape where needed by management UI.
- Create `backend/scripts/domestic_route_cutover.py`: read-only preflight by default and explicit reviewed cutover mode.
- Create `backend/tests/test_domestic_conditional_routing.py`: state-machine, concurrency, idempotency, revoke, and cutover regression tests.
- Create `backend/tests/test_domestic_route_cutover.py`: isolated preflight/token/reconciliation/atomicity tests without duplicating the state-machine factory.
- Modify `backend/tests/test_domestic_reporting.py`: existing linear-route assertions remain valid with no rules.
- Modify `backend/tests/test_domestic_optimizations.py`: exact-unit optional bypass and workload assertions.
- Modify `frontend/src/api/domestic.js`: route-rule and skip API functions.
- Modify `frontend/src/views/production/ProcessRouteManage.vue`: configure and preview domestic rule types/outcomes.
- Modify `frontend/src/views/domestic/DomesticOrders.vue`: web proxy-report outcome allocation and skipped progress display.
- Modify `frontend/src/views/domestic/composables/useDomesticOrders.js`: outcome payload and manual-skip orchestration.
- Modify `miniprogram/components/domestic-sheet/*`: decision quantities/radios and skipped progress.
- Modify `miniprogram/pages/domestic/scan/scan.js`: submit outcome allocation.
- Modify `miniprogram/pages/domestic/orders/*`, `miniprogram/pages/domestic/lookup/*`, `miniprogram/pages/domestic/track/*`: display effective progress without counting skip as labor.
- Modify `pda-reporting/app/src/main/java/com/leshine/pdareporting/ApiClient.kt`: submit outcome maps.
- Create `pda-reporting/app/src/main/java/com/leshine/pdareporting/DecisionReportFlow.kt`: pure decision validation and payload model.
- Create `pda-reporting/app/src/test/java/com/leshine/pdareporting/DecisionReportFlowTest.kt`: unit and quantity decision tests.
- Modify `pda-reporting/app/src/main/java/com/leshine/pdareporting/UnitReportFlow.kt`: prevent auto-submit when an outcome is required.
- Modify `pda-reporting/app/src/main/java/com/leshine/pdareporting/ReportingScreen.kt`: render decision inputs for quantity and unit modes.
- Modify `pda-reporting/app/src/main/java/com/leshine/pdareporting/MainActivity.kt`: route decision scans through confirmation and persist outcome payloads for retry.
- Modify `pda-reporting/app/src/main/java/com/leshine/pdareporting/PendingSubmissionStore.kt`: persist/replay outcomes with the same idempotency key.
- Modify `docs/database.md`, `docs/api-reference.md`, and `docs/handoff.md`: document the final schema, API, rollout status, and remaining live cutover gate.

### Task 1: Define schema and route-rule contract

**Files:**
- Create: `backend/alembic/versions/127_domestic_route_rules.py`
- Modify: `backend/app/domestic/models.py`
- Create: `backend/app/domestic/route_rule_service.py`
- Modify: `backend/app/domestic/schemas.py`
- Modify: `backend/app/domestic/router.py`
- Test: `backend/tests/test_domestic_conditional_routing.py`

- [ ] **Step 1: Verify the global Alembic head before creating the migration**

Run:

```powershell
git log --all --oneline -- backend/alembic/versions/
& 'D:\MyProgram\commission-system\backend\.venv\Scripts\python.exe' -m alembic heads
```

Expected: one head. At plan creation it was `125_invoice_integration`; revision 126 was reserved by parallel work, so this branch selected 127. The committed migration currently revises 125 because 126 is not present in this branch. If the parallel 126 migration is merged first, re-chain `127_domestic_route_rules.down_revision` to that actual 126 revision and re-run `alembic heads/history` before integration; never ship two heads.

- [ ] **Step 2: Write failing route-rule tests**

Create fixtures with a six-step route and assert these contracts:

```python
def test_route_rule_rejects_skip_target_before_trigger(db, conditional_route):
    with pytest.raises(ValueError, match="必须位于触发工序之后"):
        route_rule_service.save_rules(db, conditional_route.id, [{
            "process_id": conditional_route.process_ids[3],
            "rule_type": "decision",
            "config": {"options": [{
                "code": "bad", "label": "错误", "skip_process_ids": [conditional_route.process_ids[1]],
            }]},
        }])


def test_route_rules_roundtrip_decision_and_optional(db, conditional_route):
    saved = route_rule_service.save_rules(db, conditional_route.id, [
        {
            "process_id": conditional_route.process_ids[1],
            "rule_type": "decision",
            "config": {"options": [
                {"code": "left", "label": "左线", "skip_process_ids": [conditional_route.process_ids[3]]},
                {"code": "right", "label": "右线", "skip_process_ids": [conditional_route.process_ids[2]]},
            ]},
        },
        {"process_id": conditional_route.process_ids[4], "rule_type": "optional", "config": None},
    ])
    assert saved[0]["rule_type"] == "decision"
    assert saved[1]["rule_type"] == "optional"
```

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```powershell
& 'D:\MyProgram\commission-system\backend\.venv\Scripts\python.exe' -m pytest tests/test_domestic_conditional_routing.py -q
```

Expected: import/attribute failure because route-rule models and service do not exist.

- [ ] **Step 4: Add the migration and ORM models**

Migration `127_domestic_route_rules` must:

```python
revision = "127_domestic_route_rules"
down_revision = "125_invoice_integration"
```

Add nullable `outcome_json JSON` to `ark_domestic_report_logs` and nullable `outcome_code VARCHAR(32)` to `ark_domestic_report_units`.

Create:

```text
ark_domestic_route_rules
  id, route_id, process_id, rule_type, config_json, created_at, updated_at
  UNIQUE(route_id, process_id)

ark_domestic_skip_logs
  id, item_id, progress_id, skip_qty, source, reason, trigger_report_log_id,
  request_id, created_by_user_id, created_at, revoked, revoked_at
  UNIQUE(request_id)

ark_domestic_skip_units
  id, skip_log_id, unit_id, progress_id, created_at
  UNIQUE(skip_log_id, unit_id)
```

Use exact FK types, `ondelete="CASCADE"` for route/skip-unit ownership, `RESTRICT` for process/unit audit references, and Beijing-time ORM defaults. Do not update route names or mappings in this schema migration.

- [ ] **Step 5: Implement strict route-rule validation**

Expose:

```python
RULE_REQUIRED = "required"
RULE_DECISION = "decision"
RULE_OPTIONAL = "optional"

def list_rules(db: Session, route_id: int) -> list[dict]: ...
def rule_map(db: Session, route_id: int) -> dict[int, dict]: ...
def save_rules(db: Session, route_id: int, rules: list[dict]) -> list[dict]: ...
def validate_rules(db: Session, route_id: int, rules: list[dict]) -> None: ...
```

Validation must reject duplicate process rules, unknown/disabled routes, processes outside the route, unsupported types, empty or duplicate decision codes, empty labels, targets outside the route, targets at/before the trigger, and decision rules with fewer than two options. `optional` must have no options.

- [ ] **Step 6: Add rule APIs**

Add domestic-admin endpoints:

```text
GET /api/domestic/process-routes/{route_id}/rules
PUT /api/domestic/process-routes/{route_id}/rules
```

Use Pydantic models with `Literal["decision", "optional"]`, option codes matching `^[a-z][a-z0-9_]{0,31}$`, non-empty labels, and integer process IDs. Return rules keyed by `process_id` with resolved target process names for the UI.

- [ ] **Step 7: Run route-rule tests and migration import checks**

Run:

```powershell
& 'D:\MyProgram\commission-system\backend\.venv\Scripts\python.exe' -m pytest tests/test_domestic_conditional_routing.py -q
& 'D:\MyProgram\commission-system\backend\.venv\Scripts\python.exe' -m alembic heads
```

Expected: route-rule tests pass and exactly one head is reported.

- [ ] **Step 8: Commit schema and rule contract**

```powershell
git add backend/alembic/versions/127_domestic_route_rules.py backend/app/domestic/models.py backend/app/domestic/route_rule_service.py backend/app/domestic/schemas.py backend/app/domestic/router.py backend/tests/test_domestic_conditional_routing.py
git commit -m "feat(domestic): define conditional route rules"
```

### Task 2: Build the per-unit passage engine

**Files:**
- Create: `backend/app/domestic/routing_service.py`
- Modify: `backend/app/domestic/progress_service.py`
- Modify: `backend/app/domestic/unit_service.py`
- Modify: `backend/app/domestic/report_service.py`
- Modify: `backend/app/domestic/schemas.py`
- Modify: `backend/app/mini/router.py`
- Modify: `backend/app/domestic/router.py`
- Test: `backend/tests/test_domestic_conditional_routing.py`

- [ ] **Step 1: Write failing split-route tests**

Add tests that submit 20 units at “发加工点” with `outcomes={"dandong": 12, "lixiaohong": 8}` and assert:

```python
assert dispatch["outcomes"] == {"dandong": 12, "lixiaohong": 8}
assert steps[DANDONG_RECEIVE]["reportable_qty"] == 12
assert steps[LI_HANDHOOK]["reportable_qty"] == 8
assert steps[DANDONG_RECEIVE]["skipped_qty"] == 8
assert steps[LI_HANDHOOK]["skipped_qty"] == 12
assert workload_qty(db, dispatch_worker.id, dispatch_process.id) == 20
```

Add exact-unit assertions proving the 12 and 8 sets are disjoint and cover all20 units.

- [ ] **Step 2: Run the split-route test and verify RED**

Expected: `submit_report()` rejects the new `outcomes` argument or progress has no `skipped_qty`.

- [ ] **Step 3: Implement unit passage snapshots**

Create `routing_service.load_passage_state(db, item)` returning:

```python
@dataclass(frozen=True)
class PassageState:
    reported_by_progress: dict[int, set[int]]
    skipped_by_progress: dict[int, set[int]]

    def passed(self, progress_id: int) -> set[int]:
        return self.reported_by_progress.get(progress_id, set()) | self.skipped_by_progress.get(progress_id, set())
```

Load all effective report units and skip units for one item in two bulk queries. Add `eligible_unit_ids(item, progress, rows, state)` using all active item units for step1 and the immediately previous progress `passed` set for later steps.

- [ ] **Step 4: Add outcome allocation and automatic skips**

Extend `submit_report(..., outcomes: dict[str, int] | None = None)`.

- Normal/optional steps reject non-empty outcomes.
- Decision steps require outcomes and `sum(outcomes.values()) == qty`.
- Codes must exactly match configured options and zero values are removed.
- Quantity mode assigns selected units in stable unit-number order across the option order in rule config.
- Unit mode requires exactly one code with quantity1.
- Store the normalized mapping in `DomesticReportLog.outcome_json` and each unit code in `DomesticReportUnit.outcome_code`.
- For every configured target process, create one skip log and mappings for the units assigned to that outcome.

- [ ] **Step 5: Rebuild progress views from concrete identities**

`build_progress_view` must return:

```python
{
    "completed_qty": len(reported),
    "skipped_qty": len(skipped - reported),
    "passed_qty": len(reported | skipped),
    "required_qty": max(0, len(upstream_passed) - len(skipped)),
    "reportable_qty": len(upstream_passed - reported - skipped),
    "rule_type": rule_type,
    "outcome_options": public_option_list,
}
```

Keep `DomesticItemProgress.completed_qty` as the cached actual-work total and sync `status` from passage count. Recalculate item/order completion using the last step’s `passed_qty`.

- [ ] **Step 6: Add optional predecessor bypass**

Before reporting a step whose immediate predecessor is `optional`, select units in this order:

1. units that already passed the optional step;
2. units eligible for the optional step but not processed.

For group2, create an `optional_bypass` skip log tied to the new downstream report log. In unit mode this applies only to the scanned unit. Reject a unit that has not passed the step before the optional process.

- [ ] **Step 7: Update API contracts and idempotent replay**

Add optional `outcomes: dict[str, int]` to web and mini submit models. Replays must compare item, progress, quantity, worker, unit, mode, and normalized outcomes; a reused request ID with different outcomes returns the existing “请求号已用于另一笔报工” error. Replay responses include outcomes and unit codes.

- [ ] **Step 8: Run the focused and legacy suites**

Run:

```powershell
& 'D:\MyProgram\commission-system\backend\.venv\Scripts\python.exe' -m pytest tests/test_domestic_conditional_routing.py tests/test_domestic_reporting.py tests/test_domestic_optimizations.py -q
```

Expected: all new split-route tests and the previous67 domestic tests pass. Routes without rules retain strict linear behavior.

- [ ] **Step 9: Commit the passage engine**

```powershell
git add backend/app/domestic/routing_service.py backend/app/domestic/progress_service.py backend/app/domestic/unit_service.py backend/app/domestic/report_service.py backend/app/domestic/schemas.py backend/app/domestic/router.py backend/app/mini/router.py backend/tests/test_domestic_conditional_routing.py backend/tests/test_domestic_reporting.py backend/tests/test_domestic_optimizations.py
git commit -m "feat(domestic): route units through conditional steps"
```

### Task 3: Make reversal and supervisor exceptions auditable

**Files:**
- Modify: `backend/app/domestic/routing_service.py`
- Modify: `backend/app/domestic/report_service.py`
- Modify: `backend/app/domestic/schemas.py`
- Modify: `backend/app/domestic/router.py`
- Test: `backend/tests/test_domestic_conditional_routing.py`

- [ ] **Step 1: Write failing revoke tests**

Cover:

```python
def test_revoke_decision_removes_its_skips_before_downstream(db, conditional_order): ...
def test_revoke_decision_lists_downstream_units_and_process(db, conditional_order): ...
def test_revoke_intake_removes_optional_bypass(db, conditional_order): ...
def test_manual_skip_requires_admin_reason_and_excludes_workload(db, conditional_order): ...
def test_manual_skip_revoke_blocked_after_downstream(db, conditional_order): ...
```

The blocked message must contain at least one display code and the earliest downstream process name.

- [ ] **Step 2: Replace immediate-neighbor revoke guards with exact downstream search**

For every unit mapped to the report/skip log, search active report units on all progress rows with greater `step_order`. Auto-generated skip rows do not block their trigger’s revoke; actual downstream work does. Revoke trigger-generated skips in the same transaction as the report log.

- [ ] **Step 3: Add manual skip and restore endpoints**

Add `domestic:admin` endpoints:

```text
POST /api/domestic/reports/skip
POST /api/domestic/reports/skip/{skip_log_id}/revoke
```

Create a manual skip only from currently eligible units, require a stripped reason of5–500 characters, accept quantity mode or exact `unit_id`, and require a stable `request_id`. Revoke only when no downstream actual work exists.

- [ ] **Step 4: Verify concurrency and idempotency**

Use two SQLAlchemy sessions over the shared SQLite test engine to prove same-item serialization prevents double allocation. Add request replay tests for decision and manual skip payloads. MySQL locking behavior stays anchored by the existing item-row-first lock order.

- [ ] **Step 5: Run tests and commit**

Run the three domestic suites from Task2, then:

```powershell
git add backend/app/domestic/routing_service.py backend/app/domestic/report_service.py backend/app/domestic/schemas.py backend/app/domestic/router.py backend/tests/test_domestic_conditional_routing.py
git commit -m "feat(domestic): audit skip and route reversals"
```

### Task 4: Configure rules and report outcomes in the web UI

**Files:**
- Modify: `frontend/src/api/domestic.js`
- Modify: `frontend/src/views/production/ProcessRouteManage.vue`
- Modify: `frontend/src/views/domestic/DomesticOrders.vue`
- Modify: `frontend/src/views/domestic/composables/useDomesticOrders.js`
- Add/Modify: focused frontend tests under `frontend/tests/`

- [ ] **Step 1: Write failing frontend contract tests**

Add pure tests for:

```js
normalizeOutcomeAllocation(options, { dandong: 12, lixiaohong: 8 }, 20)
// => { qty: 20, outcomes: { dandong: 12, lixiaohong: 8 } }

validateRouteRule({ rule_type: 'decision', options: [...] }, routeSteps)
// rejects target processes before the trigger
```

Expected initial result: imports fail because helpers do not exist.

- [ ] **Step 2: Add API functions**

```js
export const getDomesticRouteRules = routeId => domesticClient.get(`/process-routes/${routeId}/rules`)
export const saveDomesticRouteRules = (routeId, rules) => domesticClient.put(`/process-routes/${routeId}/rules`, { rules })
export const skipDomesticStep = data => domesticClient.post('/reports/skip', data)
export const revokeDomesticSkip = id => domesticClient.post(`/reports/skip/${id}/revoke`)
```

- [ ] **Step 3: Extend route management progressively**

For each route step show one selector: `必须扫描 / 分流判定 / 非阻塞可选`. A decision row expands inline with result label/code and checkboxes limited to later route steps. Provide fixed templates for the four confirmed business decisions, but save the same generic validated payload. Display a compact path summary such as “丹东 → 跳过 李晓宏手钩、李晓宏递针”.

Save route steps first, then save rules only after the step request succeeds. Reload both responses and keep unsaved-change protection covering rule edits.

- [ ] **Step 4: Extend web proxy reporting**

When `step.rule_type === 'decision'`, replace the single quantity input with one quantity input per option. Submit `qty=sum` and `outcomes` together. For normal/optional steps retain the existing single quantity input. Show progress as `已报 N / 应做 M`, with `自动跳过 K` secondary text; skipped quantities must never be labeled completed work.

- [ ] **Step 5: Add supervisor exception UI**

Only users with `domestic:admin` see “异常跳过”. Require quantity and reason in a warning dialog; show that skipped quantities do not count wages. After success reload progress and logs. Restore uses the server’s downstream guard and displays its actionable error unchanged.

- [ ] **Step 6: Run frontend tests and production build**

Run:

```powershell
npm ci
npm test -- --run
npm run build
```

Expected: focused tests pass and Vite production build exits0.

- [ ] **Step 7: Commit web configuration and reporting**

```powershell
git add frontend/src/api/domestic.js frontend/src/views/production/ProcessRouteManage.vue frontend/src/views/domestic/DomesticOrders.vue frontend/src/views/domestic/composables/useDomesticOrders.js frontend/tests
git commit -m "feat(domestic-web): configure conditional reporting"
```

### Task 5: Implement the shared scan contract in Mini Program and PDA

**Files:**
- Modify: `miniprogram/components/domestic-sheet/domestic-sheet.js`
- Modify: `miniprogram/components/domestic-sheet/domestic-sheet.wxml`
- Modify: `miniprogram/components/domestic-sheet/domestic-sheet.wxss`
- Modify: `miniprogram/pages/domestic/scan/scan.js`
- Modify: `miniprogram/pages/domestic/orders/*`
- Modify: `miniprogram/pages/domestic/lookup/*`
- Modify: `miniprogram/pages/domestic/track/*`
- Modify: `pda-reporting/app/src/main/java/com/leshine/pdareporting/ApiClient.kt`
- Create: `pda-reporting/app/src/main/java/com/leshine/pdareporting/DecisionReportFlow.kt`
- Create: `pda-reporting/app/src/test/java/com/leshine/pdareporting/DecisionReportFlowTest.kt`
- Modify: `pda-reporting/app/src/main/java/com/leshine/pdareporting/UnitReportFlow.kt`
- Modify: `pda-reporting/app/src/main/java/com/leshine/pdareporting/ReportingScreen.kt`
- Modify: `pda-reporting/app/src/main/java/com/leshine/pdareporting/MainActivity.kt`
- Modify: `pda-reporting/app/src/main/java/com/leshine/pdareporting/PendingSubmissionStore.kt`

- [ ] **Step 1: Write failing pure PDA decision tests**

```kotlin
@Test fun decision_step_never_auto_submits_even_in_unit_mode() {
    assertFalse(UnitReportFlow.shouldAutoSubmit("unit", requiresOutcome = true))
}

@Test fun quantity_outcomes_must_sum_to_qty() {
    val result = DecisionReportFlow.validate(
        maxQty = 20,
        values = linkedMapOf("dandong" to 12, "lixiaohong" to 8),
    )
    assertEquals(20, result.qty)
}

@Test fun unit_decision_requires_exactly_one_option() { ... }
```

- [ ] **Step 2: Build Mini Program decision inputs**

`domestic-sheet` detects `nextStep.rule_type`. Decision quantity mode renders one numeric input per option, calculates a visible total, and emits `{qty, outcomes}`. Unit mode renders large single-choice buttons and emits `{qty:1, outcomes:{code:1}}`. Normal mode keeps the current quantity input. Do not add a general skip button.

- [ ] **Step 3: Submit Mini Program outcomes and show effective progress**

Pass `outcomes` to `/api/mini/domestic/scan/submit`. Update order, lookup, and track views to use `passed_qty` for route completion while displaying actual `completed_qty` and `skipped_qty` separately. Public customer tracking may label skip as “无需此工序” but must not expose worker or internal reason.

- [ ] **Step 4: Implement the PDA pure decision model and API payload**

`DecisionReportFlow` normalizes ordered JSON options and validates positive allocations. `ApiClient.submit` accepts `JSONObject? outcomes` and places it in the request. `PendingSubmissionStore` persists the serialized map so network-unknown retry resends the identical request ID and outcomes.

- [ ] **Step 5: Gate unit auto-submit and render decisions**

Change:

```kotlin
fun shouldAutoSubmit(reportMode: String, requiresOutcome: Boolean): Boolean =
    reportMode == "unit" && !requiresOutcome
```

`ReportingScreen` renders quantity allocations for decision quantity mode and large radio choices for unit mode. `MainActivity` only auto-submits unit scans without decision options; decision scans always wait for confirmation.

- [ ] **Step 6: Run Mini Program syntax checks and Android verification**

Run Node syntax checks over changed Mini Program JS files, then:

```powershell
.\gradlew.bat testDebugUnitTest lintDebug assembleDebug
```

Expected: all Android tests pass, lint has no new errors, and debug APK builds.

- [ ] **Step 7: Commit both scan clients**

```powershell
git add miniprogram/components/domestic-sheet miniprogram/pages/domestic pda-reporting/app/src/main pda-reporting/app/src/test
git commit -m "feat(domestic-scan): capture routing outcomes"
```

### Task 6: Cutover tooling, documentation, and final verification

> **2026-09-01 决策变更**：下列 token/reconciliation 方案是原始实施记录，已被最终业务口径取代，不再作为生产操作说明。现行切换按产品类型全量直接绑定：`cap → 头套网帽（递针）`、`piece → 发片网底（递针）`；两条路线使用相同条件规则，只更新工艺映射和已有产品，存量订单路线快照保持不变。实际命令以 `docs/api-reference.md` 为准。

**Files:**
- Create: `backend/scripts/domestic_route_cutover.py`
- Create: `backend/tests/test_domestic_route_cutover.py`
- Modify: `docs/database.md`
- Modify: `docs/api-reference.md`
- Modify: `docs/handoff.md`

- [ ] **Step 1: Write failing cutover-preflight tests**

Cover route discovery by exact configured name, refusal on ambiguous/missing routes, report-count grouping, product routes that will not follow mapping changes, and a dry-run result containing no writes. Do not identify live records by hard-coded numeric IDs.

- [ ] **Step 2: Implement read-only-by-default preflight**

The script must require `--target-route-name`, print:

- target route/rule validity and worker coverage;
- affected craft mappings and existing product routes;
- no-report items eligible for rebuild;
- reported items requiring explicit reconciliation;
- before-state totals for items, report logs, report units, completed quantities, and workload.

Any mutation requires both `--apply` and a generated preflight token. Do not switch mapping automatically from the Alembic migration.

Prefer repeatable `--craft-key product_type::craft` selectors. `--craft-name` is only a convenience for names that resolve to exactly one `(product_type, craft)` mapping; ambiguous, missing, duplicate, malformed, or overlapping selectors must fail before token generation.

- [ ] **Step 3: Implement explicit reviewed cutover**

Apply mode must first require proof that every domestic writer/background write task is stopped and in-flight write transactions are drained; row locks do not replace this gate. The CLI confirmation is the exact constant `--confirm-writes-stopped DOMESTIC_WRITES_STOPPED`. Only then may it update selected craft mappings and existing product route bindings in one transaction, rebuild only no-report items, and consume a reviewed JSON reconciliation file for reported items. Abort the entire transaction on any quantity, unit-identity, or workload mismatch. Print an after-state comparison and commit only when every invariant matches; restore new-version write traffic only after success is verified.

- [ ] **Step 4: Update documentation**

Document the three rule types, outcome payload, progress fields, skip APIs/tables, exact revoke semantics, client behavior, and live-cutover gate. `docs/handoff.md` must say code readiness separately from whether the production mapping has actually switched.

- [ ] **Step 5: Apply the schema migration in the required maintenance window**

Per `CLAUDE.md`, stop old write instances before applying the migration because old code does not understand conditional routing outcomes/skips. Run `alembic upgrade head`, verify one head, then start only the new version. Do not execute business cutover until application verification is complete.

This remains an operator maintenance-window step. It was deliberately not executed while preparing the code and cutover documentation.

- [ ] **Step 6: Run full verification**

Run:

```powershell
& 'D:\MyProgram\commission-system\backend\.venv\Scripts\python.exe' -m pytest -q
npm test -- --run
npm run build
.\gradlew.bat clean test lintDebug assembleDebug
python scripts/check_conventions.py --base (git merge-base main HEAD)
python scripts/git_sweep.py
```

Expected: all new tests pass; any known pre-existing baseline failures are listed separately with evidence. Confirm Alembic has one head and inspect `git diff --check`.

- [ ] **Step 7: Request independent adversarial review**

This change spans more than three files and changes a quantity state machine. Dispatch an independent reviewer to inspect branch/set conservation, concurrent allocation, idempotent replay, revoke ordering, workload exclusion, migration safety, three-client contract consistency, and unauthorized manual skips. Address every P0/P1 finding and rerun affected tests.

- [ ] **Step 8: Commit tooling and documentation**

```powershell
git add backend/scripts/domestic_route_cutover.py backend/tests/test_domestic_route_cutover.py docs/database.md docs/api-reference.md docs/handoff.md docs/superpowers/plans/2026-08-31-domestic-conditional-routing.md
git commit -m "docs(domestic): prepare conditional route cutover"
```

- [ ] **Step 9: Push the feature branch for backup**

```powershell
git push -u origin codex/domestic-conditional-routing
```

Do not merge or push `main`; only the main worktree owner may merge after review.
