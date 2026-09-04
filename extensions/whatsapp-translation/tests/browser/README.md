# Browser regression tests

- `*.spec.ts` contains Playwright tests. After `npm ci`, install the test browser with `npx playwright install chromium` if needed, then run `npm run test:browser`.
- `fixture.html` is a synthetic direct-chat page; it contains no copied customer data.
- `lexicalEditor.ts` runs the real Lexical plain-text editor in the page's main world.
- `extensionHarness.ts` mounts the production adapter, composer, controller and closed-shadow toolbar in a separate Chromium isolated world. Only the translation response is deterministic test data.
- The harness is bundled in memory with the existing Vite dependency. The test launches its own temporary Chromium profile; it never connects to the user's browser or any production service.
- Mouse interactions use Chromium's pierced DOM to locate controls in the closed shadow root and inspect the selected control's focus, then send real mouse input. Keyboard coverage uses real Alt+T input.
- Focus coverage includes primary-button focus retention, replacement/restoration starting from an external synthetic search field, and the language selector retaining its native ability to take focus.
- Failure screenshots, video and traces are disabled. Playwright output stays under the existing ignored repository `tmp/whatsapp-composer-browser/` directory and can be removed after a run.

This fixture reproduces browser focus, native selection, and real Lexical state updates. It is not WhatsApp's private editor build, so passing here is necessary regression coverage, not a substitute for online acceptance.

The default Lexical editor already accepts the pre-fix replacement sequence. The regression that fails before the focus fix is the real primary `mousedown` transferring focus away from the editor before `click`. That assertion protects against the blur/selection race observed during online acceptance without inventing a fake editor handler that rejects input.
