# Knowledge Editor P0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the existing knowledge editor POC with the approved P0 Yuque-style editing interactions while preserving the current revision and permission model.

**Architecture:** Keep `KnowledgeEditor.vue` as the coordinator and move command metadata, toolbar, slash menu, and outline into focused units. Reuse the installed Tiptap v3 stack and add only the list extension needed for task lists; all persisted JSON must remain accepted by the backend allowlist.

**Tech Stack:** Vue 3, Element Plus, Tiptap 3.29, Node test runner, Vite.

---

### Task 1: Editor behavior contract

**Files:**
- Create: `frontend/src/views/knowledge/components/editorConfig.js`
- Create: `frontend/tests/knowledgeEditor.test.mjs`

- [ ] Write failing tests for slash command filtering, heading outline extraction, and save-state labels.
- [ ] Run `node --test tests/knowledgeEditor.test.mjs` and confirm failures are caused by missing exports.
- [ ] Implement the minimal pure functions and command catalog.
- [ ] Re-run the focused test and commit with `test(knowledge): define editor p0 behavior`.

### Task 2: Editing controls

**Files:**
- Create: `frontend/src/views/knowledge/components/EditorToolbar.vue`
- Create: `frontend/src/views/knowledge/components/EditorSlashMenu.vue`
- Modify: `frontend/src/views/knowledge/components/KnowledgeEditor.vue`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`

- [ ] Extend the failing source-contract test to require toolbar groups, slash menu keyboard controls, link editing, table commands, task-list extensions, and accessible labels.
- [ ] Run the focused test and confirm the new assertions fail.
- [ ] Add `@tiptap/extension-list`, implement both components, and wire them to the editor.
- [ ] Re-run the focused test and commit with `feat(knowledge): add rich editing controls`.

### Task 3: Outline and save feedback

**Files:**
- Create: `frontend/src/views/knowledge/components/EditorOutline.vue`
- Modify: `frontend/src/views/knowledge/components/KnowledgeEditor.vue`
- Modify: `frontend/src/views/knowledge/KnowledgeWorkbench.vue`
- Modify: `frontend/tests/knowledgeEditor.test.mjs`

- [ ] Add failing assertions for live outline, heading navigation, dirty/saving/saved/error states, and save completion callbacks.
- [ ] Run the focused test and confirm the assertions fail.
- [ ] Implement outline extraction/navigation and propagate save success/failure into the editor state without adding autosave.
- [ ] Re-run the focused test and commit with `feat(knowledge): add outline and save feedback`.

### Task 4: Verification

**Files:**
- Modify only files required by failures introduced by this feature.

- [ ] Run `node --test tests/knowledgeEditor.test.mjs tests/knowledgeState.test.mjs`.
- [ ] Run `npm run build`.
- [ ] Run `python scripts/check_conventions.py --base $(git merge-base main HEAD)` using the PowerShell equivalent for the merge-base value.
- [ ] Inspect `git diff --check`, `git status --short`, and the final scoped diff.
