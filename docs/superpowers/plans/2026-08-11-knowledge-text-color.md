# Knowledge Text Color Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a controlled five-option text-color picker to the enterprise knowledge editor while persisting only four semantic color tones.

**Architecture:** A custom Tiptap `textColor` mark stores semantic tone names instead of CSS values. A focused picker component owns toolbar interaction, while the backend content validator enforces the same finite tone contract and rejects arbitrary attributes.

**Tech Stack:** Vue 3, Tiptap 3.29, Element Plus design tokens, FastAPI, Python, pytest, Node test runner.

---

## File Map

- Create `frontend/src/views/knowledge/components/TextColorMark.js`: one source of truth for tone options, safe HTML parsing/rendering, and editor commands.
- Create `frontend/src/views/knowledge/components/TextColorPicker.vue`: accessible toolbar trigger and five-option popover.
- Modify `frontend/src/views/knowledge/components/EditorToolbar.vue`: compose the picker in the existing text-format group.
- Modify `frontend/src/views/knowledge/components/KnowledgeEditor.vue`: register the mark and map semantic classes to design tokens.
- Modify `frontend/tests/knowledgeEditor.test.mjs`: verify mark contract, command wiring, toolbar integration, accessibility, and bounded motion.
- Modify `backend/app/knowledge/content.py`: allow and validate the semantic `textColor` mark.
- Modify `backend/tests/test_knowledge_content.py`: cover accepted and rejected tone payloads.
- Modify `docs/module-notes.md`: document the editor color contract and deployment status.

### Task 1: Backend content contract

**Files:**
- Modify: `backend/tests/test_knowledge_content.py`
- Modify: `backend/app/knowledge/content.py`

- [ ] **Step 1: Add failing acceptance and rejection tests**

Add a document whose text has `{"type": "textColor", "attrs": {"tone": "gold"}}`, assert validation returns it unchanged, and assert text extraction ignores the visual mark. Add parameterized invalid cases for missing tone, `tone="purple"`, and an extra `style` attribute.

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_knowledge_content.py -q`

Expected: the accepted `textColor` case fails with `ContentValidationError: unsupported mark`.

- [ ] **Step 3: Implement the minimal validator contract**

Add `textColor` to `_ALLOWED_MARKS`. In `_validate_marks`, accept only an attrs object with exactly the `tone` key and a value in `{"gold", "danger", "success", "info"}`. Preserve all existing link and attribute rejection behavior.

- [ ] **Step 4: Run the focused test and confirm GREEN**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_knowledge_content.py -q`

Expected: all content-validation tests pass.

### Task 2: Semantic Tiptap mark

**Files:**
- Create: `frontend/src/views/knowledge/components/TextColorMark.js`
- Modify: `frontend/tests/knowledgeEditor.test.mjs`

- [ ] **Step 1: Add failing mark-contract tests**

Import the planned exports and assert:

```js
assert.deepEqual(TEXT_COLOR_OPTIONS.map(item => item.tone), [null, 'gold', 'danger', 'success', 'info'])
assert.equal(normalizeTextColorTone('gold'), 'gold')
assert.equal(normalizeTextColorTone('#ff0000'), null)
```

Use a small fake editor chain to prove `applyTextColor(editor, 'gold')` calls `setMark('textColor', { tone: 'gold' })`, while `applyTextColor(editor, null)` calls `unsetMark('textColor')`.

- [ ] **Step 2: Run the frontend test and confirm RED**

Run: `cd frontend && node --test tests/knowledgeEditor.test.mjs`

Expected: module-not-found for `TextColorMark.js`.

- [ ] **Step 3: Implement the custom mark**

Export a frozen five-option array containing labels and CSS-variable references, a tone normalizer, the editor command helper, and `TextColorMark`. Parse only `span[data-text-color]`; return `false` for unregistered values. Render registered values as `data-text-color` plus a fixed `knowledge-text-color--<tone>` class. Do not parse `style="color"`.

- [ ] **Step 4: Run the frontend test and confirm GREEN**

Run: `cd frontend && node --test tests/knowledgeEditor.test.mjs`

Expected: all current and new mark-contract tests pass.

### Task 3: Accessible picker and toolbar wiring

**Files:**
- Create: `frontend/src/views/knowledge/components/TextColorPicker.vue`
- Modify: `frontend/src/views/knowledge/components/EditorToolbar.vue`
- Modify: `frontend/tests/knowledgeEditor.test.mjs`

- [ ] **Step 1: Add failing integration assertions**

Assert the picker source contains `aria-haspopup="menu"`, `:aria-expanded`, `role="menu"`, `role="menuitemradio"`, Chinese option labels, Escape handling, outside-pointer handling, and `prefers-reduced-motion`. Assert `EditorToolbar.vue` imports and renders `TextColorPicker` with both `editor` and `version`.

- [ ] **Step 2: Run the frontend test and confirm RED**

Run: `cd frontend && node --test tests/knowledgeEditor.test.mjs`

Expected: missing picker file or missing toolbar integration assertion.

- [ ] **Step 3: Implement the picker**

The component reads the active tone from `editor.getAttributes('textColor')`, shows it as the trigger underline, and invokes `applyTextColor`. Use `mousedown.prevent` for editor-selection preservation. Maintain a local `open` ref, close on Escape and document pointerdown outside the component, remove listeners on unmount, and expose visible labels next to every swatch.

- [ ] **Step 4: Wire it into the text-format group**

Import `TextColorPicker` in `EditorToolbar.vue` and render it after the link button. Extend shared toolbar selectors so the trigger matches existing 30px controls without introducing raw hex colors or `transition: all`.

- [ ] **Step 5: Run the frontend test and confirm GREEN**

Run: `cd frontend && node --test tests/knowledgeEditor.test.mjs`

Expected: all editor tests pass.

### Task 4: Editor registration and persisted rendering

**Files:**
- Modify: `frontend/src/views/knowledge/components/KnowledgeEditor.vue`
- Modify: `frontend/tests/knowledgeEditor.test.mjs`

- [ ] **Step 1: Add failing editor-registration assertions**

Assert `KnowledgeEditor.vue` imports `TextColorMark`, registers it in `extensions`, and maps the four rendered classes to `--color-primary`, `--color-danger-text`, `--color-success-text`, and `--color-info-text`.

- [ ] **Step 2: Run the frontend test and confirm RED**

Run: `cd frontend && node --test tests/knowledgeEditor.test.mjs`

Expected: missing mark registration and semantic class styles.

- [ ] **Step 3: Register and style the mark**

Add `TextColorMark` to the editor extensions. Add four scoped `:deep(.knowledge-text-color--...)` rules using design tokens only. Do not add arbitrary inline colors or a new package.

- [ ] **Step 4: Run the frontend test and confirm GREEN**

Run: `cd frontend && node --test tests/knowledgeEditor.test.mjs`

Expected: all editor tests pass.

### Task 5: Documentation and focused regression

**Files:**
- Modify: `docs/module-notes.md`

- [ ] **Step 1: Document the behavior**

Under the enterprise knowledge editor section, state that font colors use semantic `textColor` tones, external arbitrary colors are stripped, the backend rejects unknown tones, and no migration is required. Mark the feature as local until the normal deploy path is run.

- [ ] **Step 2: Run focused regressions**

Run:

```powershell
cd backend
.venv\Scripts\python.exe -m pytest tests/test_knowledge_content.py tests/test_knowledge_api.py tests/test_knowledge_service.py -q
cd ..\frontend
node --test tests/knowledgeEditor.test.mjs
```

Expected: all selected tests pass.

### Task 6: Full verification and interaction audit

**Files:**
- Verify all files above; no additional production files are expected.

- [ ] **Step 1: Run full automated gates**

Run:

```powershell
cd backend
.venv\Scripts\python.exe -m pytest -q
cd ..\frontend
npm run build
cd ..
python scripts/check_conventions.py
git diff --check
```

Expected: backend suite passes, frontend production build exits 0, convention check reports no violations, and diff check reports no whitespace errors.

- [ ] **Step 2: Review motion against the loaded animation standards**

Verify hover styles are pointer-capability gated, the trigger uses only the existing 120ms press feedback, focus does not scale, no entrance animation was added, and reduced-motion removes transform feedback.

- [ ] **Step 3: Verify the real local interaction**

In the running local app, verify selection coloring, collapsed-caret subsequent typing, default-color removal, coexistence with bold and links, save plus refresh persistence, and stripping of pasted external inline colors. Inspect the saved request JSON to confirm only semantic tones are sent.

- [ ] **Step 4: Audit the final diff**

Confirm every changed line belongs to either the previous table-alignment bug fix or this text-color feature, no generated `.superpowers/` brainstorming files are staged, no raw secrets appear, and no deployment or push was performed.
