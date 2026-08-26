# Customer Image Portal Bilingual UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every system-controlled string on the public customer image portal default to English and switch instantly to Chinese, while preserving the existing generation workflow and backend-configured business text.

**Architecture:** Add a portal-local English/Chinese message catalog with pure normalization/interpolation helpers and a Vue provide/inject wrapper. Store UI status as stable `{ key, params }` message descriptors so an already-visible error or generation status retranslates when locale changes. Keep language out of API payloads and keep product/category/option content untouched.

**Tech Stack:** Vue 3 Composition API, Vite 5, Node test runner, existing scoped CSS design tokens

---

## File map

- Create `frontend/src/views/customer-image/i18n.js`: catalog, locale persistence, message descriptors, translation helpers, Vue provider/inject lifecycle.
- Create `frontend/src/views/customer-image/components/LanguageSwitcher.vue`: accessible `EN / 中文` segmented control.
- Create `frontend/tests/customerImageI18n.test.mjs`: default, persistence, interpolation, fallback, and message-descriptor tests.
- Modify `frontend/src/views/customer-image/state.js`: return message descriptors instead of rendered Chinese status strings.
- Modify `frontend/src/views/customer-image/composables/useCustomerImagePortal.js`: use message descriptors for notices, errors, announcements, and safe error mapping.
- Modify `frontend/src/views/customer-image/CustomerImagePortal.vue`: install the provider, render the switcher in every state, translate shell/state messages, and synchronize translated props.
- Modify `frontend/src/views/customer-image/CustomerProductCatalog.vue`: translate catalog UI while leaving product data raw.
- Modify `frontend/src/views/customer-image/CustomerProductEditor.vue`: translate editor UI and render descriptor props.
- Modify `frontend/src/views/customer-image/components/CustomerLogoUpload.vue`: translate upload UI.
- Modify `frontend/src/views/customer-image/components/ProductOptionGroup.vue`: translate only system text (`Required`, boolean yes/no).
- Modify `frontend/src/views/customer-image/components/GenerationPreview.vue`: translate preview/status/accessibility UI.
- Modify `frontend/src/views/customer-image/components/GenerationHistory.vue`: translate history/status UI.
- Modify focused customer-image tests to assert message keys and bilingual coverage without changing workflow assertions.

### Task 1: Portal-local language runtime

**Files:**
- Create: `frontend/src/views/customer-image/i18n.js`
- Create: `frontend/tests/customerImageI18n.test.mjs`

- [ ] **Step 1: Write failing pure-function tests**

Cover these exact contracts:

```js
assert.equal(normalizeCustomerImageLocale(undefined), 'en')
assert.equal(normalizeCustomerImageLocale('zh-CN'), 'zh-CN')
assert.equal(normalizeCustomerImageLocale('fr'), 'en')
assert.equal(readCustomerImageLocale({ getItem: () => null }), 'en')
assert.equal(translateCustomerImage('en', 'quota.copy', { count: 3 }), 'This generation uses 1 credit. 3 remaining.')
assert.equal(translateCustomerImage('zh-CN', 'quota.copy', { count: 3 }), '本次生成将使用 1 次额度，剩余 3 次')
assert.deepEqual(customerImageMessage('status.completed', { product: 'Box' }), {
  key: 'status.completed', params: { product: 'Box' },
})
```

- [ ] **Step 2: Run the test and confirm the module is missing**

Run: `cd frontend && node --test tests/customerImageI18n.test.mjs`

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `views/customer-image/i18n.js`.

- [ ] **Step 3: Implement the language catalog and pure helpers**

Create `i18n.js` with:

```js
export const CUSTOMER_IMAGE_LOCALE_KEY = 'ark_customer_image_locale'
export const CUSTOMER_IMAGE_LOCALES = ['en', 'zh-CN']

export function normalizeCustomerImageLocale(value) {
  return CUSTOMER_IMAGE_LOCALES.includes(value) ? value : 'en'
}

export function customerImageMessage(key, params = {}) {
  return { key, params }
}

export function translateCustomerImage(locale, key, params = {}) {
  const template = MESSAGES[normalizeCustomerImageLocale(locale)]?.[key]
    ?? MESSAGES.en[key]
    ?? key
  return template.replace(/\{(\w+)\}/g, (_, name) => String(params[name] ?? ''))
}
```

Add English and Chinese entries for every fixed string enumerated in design section 4. `readCustomerImageLocale(storage)` must catch storage errors and return `en`; `writeCustomerImageLocale(storage, locale)` must catch errors and not throw.

Add `provideCustomerImageI18n()` and `useCustomerImageI18n()` using Vue `ref/provide/inject/onMounted/onBeforeUnmount`. The provider exposes `locale`, `setLocale`, `t(key, params)`, and `tm(descriptor)`. On mount it sets `document.documentElement.lang`; on unmount it restores the previous value.

- [ ] **Step 4: Run the focused test**

Run: `cd frontend && node --test tests/customerImageI18n.test.mjs`

Expected: all tests PASS.

- [ ] **Step 5: Commit the runtime**

```bash
git add frontend/src/views/customer-image/i18n.js frontend/tests/customerImageI18n.test.mjs
git commit -m "Add customer image portal translations"
```

### Task 2: Stable translatable workflow messages

**Files:**
- Modify: `frontend/src/views/customer-image/state.js`
- Modify: `frontend/src/views/customer-image/composables/useCustomerImagePortal.js`
- Modify: `frontend/tests/customerImageState.test.mjs`
- Modify: `frontend/tests/customerImagePortalFlow.test.mjs`

- [ ] **Step 1: Change focused tests to require descriptors**

Replace rendered-string assertions with stable contracts such as:

```js
assert.deepEqual(generationStatusMessage('queued'), {
  key: 'generation.queued.detail', params: {},
})
assert.equal(portal.state.notice.key, 'settings.updated')
assert.deepEqual(portal.state.resultAnnouncement, {
  key: 'generation.completed.announcement', params: { product: '包装盒' },
})
```

Also assert that generation request payloads remain byte-for-byte independent of locale.

- [ ] **Step 2: Run focused tests and confirm the old string API fails**

Run: `cd frontend && node --test tests/customerImageState.test.mjs tests/customerImagePortalFlow.test.mjs`

Expected: FAIL because `generationStatusMessage` and descriptor-shaped state do not exist.

- [ ] **Step 3: Convert workflow UI state to message descriptors**

Import `customerImageMessage` and make `error`, `notice`, and `resultAnnouncement` nullable descriptors. Rename `generationStatusText(status)` to `generationStatusMessage(status)` and return keys:

```js
const STATUS_MESSAGES = {
  queued: 'generation.queued.detail',
  running: 'generation.running.detail',
  succeeded: 'generation.succeeded.detail',
  failed: 'generation.failed.detail',
}
return customerImageMessage(STATUS_MESSAGES[status] || 'generation.processing.detail')
```

Convert every composable assignment and `customerSafeError()` branch to descriptors. Dynamic completion uses `params: { product: completed.product_name || '' }`. Clearing a message uses `null`, not an empty string. Do not add `locale` to `createGeneration`, context, upload, or polling calls.

- [ ] **Step 4: Run focused workflow tests**

Run: `cd frontend && node --test tests/customerImageState.test.mjs tests/customerImagePortalFlow.test.mjs`

Expected: all tests PASS, including existing concurrency, idempotency, invalidation, and asset-cleanup cases.

- [ ] **Step 5: Commit workflow message changes**

```bash
git add frontend/src/views/customer-image/state.js frontend/src/views/customer-image/composables/useCustomerImagePortal.js frontend/tests/customerImageState.test.mjs frontend/tests/customerImagePortalFlow.test.mjs
git commit -m "Make customer portal messages locale reactive"
```

### Task 3: Always-available language switcher and portal shell

**Files:**
- Create: `frontend/src/views/customer-image/components/LanguageSwitcher.vue`
- Modify: `frontend/src/views/customer-image/CustomerImagePortal.vue`
- Modify: `frontend/tests/customerImageI18n.test.mjs`

- [ ] **Step 1: Add structural tests for accessibility and placement**

Read both Vue files as text and assert:

```js
assert.match(portal, /<LanguageSwitcher/)
assert.match(portal, /provideCustomerImageI18n/)
assert.match(switcher, /aria-pressed/)
assert.match(switcher, /min-height:\s*44px/)
assert.doesNotMatch(switcher, /transition:\s*all/)
```

- [ ] **Step 2: Run the test and confirm the component is missing**

Run: `cd frontend && node --test tests/customerImageI18n.test.mjs`

Expected: FAIL because `LanguageSwitcher.vue` is absent.

- [ ] **Step 3: Implement the switcher and shell translations**

The component renders two buttons from `[{ value: 'en', label: 'EN' }, { value: 'zh-CN', label: '中文' }]`, sets `aria-pressed`, and calls `setLocale(value)`. Use a 44px minimum target, a selected background state, `transform: scale(.97)` press feedback with `160ms cubic-bezier(0.23, 1, 0.32, 1)`, pointer-qualified hover, and reduced-motion handling.

In `CustomerImagePortal.vue`, call `provideCustomerImageI18n()` before `useCustomerImagePortal()`, render `<LanguageSwitcher />` as the first child so it exists in loading/error/ready states, and replace fixed strings with `t(...)`. Render composable descriptors through `tm(...)`. Keep the switcher above the sticky bar and reserve topbar room so it does not overlap status content; hide the redundant status pill on narrow screens if needed.

- [ ] **Step 4: Run the i18n structural tests**

Run: `cd frontend && node --test tests/customerImageI18n.test.mjs`

Expected: all tests PASS.

- [ ] **Step 5: Commit the portal shell**

```bash
git add frontend/src/views/customer-image/components/LanguageSwitcher.vue frontend/src/views/customer-image/CustomerImagePortal.vue frontend/tests/customerImageI18n.test.mjs
git commit -m "Add customer portal language switcher"
```

### Task 4: Translate catalog, editor, and child components

**Files:**
- Modify: `frontend/src/views/customer-image/CustomerProductCatalog.vue`
- Modify: `frontend/src/views/customer-image/CustomerProductEditor.vue`
- Modify: `frontend/src/views/customer-image/components/CustomerLogoUpload.vue`
- Modify: `frontend/src/views/customer-image/components/ProductOptionGroup.vue`
- Modify: `frontend/src/views/customer-image/components/GenerationPreview.vue`
- Modify: `frontend/src/views/customer-image/components/GenerationHistory.vue`
- Modify: `frontend/tests/customerImageI18n.test.mjs`
- Modify: `frontend/tests/customerImageResponsiveFlow.test.mjs`

- [ ] **Step 1: Add a fixed-copy coverage test**

Assert each component imports `useCustomerImageI18n`, fixed customer-facing Chinese literals are absent from templates/scripts except the switcher label `中文`, and known business data bindings remain raw:

```js
assert.match(catalog, /product\.name/)
assert.match(catalog, /product\.category/)
assert.match(editor, /:option="option"/)
assert.match(optionGroup, /option\.label/)
assert.match(optionGroup, /value\.label/)
```

Update the responsive flow test to locate `t('editor.selectProduct')` instead of the former literal `选择产品`.

- [ ] **Step 2: Run customer image tests and confirm untranslated templates fail**

Run: `cd frontend && node --test tests/customerImageI18n.test.mjs tests/customerImageResponsiveFlow.test.mjs`

Expected: FAIL on remaining fixed Chinese UI literals.

- [ ] **Step 3: Translate all six components**

Each component calls:

```js
const { t, tm } = useCustomerImageI18n()
```

Use `t()` for fixed UI and dynamic fixed templates, `tm()` for descriptor props. Preserve `product.name`, `product.category`, `product.description`, `option.label`, `value.label`, and `pantone_code` exactly. In the catalog, use a sentinel such as `ALL_CATEGORIES = '__all__'` rather than localized text as filter state. In previews and downloads, interpolate the raw product name into translated fixed suffixes.

- [ ] **Step 4: Run the full focused customer-image suite**

Run: `cd frontend && node --test tests/customerImageAdmin.test.mjs tests/customerImageApi.test.mjs tests/customerImageI18n.test.mjs tests/customerImageInvite.test.mjs tests/customerImageLayout.test.mjs tests/customerImagePortalFlow.test.mjs tests/customerImageResponsiveFlow.test.mjs tests/customerImageRouting.test.mjs tests/customerImageState.test.mjs`

Expected: all customer image portal, layout, routing, API, state, flow, admin, responsive, and i18n tests PASS.

- [ ] **Step 5: Commit complete UI translation**

```bash
git add frontend/src/views/customer-image frontend/tests/customerImageI18n.test.mjs frontend/tests/customerImageResponsiveFlow.test.mjs
git commit -m "Translate customer image portal UI"
```

### Task 5: Verification, motion review, and conventions

**Files:**
- Modify only if a verification finding directly requires it.

- [ ] **Step 1: Run the focused tests again**

Run: `cd frontend && node --test tests/customerImageAdmin.test.mjs tests/customerImageApi.test.mjs tests/customerImageI18n.test.mjs tests/customerImageInvite.test.mjs tests/customerImageLayout.test.mjs tests/customerImagePortalFlow.test.mjs tests/customerImageResponsiveFlow.test.mjs tests/customerImageRouting.test.mjs tests/customerImageState.test.mjs`

Expected: PASS with zero failures.

- [ ] **Step 2: Run the production frontend build**

Run: `cd frontend && npm run build`

Expected: Vite exits 0 and writes `dist` without compilation errors.

- [ ] **Step 3: Run repository convention checks against the branch**

Run: `python scripts/check_conventions.py --base $(git merge-base main HEAD)`

Expected: zero red violations; warnings must be inspected and reported.

- [ ] **Step 4: Review motion against `review-animations`**

Inspect the diff for `transition: all`, movement above 300ms, ungated hover, missing reduced motion, layout-property animation, and unnecessary language-change animation. Expected verdict: Approve; the locale change itself is instant and only existing/press feedback uses transform.

- [ ] **Step 5: Dispatch independent adversarial review**

Because the change crosses more than three files, ask an independent agent to inspect bilingual completeness, live locale reactivity of existing messages, persistence failure behavior, API payload invariance, accessibility, mobile overlap, and regression risks. Fix only findings within this feature.

- [ ] **Step 6: Run final diff checks and commit fixes if any**

Run:

```bash
git diff --check main...HEAD
git status --short
git log --oneline main..HEAD
```

Expected: no whitespace errors, clean tracked worktree, and small English commits corresponding to the tasks above.
