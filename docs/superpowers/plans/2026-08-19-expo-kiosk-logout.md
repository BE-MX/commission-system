# Expo Kiosk Logout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a discoverable, confirmation-protected logout button to the `/expo/kiosk` home screen.

**Architecture:** Keep the change inside `ExpoKiosk.vue` and reuse the existing Pinia `authStore.logout()` flow. Add a source-contract Node test matching the frontend test suite's established pattern so the button visibility, confirmation gate, and auth delegation remain protected without introducing a new UI test dependency.

**Tech Stack:** Vue 3 `<script setup>`, Pinia, Node.js built-in test runner, Vite 5.

---

## File Map

- Create `frontend/tests/expoKioskLogout.test.mjs`: verifies the kiosk-only logout UI and delegation contract.
- Modify `frontend/src/views/expo/ExpoKiosk.vue`: renders the home-only button, confirmation dialog, and existing auth-store call.

### Task 1: Add the kiosk logout flow with TDD

**Files:**
- Create: `frontend/tests/expoKioskLogout.test.mjs`
- Modify: `frontend/src/views/expo/ExpoKiosk.vue`

- [ ] **Step 1: Write the failing source-contract tests**

Create `frontend/tests/expoKioskLogout.test.mjs`:

```js
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../src/views/expo/ExpoKiosk.vue', import.meta.url), 'utf8')

test('kiosk shows logout only on the attract home screen', () => {
  assert.match(
    source,
    /<button\s+v-if="flow\.step\.value === 'attract'"\s+class="xk-nav"\s+@click="requestLogout">退出登录<\/button>/,
  )
})

test('kiosk requires confirmation before delegating to the auth store', () => {
  assert.match(source, /import \{ useAuthStore \} from '@\/stores\/auth'/)
  assert.match(source, /const authStore = useAuthStore\(\)/)
  assert.match(source, /<div v-if="logoutConfirm" class="xk-confirm"/)
  assert.match(source, /退出后需要重新输入展会设备账号才能继续使用/)
  assert.match(source, /class="xk-btn ghost" @click="logoutConfirm = false">取消<\/button>/)
  assert.match(source, /class="xk-btn" @click="confirmLogout">退出登录<\/button>/)
  assert.match(source, /function requestLogout\(\) \{[\s\S]*?logoutConfirm\.value = true[\s\S]*?\}/)
  assert.match(source, /async function confirmLogout\(\) \{[\s\S]*?logoutConfirm\.value = false[\s\S]*?await authStore\.logout\(\)[\s\S]*?\}/)
})

test('logout confirmation reuses the bounded kiosk modal motion', () => {
  assert.match(source, /<Transition name="xconfirm">[\s\S]*?<div v-if="logoutConfirm"/)
  assert.doesNotMatch(source, /transition:\s*all/)
})
```

- [ ] **Step 2: Run the test and verify the RED state**

Run:

```powershell
node --test frontend/tests/expoKioskLogout.test.mjs
```

Expected: three failures because the logout button, confirmation state, and auth-store delegation do not exist yet.

- [ ] **Step 3: Implement the minimum Vue change**

In `frontend/src/views/expo/ExpoKiosk.vue`:

1. Add the home-only button after the quota label and before the step label:

```vue
<button
  v-if="flow.step.value === 'attract'"
  class="xk-nav"
  @click="requestLogout"
>退出登录</button>
```

2. Add a second `xconfirm` dialog after the existing return-home confirmation:

```vue
<Transition name="xconfirm">
  <div v-if="logoutConfirm" class="xk-confirm" @click.self="logoutConfirm = false">
    <div class="xk-confirm-panel" role="dialog" aria-modal="true" aria-labelledby="logout-confirm-title">
      <div id="logout-confirm-title" class="xc-title">确认退出登录？</div>
      <div class="xc-sub">退出后需要重新输入展会设备账号才能继续使用</div>
      <div class="xc-actions">
        <button class="xk-btn ghost" @click="logoutConfirm = false">取消</button>
        <button class="xk-btn" @click="confirmLogout">退出登录</button>
      </div>
    </div>
  </div>
</Transition>
```

3. Import and use the existing store, then add the confirmation state and handlers:

```js
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const logoutConfirm = ref(false)

function requestLogout() {
  logoutConfirm.value = true
  flow.touch()
}

async function confirmLogout() {
  logoutConfirm.value = false
  await authStore.logout()
}
```

Do not add a backend endpoint, a new component, a new animation, or fallback authentication behavior.

- [ ] **Step 4: Run focused tests and verify the GREEN state**

Run:

```powershell
node --test frontend/tests/expoKioskLogout.test.mjs
```

Expected: `3` tests pass, `0` fail.

- [ ] **Step 5: Run project verification**

Run:

```powershell
npm run build --prefix frontend
python scripts/check_conventions.py
git diff --check
```

Expected: build exits `0`, convention check reports no red items, and `git diff --check` returns no output.

- [ ] **Step 6: Review motion and responsive behavior**

Check the diff against the kiosk motion standards:

- no `transition: all`;
- the frequent logout button has only existing press feedback;
- the occasional confirmation reuses the existing sub-300ms asymmetric modal transition;
- reduced-motion behavior remains inherited from `xconfirm`;
- at `390px` width the button appears only on `attract`, where the back/home controls are absent.

- [ ] **Step 7: Commit the implementation**

```powershell
git add -- frontend/tests/expoKioskLogout.test.mjs frontend/src/views/expo/ExpoKiosk.vue
git branch --show-current
git commit -m "feat(expo): add kiosk logout action"
```

### Task 2: Integrate, deploy, and verify

**Files:** None beyond generated `frontend/dist` artifacts, which remain untracked.

- [ ] **Step 1: Verify the feature branch one final time**

```powershell
node --test frontend/tests/expoKioskLogout.test.mjs
npm run build --prefix frontend
python scripts/check_conventions.py --base (git merge-base main HEAD)
```

- [ ] **Step 2: Merge from the primary worktree and push `main`**

From `D:\MyProgram\commission-system`, confirm the checked-out branch is `main`, fast-forward merge `codex/expo-kiosk-logout`, then push `main` to `origin` and `cloud`. Preserve all unrelated untracked files in the primary worktree.

- [ ] **Step 3: Deploy the built frontend**

From the merged `main`, build again and follow the runbook's frontend deployment path:

```powershell
npm run build --prefix frontend
tar czf - -C frontend dist | ssh ubuntu@154.8.205.162 "cd /tmp && tar xzf - && sudo rsync -a --delete dist/ /var/www/ark-dist/ && rm -rf /tmp/dist"
```

- [ ] **Step 4: Live-verify the kiosk asset**

Fetch `https://154.8.205.162/expo/kiosk`, resolve its current ExpoKiosk JavaScript chunk, and confirm the deployed chunk contains the new logout copy. Confirm the route returns HTTP `200`; do not attempt to log out the shared production device session remotely.

- [ ] **Step 5: Clean up the merged feature branch/worktree**

After the merged result and live deployment verify successfully, remove the temporary worktree and delete the local feature branch. Do not delete or modify unrelated files in the primary worktree.
