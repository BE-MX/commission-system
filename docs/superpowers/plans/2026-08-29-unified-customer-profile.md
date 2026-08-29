# Unified Customer Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the duplicated lead, research subject, customer profile, opportunity and radar records with one Ark-owned `customer_id` domain that is versioned, evidence-backed and safe for Agent use.

**Architecture:** Add a self-contained `app/customer/` domain as the only customer truth and expose one `/api/customer-hub` service boundary. Acquisition, public-pool research, Alibaba inquiries, OKKI projections, opportunities and radar all write through customer services; consumer Agents only call scoped read tools. The cutover is a deliberate destructive rebuild guarded by an inventory and suppression export, not a compatibility migration.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, MySQL 8, Pydantic 2, pytest, Vue 3, Element Plus and Vite 5.

---

## File map

- `backend/app/customer/models.py`: account, identity, source, fact, profile, interaction, governance and workflow ORM models.
- `backend/app/customer/contracts.py`: enum sets, JSON schema names, identity/source registries and transition rules.
- `backend/app/customer/schemas.py`: HTTP and research-ingest request contracts.
- `backend/app/customer/access.py`: customer scope and field-classification enforcement.
- `backend/app/customer/identity_service.py`: resolution-key arbitration, provisional account/contact creation and identity candidate handling.
- `backend/app/customer/fact_service.py`: source-record, fact, evidence-link, conflict and event ledger writes.
- `backend/app/customer/profile_service.py`: CAS profile compilation, Agent context and list/target projections.
- `backend/app/customer/workflow_service.py`: search, research, qualification, assignment, opportunity and action orchestration.
- `backend/app/customer/query_service.py`: customer list/detail and paged timeline reads.
- `backend/app/customer/agent_service.py`: scoped, budgeted, evidence-citing consumer Agent reads.
- `backend/app/customer/cutover_service.py`: exact reset inventory, Agent history closure and suppression import/export logic.
- `backend/app/customer/router.py`: human `/api/customer-hub` endpoints with permission dependencies and `ok()` envelopes.
- `backend/app/customer/agent_router.py`: research-Agent task endpoints; no consumer database access surface.
- `backend/alembic/versions/126_unified_customer_domain.py`: destructive schema rebuild with MySQL table and column comments.
- `backend/tests/test_customer_*.py`: focused domain, workflow, permissions, Agent and cutover tests.
- `frontend/src/api/customerHub.js`: API calls through `customerHubClient`.
- `frontend/src/views/customer_hub/`: profiles, acquisition tasks, research center, opportunity desk, radar and detail drawer.
- `.agents/skills/ark-*/SKILL.md`: updated Ark research/discovery contracts using `customer_id` and new endpoints.
- `docs/{database.md,api-reference.md,architecture.md,module-notes.md,runbook.md}`: implemented schema, API, flow and cutover operations.

## Task 1: Freeze the executable contracts

**Files:**
- Create: `backend/app/customer/__init__.py`
- Create: `backend/app/customer/contracts.py`
- Create: `backend/tests/test_customer_contracts.py`

- [ ] **Step 1: Write failing contract tests**

```python
from app.customer.contracts import (
    allowed_relationship_transition,
    identity_policy,
    validate_registered_fact,
)


def test_shared_domain_never_auto_matches_a_company():
    policy = identity_policy("public_web", "domain")
    assert policy.strength == "medium"
    assert policy.cardinality in {"one_to_many", "unknown"}
    assert policy.unique_slot is False


def test_relationship_transition_respects_order_recency():
    assert allowed_relationship_transition("developing", "active_customer", "valid_order", True)
    assert not allowed_relationship_transition("inactive", "active_customer", "historical_order_replay", False)


def test_unregistered_fact_is_rejected():
    assert validate_registered_fact("unknown.key", "public_web") == "restricted_internal"
```

- [ ] **Step 2: Run `cd backend; pytest tests/test_customer_contracts.py -q` and confirm import failure.**
- [ ] **Step 3: Implement frozen enum sets, identity/source policies, fact registry and relationship transition function exactly from design sections 5, 8, 9 and 15.**
- [ ] **Step 4: Run the contract tests and confirm all pass.**
- [ ] **Step 5: Commit `feat: define customer domain contracts`.**

## Task 2: Define the unified ORM and comment invariant

**Files:**
- Create: `backend/app/customer/models.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/tests/test_customer_models.py`

- [ ] **Step 1: Write failing metadata tests** that import the 31 core tables and seven workflow tables listed in the approved design, assert every table has `comment`, every column has `comment`, and assert these physical constraints:

```python
EXPECTED = {
    "ark_customer_accounts",
    "ark_customer_external_identities",
    "ark_customer_facts",
    "ark_customer_profile_versions",
    "ark_customer_suppression_registry",
    "ark_sales_search_results",
    "ark_sales_search_result_sources",
    "ark_customer_opportunities",
    "ark_customer_actions",
}


def test_customer_tables_and_columns_have_comments():
    tables = {table.name: table for table in Base.metadata.sorted_tables}
    assert EXPECTED <= tables.keys()
    for name in EXPECTED:
        assert tables[name].comment
        assert all(column.comment for column in tables[name].columns)


def test_search_candidate_is_unique_per_job_customer():
    table = Base.metadata.tables["ark_sales_search_results"]
    assert any(
        {column.name for column in item.columns} == {"job_id", "customer_id"}
        for item in table.constraints
        if isinstance(item, UniqueConstraint)
    )
```

- [ ] **Step 2: Run the focused test and confirm the tables are absent.**
- [ ] **Step 3: Implement all fields, comments, generated slots, unique keys, composite same-customer foreign keys and `lazy="noload"` relationships from design sections 7 and 12.8. Use Beijing defaults only for business/audit times and explicit UTC only for fencing leases already allowlisted.**
- [ ] **Step 4: Replace old sales model exports in `app.models` with the customer model exports so Alembic metadata is complete.**
- [ ] **Step 5: Run `pytest tests/test_customer_models.py -q` and confirm pass.**
- [ ] **Step 6: Commit `feat: add unified customer data model`.**

## Task 3: Build the destructive migration and guarded cutover inventory

**Files:**
- Create: `backend/alembic/versions/126_unified_customer_domain.py`
- Create: `backend/app/customer/cutover_service.py`
- Create: `backend/tests/test_customer_migration.py`
- Create: `backend/tests/test_customer_cutover.py`
- Create: `scripts/customer_domain_cutover.py`

- [ ] **Step 1: Re-run `git log --all --oneline -- backend/alembic/versions/` and `alembic heads`; set `down_revision` to the single real head and keep revision length at most 32 characters.**
- [ ] **Step 2: Write a failing migration source test** that checks the migration names every retired table explicitly, creates all approved tables, adds actual table/column comments, avoids `TRUNCATE`, and contains preflight assertions before destructive DDL.
- [ ] **Step 3: Write failing cutover tests** for binary-exact J/P/A matching, Session/Run/Event/Artifact fixed-point closure, unrelated Agent row hash preservation and unmapped suppression preservation.
- [ ] **Step 4: Implement `build_inventory(db)`, `export_suppressions(db, hmac_key)`, `resolve_agent_history_closure(db, inventory)` and `verify_unrelated_unchanged(before, after)` without name/time-range matching.**
- [ ] **Step 5: Implement migration upgrade in this order: verify inventory marker; drop foreign keys into retired structures; delete exact Agent closure; drop retired customer tables; alter the preserved target profile; create the 38 new/rebuilt tables; add generated slots, CHECKs, indexes, FKs and comments. `downgrade()` raises because MySQL destructive restoration is unsupported.**
- [ ] **Step 6: Make the script expose `preflight`, `export-suppressions`, `verify-ready`, `apply-reset` and `verify-after`; `apply-reset` must require the exact inventory SHA-256 and a stopped-writer manifest.**
- [ ] **Step 7: Run focused migration/cutover tests and `alembic heads`; do not run `upgrade head` against the shared database yet.**
- [ ] **Step 8: Commit `feat: add guarded customer domain cutover`.**

## Task 4: Implement identity resolution and the evidence ledger

**Files:**
- Create: `backend/app/customer/identity_service.py`
- Create: `backend/app/customer/fact_service.py`
- Create: `backend/tests/test_customer_identity.py`
- Create: `backend/tests/test_customer_facts.py`

- [ ] **Step 1: Write failing tests** for OKKI company ID convergence, Alibaba buyer ID as contact identity, personal-email provisional creation with null company name, shared-domain non-merge, concurrent resolution-key winner/loser rollback, source-record replay idempotency and cross-customer evidence rejection.
- [ ] **Step 2: Run both files and verify failures are caused by missing services.**
- [ ] **Step 3: Implement `resolve_business_context`, `attach_identity_candidate`, `confirm_identity`, `append_source_record`, `append_fact`, `link_fact_evidence`, `open_fact_conflict` and `append_customer_event`. All multi-row first-time creation occurs inside the resolution-key transaction.**
- [ ] **Step 4: Increment `accounts.profile_input_seq` in every committed fact/identity/event mutation and retain raw source payload hashes.**
- [ ] **Step 5: Run focused identity/fact tests, including two-thread MySQL concurrency coverage where available.**
- [ ] **Step 6: Commit `feat: resolve customer identity with evidence`.**

## Task 5: Compile versioned profiles and list/Agent projections

**Files:**
- Create: `backend/app/customer/profile_service.py`
- Create: `backend/tests/test_customer_profile_compiler.py`

- [ ] **Step 1: Write failing tests** for first compile, semantic no-change suppression, no-change CAS race, old-snapshot/new-snapshot race, confirmed fact precedence, expressed/observed conflict preservation, stale fact exclusion and profile/context classification limits.
- [ ] **Step 2: Verify RED with `pytest tests/test_customer_profile_compiler.py -q`.**
- [ ] **Step 3: Implement `compile_customer_profile(customer_id)` using canonical semantic fingerprints, per-section hashes and a row-lock CAS on `profile_input_seq`; recheck the sequence before returning no-change.**
- [ ] **Step 4: Build `customer_context_v1`, `list_projection_v1` and per-target `target_match_v1` only from the committed profile version; keep the previous projection on projection failure and expose stale metadata.**
- [ ] **Step 5: Run the focused compiler tests and confirm all pass.**
- [ ] **Step 6: Commit `feat: compile versioned customer profiles`.**

## Task 6: Rebuild search, research and qualification on `customer_id`

**Files:**
- Modify: `backend/app/sales_automation/models.py`
- Modify: `backend/app/sales_automation/schemas.py`
- Modify: `backend/app/sales_automation/service.py`
- Modify: `backend/app/sales_automation/public_pool_service.py`
- Modify: `backend/app/sales_automation/enrichment_service.py`
- Modify: `backend/app/sales_automation/router.py`
- Modify: `backend/app/sales_automation/agent_router.py`
- Create: `backend/tests/test_customer_acquisition_workflow.py`

- [ ] **Step 1: Replace old sales tests with failing customer-ID tests** for duplicate sources under one result, one active research task per strategy, gate stop, result quality review versus qualification, current-scope qualification CAS, DNC deny gate and target-specific poor-fit.
- [ ] **Step 2: Run the focused file and confirm RED.**
- [ ] **Step 3: Remove `LeadCompany`, `LeadContact`, `ResearchSubject`, `PublicPoolTask`, `DealAssessment`, `ResearchRun` and `ResearchFact` runtime use. Re-export only preserved target-profile and unified workflow models from the customer domain.**
- [ ] **Step 4: Rewrite ingestion to append source records, resolve/create customer, upsert `(job_id, customer_id)`, append result sources, aggregate scores and create the research task by stable fingerprint.**
- [ ] **Step 5: Rewrite public-pool selection and research submission around `customer_id`, research tasks, facts and qualification reviews. Accepted research creates a pending qualification queue; it never silently means qualified.**
- [ ] **Step 6: Return only new envelopes and identifiers from HTTP/Agent endpoints; delete lead/company/subject endpoints rather than aliasing them.**
- [ ] **Step 7: Run acquisition tests and existing knowledge-reference security tests.**
- [ ] **Step 8: Commit `feat: unify acquisition and research workflows`.**

## Task 7: Rebuild opportunities, assignments and radar actions

**Files:**
- Create: `backend/app/customer/workflow_service.py`
- Modify: `backend/app/insight/customer_opportunity_service.py`
- Modify: `backend/app/insight/customer_radar_service.py`
- Modify: `backend/app/insight/customer_profile_service.py`
- Modify: `backend/app/insight/router.py`
- Create: `backend/tests/test_customer_workflow.py`

- [ ] **Step 1: Write failing workflow tests** for approved search/public-pool qualification creating one namespaced pending opportunity and one first action, deferred/rejected creating neither, atomic public-pool claim, owner conflict, opportunity transition evidence, valid-order activation and action completion creating `sales_activity.logged` without fabricating replied/quoted.
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement qualification orchestration, primary/collaborator assignment history, request-time claimability, opportunity upsert by `(source_system, source_account_key, source_key)`, append-only opportunity events and idempotent action generation.**
- [ ] **Step 4: Replace insight customer profile reads with customer query/profile services; remove all name/profile-ID joins and old profile event writes.**
- [ ] **Step 5: Implement merge/split proposal handling so other draft/pending/approved proposals become superseded in the same transaction.**
- [ ] **Step 6: Run workflow tests and all existing opportunity/radar tests updated to `customer_id`.**
- [ ] **Step 7: Commit `feat: unify customer opportunities and radar`.**

## Task 8: Project Alibaba, OKKI, conversations and orders into Ark

**Files:**
- Create: `backend/app/customer/projection_service.py`
- Modify: `backend/app/insight/customer_source_service.py`
- Modify: `backend/app/insight/external_binding_service.py`
- Create: `backend/tests/test_customer_source_projection.py`

- [ ] **Step 1: Write failing projection tests** for namespaced external IDs, Alibaba inquiry messages/attachment metadata, OKKI customer/contact/order/item projection, duplicate replay, order-to-opportunity reconciliation and invalid identity quarantine.
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement deterministic adapters that write source record first, resolve identity, project conversations/messages or orders/items, append facts/events and advance sync cursor only after the complete record succeeds.**
- [ ] **Step 4: Confirm no adapter writes back to Alibaba or OKKI and no customer consumer read path calls the external business DB.**
- [ ] **Step 5: Run projection and OKKI binding tests.**
- [ ] **Step 6: Commit `feat: project external customer sources into Ark`.**

## Task 9: Add scoped human APIs and permissions

**Files:**
- Create: `backend/app/customer/access.py`
- Create: `backend/app/customer/schemas.py`
- Create: `backend/app/customer/query_service.py`
- Create: `backend/app/customer/router.py`
- Create: `backend/app/customer/agent_router.py`
- Modify: `backend/app/routers.py`
- Modify: `backend/app/auth/service.py`
- Create: `backend/tests/test_customer_api.py`
- Create: `backend/tests/test_customer_permissions.py`

- [ ] **Step 1: Write failing API tests** for unified envelopes, customer list/detail/timeline, research queues, opportunity/action updates and high-impact proposals. Add the full four data classes by owner/collaborator/public-pool/team-admin/global-admin and Run-scope permission matrix.
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement `/api/customer-hub` endpoints with service-only routers, `require_permission`/`require_any_permission`, `ok()` envelopes, pagination and Beijing-time serializers.**
- [ ] **Step 4: Seed `customer:admin` and retain existing acquisition/opportunity/radar action codes only where they control a distinct action; add `customer:read_all` as a data-kind code.**
- [ ] **Step 5: Register only the new customer router for customer operations and remove retired customer opportunity/radar routes from insight.**
- [ ] **Step 6: Run API/permission tests.**
- [ ] **Step 7: Commit `feat: expose unified customer hub api`.**

## Task 10: Replace customer Agent access with scoped read tools

**Files:**
- Create: `backend/app/customer/agent_service.py`
- Modify: `backend/app/mcp/agent_tools.py`
- Modify: `backend/app/mcp/server.py`
- Modify: `backend/app/agent_runtime/evaluation_service.py`
- Modify: `backend/app/agent_runtime/orchestration.py`
- Create: `backend/tests/test_customer_agent_tools.py`

- [ ] **Step 1: Write failing tests** for materialized Run members, same external appearance for absent/unauthorized customers, signed cursors, total/section/row budgets, stale metadata, evidence claim validation, raw-message on-demand access and cross-customer evidence rejection.
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement `resolve_customer`, `search_customers`, `get_customer_profile`, `get_customer_facts`, `get_customer_orders`, `search_customer_messages`, `get_customer_actions`, `get_customer_evidence` and `get_customer_source_chunks` through `agent_service`; never return ORM rows or complete profile/context JSON.**
- [ ] **Step 4: Materialize Run customer membership before queued state and intersect frozen permissions with live permissions on every call. Consumer tools use Ark read-only sessions; research writes remain task-scoped Agent endpoints.**
- [ ] **Step 5: Update the 30-case evaluation contract to use `customer_id` and new evidence envelopes.**
- [ ] **Step 6: Run Agent tool, runtime and evaluation tests.**
- [ ] **Step 7: Commit `feat: secure customer agent tools`.**

## Task 11: Consolidate the customer-facing UI

**Files:**
- Modify: `frontend/src/api/clients.js`
- Create: `frontend/src/api/customerHub.js`
- Create: `frontend/src/views/customer_hub/CustomerProfiles.vue`
- Create: `frontend/src/views/customer_hub/AcquisitionTasks.vue`
- Create: `frontend/src/views/customer_hub/ResearchCenter.vue`
- Create: `frontend/src/views/customer_hub/OpportunityDesk.vue`
- Create: `frontend/src/views/customer_hub/CustomerRadar.vue`
- Create: `frontend/src/views/customer_hub/components/CustomerDetailDrawer.vue`
- Create: `frontend/src/views/customer_hub/composables/useCustomerHub.js`
- Modify: `frontend/src/config/navigation.js`
- Delete: retired sales lead-pool and insight customer opportunity/radar views after replacement.

- [ ] **Step 1: Add failing frontend tests for API parameter mapping, list state, stale/error guidance and navigation permissions.**
- [ ] **Step 2: Add `customerHubClient` and new API module; no direct axios instance.**
- [ ] **Step 3: Build the five “客户经营” entries using the list/search/feedback patterns from `DictManagement.vue` and `ExpoLeads.vue`; keep Vue files below 500 lines by moving state to the composable.**
- [ ] **Step 4: Make the detail drawer progressively show overview, identity, contacts, conversations, orders, evidence, opportunities, actions, annotations and version quality.**
- [ ] **Step 5: Remove old navigation entries and deleted view imports.**
- [ ] **Step 6: Run frontend tests and `npm run build`.**
- [ ] **Step 7: Commit `feat: consolidate customer operations ui`.**

## Task 12: Update Ark skills and remove retired runtime paths

**Files:**
- Modify: `.agents/skills/ark-lead-discovery/SKILL.md`
- Modify: `.agents/skills/ark-company-research/SKILL.md`
- Modify: `.agents/skills/ark-public-pool-research/SKILL.md`
- Modify: `.agents/skills/ark-email-outreach/SKILL.md`
- Modify: `backend/app/models/__init__.py`
- Delete: runtime code that imports retired customer models after all call sites are migrated.
- Create: `backend/tests/test_customer_retirement.py`

- [ ] **Step 1: Write a failing repository scan test** that rejects imports/references to `LeadCompany`, `ResearchSubject`, old `CustomerProfile`, `CustomerProfileEvent`, and customer association by `profile_id`, `company_id`, `subject_id` or `customer_name` in the customer operating paths.
- [ ] **Step 2: Update the four skills to use `customer_id`, task-scoped research writes and Ark-only consumer reads.**
- [ ] **Step 3: Delete retired model/service/router paths and update every delayed import and scheduler registration found by global `rg`.**
- [ ] **Step 4: Run retirement scan plus sales, insight, MCP, Agent runtime and scheduler tests.**
- [ ] **Step 5: Commit `refactor: retire duplicated customer runtime`.**

## Task 13: Documentation, database rehearsal and completion audit

**Files:**
- Modify: `docs/database.md`
- Modify: `docs/api-reference.md`
- Modify: `docs/architecture.md`
- Modify: `docs/module-notes.md`
- Modify: `docs/runbook.md`
- Modify: `docs/handoff.md`
- Create: `docs/memory/project_customer.md`

- [ ] **Step 1: Document every new table, endpoint, data flow, Agent trust boundary and cutover command.**
- [ ] **Step 2: Run migration in a disposable MySQL database matching production version/SQL mode, then query `information_schema.tables` and `information_schema.columns` to assert all 38 tables and all columns have comments.**
- [ ] **Step 3: Run preflight against the shared database read-only and save the inventory, suppression manifest, writer manifest requirements and exact reset SHA-256. Do not apply while any writer is active.**
- [ ] **Step 4: Run `python scripts/check_conventions.py --base $(git merge-base main HEAD)`, focused tests, full `pytest`, frontend tests, `npm run build`, `alembic heads` and `python scripts/git_sweep.py`; preserve actual outputs.**
- [ ] **Step 5: Trigger independent adversarial review for boundary conditions, concurrent writes, idempotency, migration safety and frontend/backend contract consistency; fix every P0/P1 finding with a failing test first.**
- [ ] **Step 6: During the approved maintenance window, stop every writer, re-run exact preflight, export suppressions, apply reset, deploy only the new code, replay suppressions, run a four-customer smoke sync and then resume writers.**
- [ ] **Step 7: Commit `docs: document unified customer operations`.**

## Self-review

- Spec coverage: all design sections 5 through 20 map to Tasks 1–13; payment, logistics, aftersales and expo remain excluded.
- Placeholder scan: this plan contains no deferred implementation markers; destructive execution has a concrete readiness gate rather than an unspecified later step.
- Type consistency: all business flows use `BIGINT customer_id`; external namespaces use `source_system + source_account_key`; profile version references carry `customer_id`; Agent scope membership is materialized.
- Delivery concern: the repository points development and production at one MySQL database. Code and disposable-MySQL rehearsal can proceed autonomously, but the final destructive reset must wait until the stopped-writer manifest proves every local and cloud writer is paused.
