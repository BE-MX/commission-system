# Disable Festival Popups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove every event popup from all five procurement-festival boards while preserving the event feed and 30-second page rotation.

**Architecture:** Detach the shared popup module at each static HTML entry point, then delete the now-unreferenced JavaScript and CSS assets. Keep backend event generation and the summary page's inline event-feed rendering unchanged.

**Tech Stack:** Static HTML, vanilla JavaScript, CSS, Vite frontend build

---

### Task 1: Remove popup integration

**Files:**
- Modify: `frontend/public/festival/zhaiyao.html`
- Modify: `frontend/public/festival/xinqian.html`
- Modify: `frontend/public/festival/fugou.html`
- Modify: `frontend/public/festival/zhenying.html`
- Modify: `frontend/public/festival/tuandui.html`
- Delete: `frontend/public/festival/assets/festival-popup.js`
- Delete: `frontend/public/festival/assets/festival-popup.css`
- Modify: `backend/app/festival/notification_service.py`
- Modify: `backend/tests/test_festival_notifications.py`

- [x] **Step 1: Record the current popup references**

Run `rg -n "festival-popup|FestivalPopup|L4 全屏回放卡|共享弹窗" frontend/public/festival -g "*.html"`.

Expected: each board contains shared CSS/JS references and popup-aware navigation; the summary page also contains popup-specific comments.

- [x] **Step 2: Remove the shared module and simplify navigation**

In each board, remove:

```html
<link rel="stylesheet" href="assets/festival-popup.css">
<script src="assets/festival-popup.js"></script>
```

Replace the popup-aware navigation expression in each file with its existing fixed destination:

```javascript
// zhaiyao.html
setTimeout(() => { location.href = "xinqian.html" + location.search; }, 30000);

// xinqian.html
setTimeout(() => { location.href = "fugou.html" + location.search; }, 30000);

// fugou.html
setTimeout(() => { location.href = "zhenying.html" + location.search; }, 30000);

// zhenying.html
setTimeout(() => { location.href = "tuandui.html" + location.search; }, 30000);

// tuandui.html
setTimeout(() => { location.href = "zhaiyao.html" + location.search; }, 30000);
```

Update the summary-page comments so they describe only the retained event feed and fixed 30-second rotation.

- [x] **Step 3: Delete the unused popup assets**

Delete `frontend/public/festival/assets/festival-popup.js` and `frontend/public/festival/assets/festival-popup.css` using `apply_patch`.

Remove the obsolete `popup=0` query argument from screenshot URLs and replace the old popup-controller tests with assertions that popups are absent, rotation remains intact, and the summary event feed is preserved.

- [x] **Step 4: Verify no popup integration remains**

Run `rg -n "festival-popup|FestivalPopup|L4 全屏回放卡|共享弹窗" frontend/public/festival`.

Expected: no matches.

Run `rg -n "subjectIcon|renderEvents|popup_events|setTimeout.*location.href" frontend/public/festival -g "*.html"`.

Expected: the summary event-feed functions and API event data remain; all five pages retain timed navigation.

### Task 2: Validate the frontend change

**Files:**
- Verify: `frontend/public/festival/`
- Verify: repository convention diff

- [x] **Step 1: Build the frontend**

Run `npm run build` from `frontend`.

Expected: Vite exits with code 0 and emits the production bundle.

- [x] **Step 2: Run convention checks**

Run `python scripts/check_conventions.py` from the repository root.

Expected: no red violations caused by this diff.

- [x] **Step 3: Inspect the final diff**

Run `git diff --check`, then inspect `git diff -- frontend/public/festival docs/superpowers/specs/2026-08-31-disable-festival-popups-design.md docs/superpowers/plans/2026-08-31-disable-festival-popups.md`.

Expected: no whitespace errors; only popup integration, obsolete comments/assets, and the two task documents changed.

- [x] **Step 4: Commit from the Codex worktree**

Verify `git branch --show-current` returns `codex/disable-festival-popups`, then commit only this task's files with `git commit -m "fix: disable procurement festival popups"`.
