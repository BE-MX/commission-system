# Knowledge Sidebar and Permissions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move knowledge search and management into a collapsible balanced sidebar, add three persisted knowledge-library categories, and replace numeric member IDs with secure Ark username selection.

**Architecture:** Keep authorization and Ark-user lookup inside `backend/app/knowledge/`; add one required library category column and one library-scoped member-candidate endpoint. Keep page orchestration in `KnowledgeWorkbench.vue`, make `KnowledgeSidebar.vue` presentational, and isolate category/storage/duplicate rules plus overflow measurement in small testable frontend units.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2, Vue 3 Composition API, Element Plus, Node test runner, Vite.

---

## File map

- Create `backend/alembic/versions/105_knowledge_category.py`: add and backfill the required library category column.
- Modify `backend/app/knowledge/models.py`: declare `KnowledgeLibrary.category`.
- Modify `backend/app/knowledge/schemas.py`: require a literal category on library creation.
- Modify `backend/app/knowledge/service.py`: validate/return categories; validate Ark users; list member identities; search member candidates.
- Modify `backend/app/knowledge/router.py`: expose category fields and the member-candidate endpoint.
- Modify `backend/tests/test_knowledge_migration.py`: prove existing rows backfill to `company` and downgrade removes the column.
- Modify `backend/tests/test_knowledge_service.py`: cover categories, active-user validation, member identity responses, and candidate authorization/search.
- Modify `backend/tests/test_knowledge_api.py`: cover HTTP category and member-candidate contracts.
- Create `frontend/src/views/knowledge/knowledgeUi.js`: category metadata, sidebar storage helpers, and member-list helpers.
- Create `frontend/src/views/knowledge/components/OverflowTooltip.vue`: enable a tooltip only for actually truncated text.
- Modify `frontend/src/views/knowledge/components/KnowledgeSidebar.vue`: render the balanced expanded/collapsed sidebar and emit intent events.
- Modify `frontend/src/views/knowledge/KnowledgeWorkbench.vue`: orchestrate classification, search, collapse state, approvals, and username-based member editing.
- Create `frontend/tests/knowledgeSidebar.test.mjs`: verify pure UI rules and source-level interaction surfaces.
- Modify `frontend/tests/knowledgeEditor.test.mjs`: update workbench structure assertions without weakening existing editor/deletion regression coverage.
- Modify `docs/api-reference.md`: document the member-candidate endpoint and changed knowledge payloads.
- Modify `docs/database.md`: document `ark_knowledge_libraries.category`.
- Modify `docs/module-notes.md`: record the confirmed knowledge-workbench UX contract.

The current snapshot is not Git-backed. Commit steps below define clean boundaries for the real repository; when executing in this snapshot, record the skipped commit with the observed `not a git repository` result rather than initializing a new repository.

### Task 1: Persist and expose knowledge-library categories

**Files:**
- Create: `backend/alembic/versions/105_knowledge_category.py`
- Modify: `backend/app/knowledge/models.py`
- Modify: `backend/app/knowledge/schemas.py`
- Modify: `backend/app/knowledge/service.py`
- Modify: `backend/app/knowledge/router.py`
- Modify: `backend/tests/test_knowledge_migration.py`
- Modify: `backend/tests/test_knowledge_service.py`
- Modify: `backend/tests/test_knowledge_api.py`

- [ ] **Step 1: Write failing migration and service/API tests**

Add a migration loader and a focused existing-row test to `backend/tests/test_knowledge_migration.py`:

```python
def _category_migration_module():
    path = Path(__file__).parents[1] / "alembic" / "versions" / "105_knowledge_category.py"
    spec = importlib.util.spec_from_file_location("knowledge_category_migration_105", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_knowledge_category_migration_backfills_existing_libraries():
    engine = create_engine("sqlite://")
    metadata = sa.MetaData()
    libraries = sa.Table(
        "ark_knowledge_libraries",
        metadata,
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
    )
    metadata.create_all(engine)
    migration = _category_migration_module()
    with engine.begin() as connection:
        connection.execute(libraries.insert().values(id=1, name="已有知识库"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        columns = {column["name"]: column for column in inspect(connection).get_columns("ark_knowledge_libraries")}
        assert columns["category"]["nullable"] is False
        assert connection.execute(sa.text(
            "SELECT category FROM ark_knowledge_libraries WHERE id = 1"
        )).scalar_one() == "company"
        migration.downgrade()
        assert "category" not in {
            column["name"] for column in inspect(connection).get_columns("ark_knowledge_libraries")
        }
    engine.dispose()
```

Add `import sqlalchemy as sa` to that test file. In `backend/tests/test_knowledge_service.py`, add:

```python
def test_library_category_is_required_and_returned(db):
    admin = identity(1, ["knowledge:admin", "knowledge:read"])
    company = service.create_library(db, admin, name="制度", category="company")
    department = service.create_library(db, admin, name="营销", category="department")
    personal = service.create_library(db, admin, name="经验", category="personal")

    assert [item["category"] for item in service.list_libraries(db, admin)] == [
        "personal", "department", "company"
    ]
    assert service.get_library(db, admin, department.id)["category"] == "department"
    with pytest.raises(service.ValidationError):
        service.create_library(db, admin, name="非法", category="team")
```

Update every existing service call in this test file to pass `category="company"`. Update every existing `POST /api/knowledge/libraries` JSON payload in `backend/tests/test_knowledge_api.py` to include `"category": "company"`, then add:

```python
def test_http_library_category_is_required_and_returned():
    client, db, identity, engine = _setup()
    try:
        missing = client.post("/api/knowledge/libraries", json={"name": "缺分类"})
        assert missing.status_code == 422
        created = client.post("/api/knowledge/libraries", json={
            "name": "营销中心",
            "category": "department",
        })
        assert created.status_code == 200, created.text
        assert created.json()["data"]["category"] == "department"
        listed = client.get("/api/knowledge/libraries")
        assert listed.json()["data"][0]["category"] == "department"
    finally:
        client.close()
        db.close()
        engine.dispose()
```

- [ ] **Step 2: Run the category tests and verify RED**

Run from `backend/`:

```powershell
python -m pytest tests/test_knowledge_migration.py::test_knowledge_category_migration_backfills_existing_libraries tests/test_knowledge_service.py::test_library_category_is_required_and_returned tests/test_knowledge_api.py::test_http_library_category_is_required_and_returned -q
```

Expected: FAIL because `105_knowledge_category.py` does not exist and `create_library`/`LibraryCreate` do not accept `category`.

- [ ] **Step 3: Add the category migration**

Create `backend/alembic/versions/105_knowledge_category.py`:

```python
"""Add required knowledge library category.

Revision ID: 105_knowledge_category
Revises: 104_ci_generation_snapshots
Create Date: 2026-08-11
"""

from alembic import op
import sqlalchemy as sa


revision = "105_knowledge_category"
down_revision = "104_ci_generation_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ark_knowledge_libraries") as batch_op:
        batch_op.add_column(sa.Column(
            "category",
            sa.String(length=16),
            nullable=True,
            comment="company/department/personal",
        ))
    op.execute(sa.text(
        "UPDATE ark_knowledge_libraries SET category = 'company' WHERE category IS NULL"
    ))
    with op.batch_alter_table("ark_knowledge_libraries") as batch_op:
        batch_op.alter_column(
            "category",
            existing_type=sa.String(length=16),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("ark_knowledge_libraries") as batch_op:
        batch_op.drop_column("category")
```

- [ ] **Step 4: Add the category model, schema, service, and route contract**

In `backend/app/knowledge/models.py`, add after `description`:

```python
category = Column(String(16), nullable=False, comment="company/department/personal")
```

In `backend/app/knowledge/schemas.py`:

```python
class LibraryCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    category: Literal["company", "department", "personal"]
    description: str | None = Field(default=None, max_length=512)
```

In `backend/app/knowledge/service.py`, declare `LIBRARY_CATEGORIES`, require it in `create_library`, and return it in list/detail payloads:

```python
LIBRARY_CATEGORIES = frozenset({"company", "department", "personal"})


def create_library(
    db,
    identity: dict,
    *,
    name: str,
    category: str,
    description: str | None = None,
) -> KnowledgeLibrary:
    _require_platform(identity, "knowledge:admin")
    clean_name = name.strip()
    if not clean_name:
        raise ValidationError("library name is required")
    if category not in LIBRARY_CATEGORIES:
        raise ValidationError("invalid knowledge library category")
    row = KnowledgeLibrary(
        name=clean_name,
        category=category,
        description=description,
        created_by=access.user_id(identity),
    )
    db.add(row)
    db.flush()
    db.add(KnowledgeLibraryMember(
        library_id=row.id,
        user_id=access.user_id(identity),
        role="admin",
        created_by=access.user_id(identity),
    ))
    _audit(db, identity, row.id, "create_library", "library", row.id)
    db.commit()
    db.refresh(row)
    return row
```

Return dictionaries must include `"category": library.category` or `"category": row.category` without a fallback.

In `backend/app/knowledge/router.py`, extend `_library` and the create call:

```python
def _library(row):
    return {
        "id": row.id,
        "name": row.name,
        "category": row.category,
        "description": row.description,
        "status": row.status,
    }


@router.post("/libraries")
def create_library(
    payload: LibraryCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("knowledge:admin")),
):
    return ok(_library(_call(
        service.create_library,
        db,
        user,
        name=payload.name,
        category=payload.category,
        description=payload.description,
    )))
```

- [ ] **Step 5: Run category tests and verify GREEN**

Run from `backend/`:

```powershell
python -m pytest tests/test_knowledge_migration.py tests/test_knowledge_service.py tests/test_knowledge_api.py -q
```

Expected: PASS with zero failures.

- [ ] **Step 6: Commit the category slice in a Git-backed worktree**

```powershell
git add backend/alembic/versions/105_knowledge_category.py backend/app/knowledge backend/tests/test_knowledge_migration.py backend/tests/test_knowledge_service.py backend/tests/test_knowledge_api.py
git commit -m "feat: classify knowledge libraries"
```

### Task 2: Use Ark usernames for member permissions

**Files:**
- Modify: `backend/app/knowledge/service.py`
- Modify: `backend/app/knowledge/router.py`
- Modify: `backend/tests/test_knowledge_service.py`
- Modify: `backend/tests/test_knowledge_api.py`

- [ ] **Step 1: Seed Ark users in knowledge tests and write failing behavior tests**

Import `ArkUser` in both knowledge test files. Add `ArkUser.__table__` before knowledge tables so the table exists, and seed deterministic users:

```python
def seed_users(db):
    db.add_all([
        ArkUser(
            id=user_id,
            username=f"user-{user_id}",
            password_hash="test-only",
            real_name=f"用户{user_id}",
            is_active=user_id != 9,
        )
        for user_id in range(1, 11)
    ])
    db.commit()
```

Call `seed_users(db)` in the service fixture and API `_setup()`. Add service tests:

```python
def test_members_return_ark_usernames_and_candidate_search_is_scoped(db):
    admin = identity(1, ["knowledge:admin", "knowledge:read"])
    outsider = identity(2, ["knowledge:admin", "knowledge:read"])
    library = service.create_library(db, admin, name="制度", category="company")
    service.replace_members(db, admin, library.id, [{"user_id": 3, "role": "viewer"}])

    assert service.list_members(db, admin, library.id) == [
        {"user_id": 1, "username": "user-1", "real_name": "用户1", "role": "admin"},
        {"user_id": 3, "username": "user-3", "real_name": "用户3", "role": "viewer"},
    ]
    assert service.search_member_candidates(db, admin, library.id, "user-3", limit=20) == [
        {"user_id": 3, "username": "user-3", "real_name": "用户3"}
    ]
    with pytest.raises(service.NotFoundError):
        service.search_member_candidates(db, outsider, library.id, "user", limit=20)


def test_replace_members_rejects_duplicate_missing_and_inactive_users(db):
    admin = identity(1, ["knowledge:admin"])
    library = service.create_library(db, admin, name="制度", category="company")

    with pytest.raises(service.ValidationError, match="duplicate"):
        service.replace_members(db, admin, library.id, [
            {"user_id": 3, "role": "viewer"},
            {"user_id": 3, "role": "editor"},
        ])
    with pytest.raises(service.ValidationError, match="inactive or missing"):
        service.replace_members(db, admin, library.id, [{"user_id": 9, "role": "viewer"}])
    with pytest.raises(service.ValidationError, match="inactive or missing"):
        service.replace_members(db, admin, library.id, [{"user_id": 999, "role": "viewer"}])
```

Add an API test that asserts candidate results have exactly `user_id`, `username`, and `real_name`, and that changing identity to a non-member knowledge admin returns 404.

- [ ] **Step 2: Run member tests and verify RED**

Run from `backend/`:

```powershell
python -m pytest tests/test_knowledge_service.py::test_members_return_ark_usernames_and_candidate_search_is_scoped tests/test_knowledge_service.py::test_replace_members_rejects_duplicate_missing_and_inactive_users tests/test_knowledge_api.py -q
```

Expected: FAIL because list members only returns IDs, candidate search does not exist, and duplicate/inactive users are accepted.

- [ ] **Step 3: Implement authoritative Ark-user validation and member identity responses**

Import `ArkUser` and add these helpers to `backend/app/knowledge/service.py`:

```python
from app.auth.models import ArkUser


def _active_user_ids(db, ids: set[int]) -> set[int]:
    if not ids:
        return set()
    return {
        row[0]
        for row in db.query(ArkUser.id).filter(
            ArkUser.id.in_(ids),
            ArkUser.is_active.is_(True),
            ArkUser.deleted_at.is_(None),
        ).all()
    }
```

In `replace_members`, build `member_ids` before normalization, reject duplicate IDs, compare them with `_active_user_ids`, and raise `ValidationError("knowledge member user is inactive or missing")` if any are absent. Keep the existing actor-admin protection after validation.

Replace `list_members` with an explicit join that does not load unrelated roles:

```python
def list_members(db, identity: dict, library_id: int) -> list[dict]:
    _require_platform(identity, "knowledge:admin")
    _library(db, identity, library_id, "admin")
    rows = db.query(
        KnowledgeLibraryMember.user_id,
        ArkUser.username,
        ArkUser.real_name,
        KnowledgeLibraryMember.role,
    ).join(ArkUser, ArkUser.id == KnowledgeLibraryMember.user_id).filter(
        KnowledgeLibraryMember.library_id == library_id,
        ArkUser.deleted_at.is_(None),
    ).order_by(ArkUser.username).all()
    return [
        {"user_id": user_id, "username": username, "real_name": real_name, "role": role}
        for user_id, username, real_name, role in rows
    ]
```

- [ ] **Step 4: Implement scoped member-candidate search and route**

Add to `backend/app/knowledge/service.py`:

```python
def search_member_candidates(
    db,
    identity: dict,
    library_id: int,
    query: str,
    *,
    limit: int = 20,
) -> list[dict]:
    _require_platform(identity, "knowledge:admin")
    _library(db, identity, library_id, "admin")
    clean_query = query.strip()
    users = db.query(ArkUser.id, ArkUser.username, ArkUser.real_name).filter(
        ArkUser.is_active.is_(True),
        ArkUser.deleted_at.is_(None),
    )
    if clean_query:
        pattern = f"%{clean_query}%"
        users = users.filter(or_(ArkUser.username.like(pattern), ArkUser.real_name.like(pattern)))
    rows = users.order_by(ArkUser.username).limit(limit).all()
    return [
        {"user_id": user_id, "username": username, "real_name": real_name}
        for user_id, username, real_name in rows
    ]
```

Add to `backend/app/knowledge/router.py` after the members routes:

```python
@router.get("/libraries/{library_id}/member-candidates")
def member_candidates(
    library_id: int,
    q: str = Query(default="", max_length=50),
    limit: int = Query(default=20, ge=1, le=20),
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("knowledge:admin")),
):
    return ok(_call(
        service.search_member_candidates,
        db,
        user,
        library_id,
        q,
        limit=limit,
    ))
```

- [ ] **Step 5: Run knowledge backend tests and verify GREEN**

Run from `backend/`:

```powershell
python -m pytest tests/test_knowledge_service.py tests/test_knowledge_api.py tests/test_knowledge_content.py tests/test_mcp_knowledge.py -q
```

Expected: PASS with zero failures.

- [ ] **Step 6: Commit the member-permission slice in a Git-backed worktree**

```powershell
git add backend/app/knowledge backend/tests/test_knowledge_service.py backend/tests/test_knowledge_api.py
git commit -m "feat: select knowledge members by username"
```

### Task 3: Add testable frontend knowledge UI rules and overflow tooltips

**Files:**
- Create: `frontend/src/views/knowledge/knowledgeUi.js`
- Create: `frontend/src/views/knowledge/components/OverflowTooltip.vue`
- Create: `frontend/tests/knowledgeSidebar.test.mjs`

- [ ] **Step 1: Write failing pure-function and component-contract tests**

Create `frontend/tests/knowledgeSidebar.test.mjs`:

```javascript
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  LIBRARY_CATEGORIES,
  isDuplicateMember,
  readSidebarCollapsed,
  writeSidebarCollapsed,
} from '../src/views/knowledge/knowledgeUi.js'

function read(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

test('library categories have distinct semantic labels and tones', () => {
  assert.deepEqual(Object.keys(LIBRARY_CATEGORIES), ['company', 'department', 'personal'])
  assert.deepEqual(
    Object.values(LIBRARY_CATEGORIES).map(item => [item.label, item.tone]),
    [['公司级', 'company'], ['部门级', 'department'], ['个人级', 'personal']],
  )
})

test('sidebar collapse storage accepts only an explicit true value', () => {
  const state = new Map()
  const storage = {
    getItem: key => state.get(key) ?? null,
    setItem: (key, value) => state.set(key, value),
  }
  assert.equal(readSidebarCollapsed(storage), false)
  writeSidebarCollapsed(storage, true)
  assert.equal(readSidebarCollapsed(storage), true)
  state.set('knowledge-sidebar-collapsed', 'broken')
  assert.equal(readSidebarCollapsed(storage), false)
})

test('member duplicate detection compares stable Ark user ids', () => {
  const members = [{ user_id: 7, username: 'liang' }]
  assert.equal(isDuplicateMember(members, 7), true)
  assert.equal(isDuplicateMember(members, 8), false)
})

test('overflow tooltip measures actual rendered overflow', () => {
  const source = read('../src/views/knowledge/components/OverflowTooltip.vue')
  assert.match(source, /scrollWidth > .*clientWidth/)
  assert.match(source, /ResizeObserver/)
  assert.match(source, /:disabled="!overflowing"/)
  assert.match(source, /prefers-reduced-motion: reduce/)
})
```

- [ ] **Step 2: Run the frontend test and verify RED**

Run from `frontend/`:

```powershell
node --test tests/knowledgeSidebar.test.mjs
```

Expected: FAIL because `knowledgeUi.js` and `OverflowTooltip.vue` do not exist.

- [ ] **Step 3: Implement category, storage, and duplicate helpers**

Create `frontend/src/views/knowledge/knowledgeUi.js`:

```javascript
export const LIBRARY_CATEGORIES = Object.freeze({
  company: Object.freeze({ label: '公司级', tone: 'company' }),
  department: Object.freeze({ label: '部门级', tone: 'department' }),
  personal: Object.freeze({ label: '个人级', tone: 'personal' }),
})

export const SIDEBAR_COLLAPSED_KEY = 'knowledge-sidebar-collapsed'

export function readSidebarCollapsed(storage = window.localStorage) {
  return storage.getItem(SIDEBAR_COLLAPSED_KEY) === 'true'
}

export function writeSidebarCollapsed(collapsed, storage = window.localStorage) {
  storage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? 'true' : 'false')
}

export function isDuplicateMember(members, userId) {
  return members.some(member => member.user_id === userId)
}
```

- [ ] **Step 4: Implement the reusable overflow-only tooltip**

Create `frontend/src/views/knowledge/components/OverflowTooltip.vue` with a single truncating span, `ResizeObserver`, a prop-text watcher, and cleanup:

```vue
<template>
  <el-tooltip :content="text" :disabled="!overflowing" placement="top" :show-after="300">
    <span ref="textElement" class="overflow-tooltip-text"><slot>{{ text }}</slot></span>
  </el-tooltip>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({ text: { type: String, required: true } })
const textElement = ref(null)
const overflowing = ref(false)
let observer = null

function measure() {
  const element = textElement.value
  overflowing.value = Boolean(element && element.scrollWidth > element.clientWidth)
}

onMounted(() => {
  observer = new ResizeObserver(measure)
  if (textElement.value) observer.observe(textElement.value)
  measure()
})
watch(() => props.text, () => nextTick(measure))
onBeforeUnmount(() => observer?.disconnect())
</script>

<style scoped>
.overflow-tooltip-text { display: block; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
@media (prefers-reduced-motion: reduce) { .overflow-tooltip-text { scroll-behavior: auto; } }
</style>
```

- [ ] **Step 5: Run the helper/component test and verify GREEN**

Run from `frontend/`:

```powershell
node --test tests/knowledgeSidebar.test.mjs
```

Expected: 4 tests pass.

- [ ] **Step 6: Commit the frontend primitives in a Git-backed worktree**

```powershell
git add frontend/src/views/knowledge/knowledgeUi.js frontend/src/views/knowledge/components/OverflowTooltip.vue frontend/tests/knowledgeSidebar.test.mjs
git commit -m "feat: add knowledge sidebar UI primitives"
```

### Task 4: Build the balanced collapsible sidebar

**Files:**
- Modify: `frontend/src/views/knowledge/components/KnowledgeSidebar.vue`
- Modify: `frontend/src/views/knowledge/KnowledgeWorkbench.vue`
- Modify: `frontend/tests/knowledgeSidebar.test.mjs`
- Modify: `frontend/tests/knowledgeEditor.test.mjs`

- [ ] **Step 1: Add failing sidebar placement and accessibility assertions**

Append to `frontend/tests/knowledgeSidebar.test.mjs`:

```javascript
test('balanced sidebar owns search, adjacent create/approval actions, row permissions, and collapse', () => {
  const sidebar = read('../src/views/knowledge/components/KnowledgeSidebar.vue')
  const workbench = read('../src/views/knowledge/KnowledgeWorkbench.vue')
  assert.ok(sidebar.indexOf('搜索已发布知识') < sidebar.indexOf('class="sidebar-header"'))
  assert.match(sidebar, /新建知识库[\s\S]*审批队列/)
  assert.match(sidebar, /@click\.stop="\$emit\('open-members', library\)"/)
  assert.match(sidebar, /OverflowTooltip[\s\S]*library\.name/)
  assert.match(sidebar, /OverflowTooltip[\s\S]*data\.title/)
  assert.match(sidebar, /aria-expanded/)
  assert.match(sidebar, /LIBRARY_CATEGORIES\[library\.category\]/)
  assert.match(sidebar, /FolderAdd/)
  assert.match(sidebar, /DocumentAdd/)
  assert.match(workbench, /knowledge-sidebar-collapsed/)
  assert.doesNotMatch(workbench, /<header class="page-bar">/)
})
```

Update any `knowledgeEditor.test.mjs` source assertion that assumes the old top page bar while preserving all dirty-state, delete, and editor assertions.

- [ ] **Step 2: Run sidebar tests and verify RED**

Run from `frontend/`:

```powershell
node --test tests/knowledgeSidebar.test.mjs tests/knowledgeEditor.test.mjs
```

Expected: FAIL because search/actions remain in the page bar and collapse/category/overflow surfaces are absent.

- [ ] **Step 3: Rebuild `KnowledgeSidebar.vue` around the approved prop/event contract**

Use these props and emits:

```javascript
const props = defineProps({
  libraries: { type: Array, default: () => [] },
  selectedLibraryId: { type: Number, default: null },
  tree: { type: Array, default: () => [] },
  searchQuery: { type: String, default: '' },
  collapsed: Boolean,
  canWrite: Boolean,
  canCreateLibrary: Boolean,
  canReview: Boolean,
  canManageMembers: Boolean,
  canDeleteLibrary: Boolean,
  canDeleteNode: Boolean,
})

defineEmits([
  'update:search-query', 'search', 'toggle-collapse', 'select-library',
  'select-document', 'create-library', 'create-node', 'open-approvals',
  'open-members', 'delete-library', 'delete-node',
])
```

Expanded DOM order must be:

1. search input and search button;
2. `sidebar-header` with adjacent new-library and approval buttons;
3. library rows with category icon, `OverflowTooltip`, role label, direct member button, and secondary delete button;
4. tree header with distinct folder/document add buttons;
5. tree rows using `OverflowTooltip`;
6. collapse button.

Collapsed DOM must retain tooltip-wrapped icon buttons for search, new library, approvals, and every library. Category classes must use existing semantic tokens:

```css
.library-category.company { color: var(--color-primary); background: var(--color-primary-light); }
.library-category.department { color: var(--color-info-text); background: var(--color-info-bg); }
.library-category.personal { color: var(--color-success); background: var(--color-success-bg); }
.create-folder { color: var(--text-on-dark); background: var(--color-info-text); }
.create-document { color: var(--text-on-dark); background: var(--color-primary); }
```

Do not add a transition to grid column width. Gate hover styling with `@media (hover: hover) and (pointer: fine)` and remove transform feedback in `prefers-reduced-motion`.

- [ ] **Step 4: Move workbench search/actions into the sidebar and persist collapse state**

In `KnowledgeWorkbench.vue`, remove `page-bar`, pass the new props/events, and add:

```javascript
import { readSidebarCollapsed, writeSidebarCollapsed } from './knowledgeUi.js'

const sidebarCollapsed = ref(readSidebarCollapsed())
const canReviewApprovals = computed(() => (
  auth.hasPermission('knowledge:review') || auth.hasPermission('knowledge:admin')
))

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  writeSidebarCollapsed(sidebarCollapsed.value)
}
```

Bind the workspace state without animation:

```vue
<div class="workspace" :class="{ 'sidebar-collapsed': sidebarCollapsed }">
```

```css
.workspace { grid-template-columns: 310px minmax(0, 1fr); }
.workspace.sidebar-collapsed { grid-template-columns: 54px minmax(0, 1fr); }
```

- [ ] **Step 5: Run sidebar/editor tests and verify GREEN**

Run from `frontend/`:

```powershell
node --test tests/knowledgeSidebar.test.mjs tests/knowledgeEditor.test.mjs
```

Expected: all tests pass with zero failures.

- [ ] **Step 6: Commit the balanced sidebar in a Git-backed worktree**

```powershell
git add frontend/src/views/knowledge/components/KnowledgeSidebar.vue frontend/src/views/knowledge/KnowledgeWorkbench.vue frontend/tests/knowledgeSidebar.test.mjs frontend/tests/knowledgeEditor.test.mjs
git commit -m "feat: balance knowledge sidebar actions"
```

### Task 5: Add classified library creation and username-based member editing

**Files:**
- Modify: `frontend/src/views/knowledge/KnowledgeWorkbench.vue`
- Modify: `frontend/tests/knowledgeSidebar.test.mjs`

- [ ] **Step 1: Write failing workbench assertions for category creation and username selection**

Append:

```javascript
test('workbench creates classified libraries and edits members by Ark username', () => {
  const workbench = read('../src/views/knowledge/KnowledgeWorkbench.vue')
  assert.match(workbench, /libraryForm = reactive\(\{ name: '', description: '', category: 'company' \}\)/)
  assert.match(workbench, /LIBRARY_CATEGORIES/)
  assert.match(workbench, /成员权限 ·/)
  assert.match(workbench, /member-candidates/)
  assert.match(workbench, /remote-method="searchMemberCandidates"/)
  assert.match(workbench, /member\.username/)
  assert.doesNotMatch(workbench, /el-input-number[\s\S]*member\.user_id/)
  assert.match(workbench, /openMembers\(library\)/)
  assert.match(workbench, /isDuplicateMember/)
})
```

- [ ] **Step 2: Run test and verify RED**

Run from `frontend/`:

```powershell
node --test tests/knowledgeSidebar.test.mjs
```

Expected: FAIL because the create dialog lacks classification and member editing still uses numeric IDs.

- [ ] **Step 3: Add the classification selector to library creation**

Import `LIBRARY_CATEGORIES` and initialize:

```javascript
const libraryForm = reactive({ name: '', description: '', category: 'company' })
```

Render three radio buttons/cards from `Object.entries(LIBRARY_CATEGORIES)`. Submit the existing reactive payload unchanged, and reset with:

```javascript
Object.assign(libraryForm, { name: '', description: '', category: 'company' })
```

- [ ] **Step 4: Replace member-ID entry with a target-library member editor**

Add state:

```javascript
const memberLibrary = ref(null)
const memberOptions = ref([])
const selectedMemberId = ref(null)
const memberSearchLoading = ref(false)
const memberDialogTitle = computed(() => `成员权限 · ${memberLibrary.value?.name || ''}`)
```

Implement:

```javascript
async function openMembers(library) {
  try {
    const loaded = unwrap(await knowledgeClient.get(`/libraries/${library.id}/members`))
    memberLibrary.value = library
    members.value = loaded
    memberOptions.value = loaded.map(({ user_id, username, real_name }) => ({ user_id, username, real_name }))
    selectedMemberId.value = null
    memberDialog.value = true
  } catch {
    msgError('成员加载失败，请重新点击成员权限')
  }
}

async function searchMemberCandidates(query = '') {
  if (!memberLibrary.value) return
  memberSearchLoading.value = true
  try {
    memberOptions.value = unwrap(await knowledgeClient.get(
      `/libraries/${memberLibrary.value.id}/member-candidates`,
      { params: { q: query, limit: 20 } },
    ))
  } catch {
    msgError('成员搜索失败，请重试')
  } finally {
    memberSearchLoading.value = false
  }
}

function addSelectedMember() {
  const option = memberOptions.value.find(item => item.user_id === selectedMemberId.value)
  if (!option || isDuplicateMember(members.value, option.user_id)) return
  members.value.push({ ...option, role: 'viewer' })
  selectedMemberId.value = null
}

async function saveMembers() {
  if (!memberLibrary.value) return
  await knowledgeClient.put(`/libraries/${memberLibrary.value.id}/members`, {
    members: members.value.map(({ user_id, role }) => ({ user_id, role })),
  })
  memberDialog.value = false
  await loadLibraries()
  msgSuccess('保存权限')
}
```

The dialog must display `username` as primary text, `real_name` as secondary text, keep role selection and remove actions, and use an `el-select` with `filterable remote reserve-keyword` plus an explicit “添加成员” button.

- [ ] **Step 5: Run frontend knowledge tests and verify GREEN**

Run from `frontend/`:

```powershell
node --test tests/knowledgeSidebar.test.mjs tests/knowledgeEditor.test.mjs tests/knowledgeState.test.mjs
```

Expected: all tests pass with zero failures.

- [ ] **Step 6: Commit the member/classification UI in a Git-backed worktree**

```powershell
git add frontend/src/views/knowledge/KnowledgeWorkbench.vue frontend/tests/knowledgeSidebar.test.mjs
git commit -m "feat: improve knowledge member configuration"
```

### Task 6: Documentation, motion review, and full verification

**Files:**
- Modify: `docs/api-reference.md`
- Modify: `docs/database.md`
- Modify: `docs/module-notes.md`

- [ ] **Step 1: Update API and database documentation with exact contracts**

Document:

```text
POST /api/knowledge/libraries
  category: company | department | personal (required)

GET /api/knowledge/libraries/{library_id}/member-candidates?q=&limit=20
  permission: knowledge:admin plus library admin
  response item: { user_id, username, real_name }

GET /api/knowledge/libraries/{library_id}/members
  response item: { user_id, username, real_name, role }
```

Add `category VARCHAR(16) NOT NULL` to the documented `ark_knowledge_libraries` columns, including the three allowed values and the existing-row `company` backfill.

- [ ] **Step 2: Record the stable UX contract in module notes**

Under the enterprise knowledge-base section, state that search is first in the collapsible sidebar, create and approval are adjacent, member configuration is per library and username-based, classification is company/department/personal, and overflow tooltips only appear for truncated names.

- [ ] **Step 3: Run fresh backend verification**

Run from `backend/`:

```powershell
python -m pytest tests/test_knowledge_migration.py tests/test_knowledge_content.py tests/test_knowledge_service.py tests/test_knowledge_api.py tests/test_mcp_knowledge.py -q
```

Expected: all selected tests pass with zero failures.

- [ ] **Step 4: Run fresh frontend verification**

Run from `frontend/`:

```powershell
node --test tests/knowledgeSidebar.test.mjs tests/knowledgeEditor.test.mjs tests/knowledgeState.test.mjs
npm run build
```

Expected: all Node tests pass and Vite exits 0 with a production `dist` build.

- [ ] **Step 5: Run repository convention checks**

Run from the repository root:

```powershell
python scripts/check_conventions.py
```

Expected: no red violations. If the snapshot's missing Git metadata prevents diff-based checks, report that exact limitation and still run the non-diff checks the script supports.

- [ ] **Step 6: Review motion code against the project standard**

Inspect every changed `transition`, `:hover`, `:active`, and reduced-motion rule. The review must confirm:

```text
- no transition: all
- no width/grid-template-columns animation
- no ease-in
- UI feedback <= 160ms
- hover rules gated by hover:hover and pointer:fine
- prefers-reduced-motion removes transform feedback
- tooltips and press feedback do not block interaction
```

- [ ] **Step 7: Perform browser QA on the real page**

Verify at minimum:

```text
1. Search is the top-most expanded-sidebar control and still finds published content.
2. New library and approval queue are adjacent and correctly permission-gated.
3. Member permission opens from the clicked library row and names that library in the title.
4. Username search returns only active Ark users and saves the intended roles.
5. Company/department/personal icons are gold/blue/green and have textual tooltips.
6. Directory/document create buttons differ in shape and color.
7. Long library, folder, and document names show full text only when truncated.
8. Collapse to 54px and restore to 310px persists across reload.
9. Keyboard focus, touch behavior, and reduced-motion remain usable.
```

- [ ] **Step 8: Request an independent adversarial review**

Have a separate reviewer inspect data backfill, member enumeration authorization, inactive-user validation, duplicate handling, frontend/backend payload consistency, truncation measurement cleanup, and collapsed-state accessibility. Fix every confirmed high- or medium-impact finding and rerun Steps 3–5.

- [ ] **Step 9: Commit documentation/final fixes in a Git-backed worktree**

```powershell
git add docs/api-reference.md docs/database.md docs/module-notes.md
git commit -m "docs: record knowledge sidebar contracts"
```

