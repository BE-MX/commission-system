# WhatsApp Translation v1.2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship extension v1.2.0 with complete incoming-message coverage, per-message manual translation, bounded concurrency, automatic reply-language selection, reliable composer replacement, transient-failure recovery, model benchmark results, and LeShine branding.

**Architecture:** Keep WhatsApp DOM knowledge inside `src/whatsapp/`; make `incomingTranslator` the single in-memory owner of per-message state and a three-worker priority queue. Reuse the incoming translation response for language sync, perform provider retry inside one backend quota reservation, and validate composer writes against the controlled contenteditable before reporting success.

**Tech Stack:** TypeScript, MV3 Chrome extension, Vitest/jsdom, Python/FastAPI/SQLAlchemy, pytest, httpx, Vite.

---

## File map

- `extensions/whatsapp-translation/src/whatsapp/messageParser.ts`: strict pure-text and forwarded-text parsing.
- `extensions/whatsapp-translation/src/content/incomingTranslator.ts`: scan scheduling, per-message registry, three-worker queue, manual priority and language callback.
- `extensions/whatsapp-translation/src/content/render.ts`: pending/manual/retry visual states and LeShine theme tokens.
- `extensions/whatsapp-translation/src/content/index.ts`: persist detected language for the active chat only.
- `extensions/whatsapp-translation/src/shared/contracts.ts`: complete target-language set.
- `extensions/whatsapp-translation/src/whatsapp/adapter.ts`: verified Chromium-native composer editing.
- `extensions/whatsapp-translation/src/content/composerController.ts` and `toolbarView.ts`: replacement busy/failure feedback and brand theme.
- `extensions/whatsapp-translation/src/background/apiClient.ts`: one retry for browser/backend transport failures.
- `extensions/whatsapp-translation/src/content/messages.ts`: actionable connection error copy.
- `backend/app/whatsapp_translation/constants.py` and `schemas.py`: German/Dutch/Swedish outgoing contracts.
- `backend/app/whatsapp_translation/translation_service.py`: bounded transient provider retry inside one quota reservation.
- `backend/scripts/benchmark_whatsapp_translation_models.py`: read-only synthetic benchmark over enabled direct model configurations.
- `extensions/whatsapp-translation/assets/icon-master.svg` and `assets/icon-*.png`: reviewed brand icon source and manifest assets.
- `extensions/whatsapp-translation/scripts/render-icons.mjs`: deterministic SVG-to-PNG rendering through installed headless Chrome.
- Existing extension/backend test files plus a new synthetic forwarded fixture cover every boundary.

### Task 1: Forwarded pure-text structure

**Files:**
- Create: `extensions/whatsapp-translation/tests/fixtures/direct-forwarded.html`
- Modify: `extensions/whatsapp-translation/src/whatsapp/messageParser.ts`
- Modify: `extensions/whatsapp-translation/tests/adapter.test.ts`

- [ ] **Step 1: Add a failing synthetic fixture test**

```ts
it('parses forwarded pure text but still fails closed for media and unknown structures', async () => {
  const forwarded = loadFixture('direct-forwarded')
  const messages = await adapterFor(forwarded).listUntranslatedIncomingMessages()
  expect(messages.map(message => message.text)).toEqual(['Forwarded synthetic text'])
  await expect(adapterFor(groupFixture).listUntranslatedIncomingMessages()).resolves.toEqual([])
  await expect(adapterFor(unknownFixture).listUntranslatedIncomingMessages()).resolves.toEqual([])
})
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `npm test -- --run tests/adapter.test.ts`

Expected: FAIL because the forwarded label test id is rejected.

- [ ] **Step 3: Admit only the reviewed forwarded label structure**

```ts
const TEXT_MESSAGE_TEST_IDS = new Set([
  'addon-bubble-container', 'forwarded', 'msg-meta', 'reaction-bubble',
  'reaction-bubble-item', 'selectable-text', 'tail-in', 'tail-out',
])
```

Keep the unique text-node, direction, metadata, direct-chat and unknown-structure checks unchanged.

- [ ] **Step 4: Run direct/group/unknown parsing tests**

Run: `npm test -- --run tests/adapter.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add extensions/whatsapp-translation/src/whatsapp/messageParser.ts extensions/whatsapp-translation/tests
git commit -m "fix(whatsapp-translation): recognize forwarded text messages"
```

### Task 2: Three-worker queue and manual per-message translation

**Files:**
- Modify: `extensions/whatsapp-translation/src/content/incomingTranslator.ts`
- Modify: `extensions/whatsapp-translation/src/content/render.ts`
- Modify: `extensions/whatsapp-translation/tests/incomingTranslator.test.ts`

- [ ] **Step 1: Add failing scheduler and manual-action tests**

```ts
it('runs at most three messages concurrently and exposes a pending action after one second', async () => {
  const pending = Array.from({ length: 4 }, (_, index) => incomingMessage(`Text ${index}`, `key-${index}`))
  adapter.listUntranslatedIncomingMessages.mockResolvedValue(pending)
  bridge.translate.mockImplementation(() => new Promise(() => {}))
  const controller = createIncomingTranslator(adapter, bridge, renderer)
  controller.notifyMutation()
  await vi.advanceTimersByTimeAsync(300)
  expect(bridge.translate).toHaveBeenCalledTimes(3)
  await vi.advanceTimersByTimeAsync(1_000)
  const manual = renderer.mountTranslation.mock.calls.find(([, state]) => state.kind === 'pending')
  expect(manual?.[2]).toBeTypeOf('function')
})

it('does not postpone scanning while mutations continue', async () => {
  const controller = createIncomingTranslator(adapter, bridge, renderer)
  controller.notifyMutation()
  await vi.advanceTimersByTimeAsync(100)
  controller.notifyMutation()
  await vi.advanceTimersByTimeAsync(200)
  expect(adapter.listUntranslatedIncomingMessages).toHaveBeenCalledTimes(1)
})
```

Also assert that manual promotion starts the queued fourth item next, duplicate scans make one call per key, a retry retains the task request id, and old-chat results never render.

- [ ] **Step 2: Run the focused test and verify failures**

Run: `npm test -- --run tests/incomingTranslator.test.ts`

Expected: FAIL on serial execution, reset debounce, and missing pending state.

- [ ] **Step 3: Implement the registry and queue**

Use one task shape and one pump:

```ts
type IncomingTask = {
  generation: number
  message: ParsedMessage
  requestId: string
  status: 'pending' | 'running' | 'success' | 'retryable_error' | 'blocked'
  pendingTimer?: ReturnType<typeof setTimeout>
}

const tasks = new Map<string, IncomingTask>()
const queue: string[] = []
const MAX_CONCURRENCY = 3

function promote(key: string): void {
  const index = queue.indexOf(key)
  if (index >= 0) queue.splice(index, 1)
  queue.unshift(key)
  pump()
}
```

`notifyMutation()` schedules only when no timer exists; mutation during a scan sets `dirty`. `pump()` starts tasks until `runningCount === 3`. Each task keeps the same UUID through automatic/manual retry and is removed or invalidated on chat change.

- [ ] **Step 4: Render pending/manual/retry states**

Add `pending` to `IncomingRenderState.kind`. Render “译此消息” for pending, “翻译中…” for running, and “重试翻译” for a retryable failure. The supplied action promotes or retries only that task.

- [ ] **Step 5: Run focused tests**

Run: `npm test -- --run tests/incomingTranslator.test.ts`

Expected: PASS with maximum observed concurrency of 3.

- [ ] **Step 6: Commit**

```bash
git add extensions/whatsapp-translation/src/content/incomingTranslator.ts extensions/whatsapp-translation/src/content/render.ts extensions/whatsapp-translation/tests/incomingTranslator.test.ts
git commit -m "feat(whatsapp-translation): add bounded message queue and manual translation"
```

### Task 3: Automatic reply-language sync and complete target languages

**Files:**
- Modify: `extensions/whatsapp-translation/src/shared/contracts.ts`
- Modify: `extensions/whatsapp-translation/src/content/incomingTranslator.ts`
- Modify: `extensions/whatsapp-translation/src/content/index.ts`
- Modify: `extensions/whatsapp-translation/tests/incomingTranslator.test.ts`
- Modify: `backend/app/whatsapp_translation/constants.py`
- Modify: `backend/app/whatsapp_translation/schemas.py`
- Modify: `backend/app/whatsapp_translation/glossary_service.py`
- Modify: `backend/tests/test_whatsapp_translation_service.py`
- Modify: `backend/tests/test_whatsapp_translation_auth.py`

- [ ] **Step 1: Add failing language-contract tests**

```ts
expect(TARGET_LANGUAGES).toEqual(['zh-CN', 'en', 'es', 'fr', 'ar', 'ja', 'de', 'nl', 'sv'])
```

```py
@pytest.mark.parametrize("target", ["de", "nl", "sv"])
def test_outgoing_accepts_new_target_languages(target):
    request = TranslateRequest(
        request_id="4f1d9b4f-0cd1-4cdf-bf9a-2e13e2e0de63",
        direction="outgoing", text="交期两周", source_language="auto", target_language=target,
    )
    assert request.target_language == target
```

Add translator tests proving the newest eligible result emits one callback, `OK`/emoji/digits do not emit it, and a previous-chat result cannot emit it.

- [ ] **Step 2: Run focused tests and verify failures**

Run: `npm test -- --run tests/incomingTranslator.test.ts tests/popup.test.ts`

Run: `pytest backend/tests/test_whatsapp_translation_service.py backend/tests/test_whatsapp_translation_auth.py -q`

Expected: FAIL because the three languages are source-only and no sync callback exists.

- [ ] **Step 3: Align contracts and emit the latest valid language**

```ts
export const TARGET_LANGUAGES = ['zh-CN', 'en', 'es', 'fr', 'ar', 'ja', 'de', 'nl', 'sv'] as const

function isLanguageSignal(text: string): boolean {
  return (text.match(/\p{L}/gu)?.length ?? 0) >= 3
}
```

Pass `onDetectedLanguage(message, language)` into `createIncomingTranslator`. Track the newest eligible message key during each scan and invoke the callback only when that key succeeds in the active generation.

In `index.ts`, verify the active title/generation, update `outgoingComposer`, reset the toolbar, and persist through `chat-language/set`. Never translate or replace the composer from this callback.

Set `SUPPORTED_TARGET_LANGUAGES = DETECTED_SOURCE_LANGUAGES` in the backend and expand the strict Pydantic target `Literal` to the same reviewed values.

- [ ] **Step 4: Run language tests**

Run the two focused commands from Step 2.

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add extensions/whatsapp-translation backend/app/whatsapp_translation backend/tests/test_whatsapp_translation_service.py backend/tests/test_whatsapp_translation_auth.py
git commit -m "feat(whatsapp-translation): sync reply language from incoming messages"
```

### Task 4: Verified controlled-composer replacement

**Files:**
- Modify: `extensions/whatsapp-translation/src/whatsapp/adapter.ts`
- Modify: `extensions/whatsapp-translation/src/content/composerController.ts`
- Modify: `extensions/whatsapp-translation/src/content/toolbarView.ts`
- Modify: `extensions/whatsapp-translation/tests/adapter.test.ts`
- Modify: `extensions/whatsapp-translation/tests/composerController.test.ts`

- [ ] **Step 1: Add a failing controlled-editor reproduction test**

Stub `document.execCommand` and make a direct `textContent` write revert on `input`. Assert replacement succeeds only when `insertText` changes the editor and the normalized read-back equals the preview; assert click/submit events remain empty.

```ts
Object.defineProperty(document, 'execCommand', {
  configurable: true,
  value: vi.fn((command: string, _ui: boolean, value: string) => {
    if (command !== 'insertText') return false
    composer.replaceChildren(document.createTextNode(value))
    composer.dispatchEvent(new document.defaultView!.InputEvent('input', { bubbles: true, data: value }))
    return true
  }),
})
expect(await adapterFor(document).replaceComposer('Translated preview')).toBe(true)
expect(adapterFor(document).readComposer()).toBe('Translated preview')
```

- [ ] **Step 2: Run tests and verify the current implementation fails the controlled-editor case**

Run: `npm test -- --run tests/adapter.test.ts tests/composerController.test.ts`

Expected: FAIL because `replaceComposer` returns true without read-back.

- [ ] **Step 3: Implement one Chromium editing path with verification**

Focus the composer, select all child content with `Range`, call `document.execCommand('insertText', false, text)`, then return `readComposer() === normalize(text)`. Do not query any send selector and do not dispatch click/submit.

Add `replacing` toolbar status. Keep the preview on false, display “未能写入输入框，点击重试”, and clear it only after verified success.

- [ ] **Step 4: Run focused tests**

Run: `npm test -- --run tests/adapter.test.ts tests/outgoingComposer.test.ts tests/composerController.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add extensions/whatsapp-translation/src extensions/whatsapp-translation/tests
git commit -m "fix(whatsapp-translation): verify composer replacement"
```

### Task 5: Transient retry and actionable errors

**Files:**
- Modify: `extensions/whatsapp-translation/src/background/apiClient.ts`
- Modify: `extensions/whatsapp-translation/src/content/messages.ts`
- Modify: `extensions/whatsapp-translation/tests/apiClient.test.ts`
- Modify: `extensions/whatsapp-translation/tests/composerController.test.ts`
- Modify: `backend/app/whatsapp_translation/translation_service.py`
- Modify: `backend/tests/test_whatsapp_translation_service.py`

- [ ] **Step 1: Add failing retry-policy tests**

Extension tests: a translation fetch rejected once with `TypeError` succeeds on the second call with the identical JSON `request_id`; 401/429 and stable API errors make one call.

Backend tests:

```py
def test_transient_provider_503_retries_once_inside_one_quota_reservation(...):
    calls = 0
    def flaky_chat(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            response = httpx.Response(503, request=httpx.Request("POST", "https://example.invalid"))
            raise httpx.HTTPStatusError("temporary", request=response.request, response=response)
        return successful_ai_result()
    # assert calls == 2 and usage input_chars == len(request.text), not double
```

Also test 400/401, invalid JSON and a fully consumed timeout do not retry.

- [ ] **Step 2: Run focused tests and verify failures**

Run: `npm test -- --run tests/apiClient.test.ts tests/composerController.test.ts`

Run: `pytest backend/tests/test_whatsapp_translation_service.py -q`

Expected: FAIL because there is no transient retry or differentiated copy.

- [ ] **Step 3: Implement extension retry**

Limit retry to translation POST requests and transport/gateway failures, at most one retry with the same serialized body. Do not retry authorization, quota, validation or translation-contract errors. Map JSON parse/gateway failures to `backend_unavailable` and raw fetch failures to `network_error`.

- [ ] **Step 4: Implement backend retry inside one reservation**

Add a small helper around `chat()` that retries only `httpx.TransportError` and HTTP 502/503/504 when enough of the total request budget remains. Reserve daily input before the helper, and call `record_success` or `record_failure` once after its final result.

- [ ] **Step 5: Replace opaque UI copy**

Use “网络暂时中断，请检查网络后重试”, “莱莎服务暂时不可用，请稍后重试”, “翻译服务响应超时，请重试” and “授权已失效，请重新授权”. Remove “连接方舟失败”.

- [ ] **Step 6: Run focused tests and commit**

Run the two focused commands from Step 2; expected PASS.

```bash
git add extensions/whatsapp-translation backend/app/whatsapp_translation/translation_service.py backend/tests/test_whatsapp_translation_service.py
git commit -m "fix(whatsapp-translation): recover transient translation failures"
```

### Task 6: LeShine icon, theme and version 1.2.0

**Files:**
- Create: `extensions/whatsapp-translation/assets/icon-master.svg`
- Create: `extensions/whatsapp-translation/assets/icon-16.png`
- Create: `extensions/whatsapp-translation/assets/icon-32.png`
- Create: `extensions/whatsapp-translation/assets/icon-48.png`
- Create: `extensions/whatsapp-translation/assets/icon-128.png`
- Create: `extensions/whatsapp-translation/scripts/render-icons.mjs`
- Modify: `extensions/whatsapp-translation/manifest.json`
- Modify: `extensions/whatsapp-translation/package.json`
- Modify: `extensions/whatsapp-translation/package-lock.json`
- Modify: `extensions/whatsapp-translation/src/content/render.ts`
- Modify: `extensions/whatsapp-translation/src/content/toolbarView.ts`
- Modify: `extensions/whatsapp-translation/src/popup/popup.css`
- Modify: `extensions/whatsapp-translation/tests/manifest.test.ts`

- [ ] **Step 1: Add failing manifest/theme assertions**

```ts
expect(manifest.version).toBe('1.2.0')
expect(manifest.icons).toEqual({
  16: 'assets/icon-16.png', 32: 'assets/icon-32.png',
  48: 'assets/icon-48.png', 128: 'assets/icon-128.png',
})
expect(manifest.action.default_icon).toEqual(manifest.icons)
```

Assert the package filename is `whatsapp-translation-1.2.0.zip` and the CSS contains the exact brand tokens `#FDD956`, `#080303`, `#25D366`.

- [ ] **Step 2: Run focused tests and verify failures**

Run: `npm test -- --run tests/manifest.test.ts tests/popup.test.ts tests/incomingTranslator.test.ts`

Expected: FAIL on version, icons and brand tokens.

- [ ] **Step 3: Draw the reviewed icon deterministically**

Create a flat SVG master matching the selected concept: yellow rounded square, black and green speech bubbles forming an S relationship, white “译”, and black LeShine wordmark on 48/128 artwork. Produce simplified 16/32 artwork without the unreadable full wordmark.

Add a build-time renderer that writes a temporary HTML page containing the reviewed SVG, starts `C:\Program Files\Google\Chrome\Application\chrome.exe` with `--headless --hide-scrollbars --default-background-color=00000000 --window-size=<size>,<size> --screenshot=<path>`, and deletes the temporary page. It creates the four exact PNG sizes without adding an extension runtime dependency.

- [ ] **Step 4: Apply the brand tokens**

Use yellow for primary buttons with black text, black for emphasis, and green only for success/connection/translation accent. Preserve dark-mode contrast and reduced-motion behavior.

- [ ] **Step 5: Bump version and run focused tests**

Update manifest/package/lock to 1.2.0 and register both extension/action icons. Run the command from Step 2; expected PASS.

Inspect all four PNGs with the local image viewer. Expected: no clipped edge; “译” remains recognizable at 16px; `LeShine` is legible at 48/128px; no gradient, checkerboard pixels or transparent holes inside the yellow tile.

- [ ] **Step 6: Commit**

```bash
git add extensions/whatsapp-translation
git commit -m "feat(whatsapp-translation): apply LeShine branding for v1.2"
```

### Task 7: Read-only configured-model benchmark

**Files:**
- Create: `backend/scripts/benchmark_whatsapp_translation_models.py`
- Create: `backend/tests/test_whatsapp_translation_benchmark.py`
- Create after execution: `docs/reports/2026-09-04-whatsapp-translation-model-benchmark.md`

- [ ] **Step 1: Add failing pure-function tests**

Test that sample generation yields 30 calls per model across `en/de/nl/es/sv × short/medium/long × 2`, percentile calculation is correct, invariants catch changed SKU/numbers/emoji/newlines, duplicate provider/model pairs are deduplicated, and report serialization contains no API key or prompt body.

- [ ] **Step 2: Run the focused test and verify failure**

Run: `pytest backend/tests/test_whatsapp_translation_benchmark.py -q`

Expected: FAIL because the benchmark module does not exist.

- [ ] **Step 3: Implement the benchmark script**

Query enabled, undeleted direct providers and enabled presets; deduplicate `(provider_id, model)`. Load the incoming WhatsApp system prompt as the common prompt, build OpenAI/Anthropic requests with existing helpers, run one warm-up plus randomized measured cases, and keep credentials/output text out of stdout and files.

Emit per model: attempts, successes, contract-valid count, invariant-valid count, P50, P95, max latency, input/output tokens and estimated cost only when configured data makes it available. Exit nonzero only when no model can be tested.

- [ ] **Step 4: Run unit tests**

Run: `pytest backend/tests/test_whatsapp_translation_benchmark.py -q`

Expected: PASS.

- [ ] **Step 5: Run against the configured production model set**

Use the project deployment/remote execution mechanism so the script reads production provider configuration without exporting secrets. Save only aggregate, sanitized results to `docs/reports/2026-09-04-whatsapp-translation-model-benchmark.md`. Do not mutate presets.

- [ ] **Step 6: Commit script and sanitized report**

```bash
git add backend/scripts/benchmark_whatsapp_translation_models.py backend/tests/test_whatsapp_translation_benchmark.py docs/reports/2026-09-04-whatsapp-translation-model-benchmark.md
git commit -m "perf(whatsapp-translation): benchmark configured translation models"
```

### Task 8: Full verification, review, package, merge and production deploy

**Files:**
- Generated only: `dist/whatsapp-translation-1.2.0.zip`
- Generated only: `dist/latest.json`

- [ ] **Step 1: Run extension verification**

Run in `extensions/whatsapp-translation`:

```bash
npm ci
npm test
npm run build
npm run package
```

Expected: all tests pass; build succeeds; release metadata says 1.2.0; generated files remain untracked.

- [ ] **Step 2: Run backend verification**

Run the WhatsApp translation pytest suite, then the repository-prescribed backend validation. Expected: PASS.

- [ ] **Step 3: Perform privacy and release audits**

Search the diff/fixtures/report for real WhatsApp text, contact IDs, HTML, screenshots, secrets and generated release files. Verify all changed lines trace to the approved spec and `git diff --check` is clean.

- [ ] **Step 4: Request independent adversarial review**

Give the reviewer the spec, plan and complete diff. Require findings on selector fail-closed behavior, duplicate billing, chat-generation races, native composer writes, retry multiplication, privacy, model benchmark safety, theme contrast and release metadata. Resolve every actionable finding and rerun affected tests.

- [ ] **Step 5: Merge in the main working tree**

From `D:\MyProgram\commission-system`, verify it is clean, fetch, fast-forward main, merge the feature branch, and rerun smoke verification. Do not delete user changes or generated release artifacts.

- [ ] **Step 6: Deploy with project commands and verify production**

Use the deployment instructions discovered in the repository. Deploy the backend independently of Git push, verify health/session/capabilities/one synthetic translation, and confirm the release artifact is available. Never use real customer text for the canary.

- [ ] **Step 7: Push the merged commit**

Push only after production verification, as previously requested by the user. Report the final commit, deployment result, benchmark recommendation and exact extension ZIP path.
