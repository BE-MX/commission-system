# Knowledge Deletion and Dirty-State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add authorized soft deletion for knowledge libraries and node subtrees while eliminating false unsaved-change prompts during document hydration and save refreshes.

**Architecture:** Extend the existing knowledge service with two atomic soft-delete operations that reuse current ACL checks, cancel pending approvals, and write aggregate audit records. Keep user navigation guarded in the workbench, but introduce an unguarded server-refresh path and use the Tiptap v3 hydration API so programmatic content updates never mark the editor dirty.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, pytest, Vue 3, Element Plus, Tiptap v3, Node test runner, Vite 5.

---

### Task 1: Knowledge service soft deletion

**Files:**
- Modify: `backend/tests/test_knowledge_service.py`
- Modify: `backend/app/knowledge/service.py`

- [ ] **Step 1: Write failing service tests**

Add tests that create a folder subtree with documents and a pending approval, then assert `delete_node` sets `deleted_at` on every descendant, changes the approval to `cancelled`, clears `pending_slot`, and records one aggregate audit event. Add a library test that asserts `delete_library` hides the library from `list_libraries`. Add permission tests asserting editor can delete nodes but viewer cannot, and only a library admin can delete a library.

- [ ] **Step 2: Verify RED**

Run:

```powershell
$env:PYTHONPATH='D:\MyProgram\commission-system\backend\.venv\Lib\site-packages;.'
& 'C:\Users\windb\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_knowledge_service.py -q
```

Expected: failures because `service.delete_node` and `service.delete_library` do not exist.

- [ ] **Step 3: Implement minimal service operations**

Add helpers that collect descendants by `parent_id`, cancel pending approvals, apply one Beijing-time deletion timestamp, and return:

```python
{
    "id": target_id,
    "folder_count": folder_count,
    "document_count": document_count,
    "cancelled_approval_count": cancelled_count,
}
```

`delete_node` must call `_require_platform(..., "knowledge:write")` and `_document(..., "write")`. `delete_library` must call `_require_platform(..., "knowledge:admin")` and `_library(..., "admin")`. Commit once after the audit entry is appended.

- [ ] **Step 4: Verify GREEN**

Run the Task 1 pytest command and expect all service tests to pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/knowledge/service.py backend/tests/test_knowledge_service.py
git commit -m "feat(knowledge): add soft deletion services"
```

### Task 2: Delete API contracts and documentation

**Files:**
- Modify: `backend/tests/test_knowledge_api.py`
- Modify: `backend/app/knowledge/router.py`
- Modify: `docs/api-reference.md`

- [ ] **Step 1: Write failing endpoint tests**

Add API tests for:

```text
DELETE /api/knowledge/libraries/{library_id}
DELETE /api/knowledge/documents/{document_id}
```

Assert the response envelope contains the affected-count summary and a subsequent GET returns 404. Override identities to prove platform and resource ACLs both apply.

- [ ] **Step 2: Verify RED**

Run:

```powershell
$env:PYTHONPATH='D:\MyProgram\commission-system\backend\.venv\Lib\site-packages;.'
& 'C:\Users\windb\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_knowledge_api.py -q
```

Expected: 405 Method Not Allowed for the new DELETE routes.

- [ ] **Step 3: Add the two router handlers**

Use `require_permission("knowledge:admin")` for library deletion and `require_any_permission(*WRITE)` for node deletion. Call the service through `_call` and return `ok(summary)`.

- [ ] **Step 4: Document both endpoints**

Add the request paths, permissions, soft-delete behavior, cascade behavior, approval cancellation, and response summary to the knowledge section of `docs/api-reference.md`.

- [ ] **Step 5: Verify GREEN and commit**

Run the Task 2 pytest command, then:

```powershell
git add backend/app/knowledge/router.py backend/tests/test_knowledge_api.py docs/api-reference.md
git commit -m "feat(knowledge): expose delete endpoints"
```

### Task 3: Correct dirty-state transitions

**Files:**
- Modify: `frontend/tests/knowledgeEditor.test.mjs`
- Modify: `frontend/src/views/knowledge/components/KnowledgeEditor.vue`
- Modify: `frontend/src/views/knowledge/KnowledgeWorkbench.vue`

- [ ] **Step 1: Write failing frontend regression tests**

Assert source behavior requires:

```javascript
editor.value?.commands.setContent(content, { emitUpdate: false })
```

Assert `selectDocument` returns immediately for the current ID, calls `allowDiscard` only for user navigation, and save calls `reloadDocument` rather than guarded `selectDocument`.

- [ ] **Step 2: Verify RED**

Run:

```powershell
node --test tests/knowledgeEditor.test.mjs tests/knowledgeState.test.mjs
```

Expected: failures showing the obsolete boolean Tiptap option and guarded save refresh.

- [ ] **Step 3: Implement the minimal state-flow correction**

In `KnowledgeEditor.vue`, use the v3 options object for hydration. In `KnowledgeWorkbench.vue`, add `reloadDocument(id)` that only fetches and assigns the document. Keep `selectDocument(id)` as the guarded user action, skip it when the ID is already open, and use `reloadDocument` in save/submit/approval refreshes.

- [ ] **Step 4: Verify GREEN and commit**

Run the Task 3 Node tests, then:

```powershell
git add frontend/src/views/knowledge/KnowledgeWorkbench.vue frontend/src/views/knowledge/components/KnowledgeEditor.vue frontend/tests/knowledgeEditor.test.mjs
git commit -m "fix(knowledge): correct dirty state transitions"
```

### Task 4: Add deletion controls and workflows

**Files:**
- Modify: `frontend/tests/knowledgeEditor.test.mjs`
- Modify: `frontend/src/views/knowledge/knowledgeState.js`
- Modify: `frontend/src/views/knowledge/components/KnowledgeSidebar.vue`
- Modify: `frontend/src/views/knowledge/components/KnowledgeEditor.vue`
- Modify: `frontend/src/views/knowledge/KnowledgeWorkbench.vue`

- [ ] **Step 1: Write failing role and interaction tests**

Extend capability assertions so only `editor` and `admin` expose node deletion and only `admin` exposes library deletion. Assert sidebar delete events stop propagation, the document header exposes delete for `canDelete`, and workbench handlers call the corresponding DELETE endpoints and reset selected state.

- [ ] **Step 2: Verify RED**

Run the Task 3 Node command and expect failures for missing capabilities, events, and handlers.

- [ ] **Step 3: Implement role capabilities and sidebar controls**

Add `deleteNode` and `deleteLibrary` capability flags derived from existing roles. Add accessible icon buttons with explicit tooltips and `@click.stop`; keep them visible on keyboard focus and reveal them on hover for pointer devices.

- [ ] **Step 4: Implement confirmation and post-delete flows**

Use `ElMessageBox.confirm` with the target name and cascade warning. Call the DELETE endpoint only after confirmation. Refresh tree/libraries, clear the open document when it was directly or indirectly deleted, select the first remaining library after library deletion, and show affected node counts with `msgSuccess`.

- [ ] **Step 5: Verify GREEN and commit**

Run the Task 3 Node command, then:

```powershell
git add frontend/src/views/knowledge frontend/tests/knowledgeEditor.test.mjs
git commit -m "feat(knowledge): add delete controls"
```

### Task 5: Final verification

**Files:**
- Verify only; modify production files only if a failing check identifies an in-scope defect.

- [ ] **Step 1: Run focused backend tests**

```powershell
$env:PYTHONPATH='D:\MyProgram\commission-system\backend\.venv\Lib\site-packages;.'
& 'C:\Users\windb\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_knowledge_service.py tests/test_knowledge_api.py tests/test_mcp_knowledge.py -q
```

- [ ] **Step 2: Run focused frontend tests**

```powershell
node --test tests/knowledgeEditor.test.mjs tests/knowledgeState.test.mjs
```

- [ ] **Step 3: Install and build frontend**

```powershell
npm ci
npm run build
```

- [ ] **Step 4: Run repository convention checks**

```powershell
& 'C:\Users\windb\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' scripts/check_conventions.py --base f933ebd2b6a068563dba853ede7d13386d739499
git diff --check
```

- [ ] **Step 5: Review destructive interaction motion**

Confirm no new entrance animation, no `transition: all`, hover movement is pointer-gated, press feedback is under 300ms, and reduced-motion behavior remains intact.
