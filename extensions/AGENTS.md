# Browser extension rules

- This extension lives in `extensions/whatsapp-translation/`; generated `dist/`, ZIP and release manifests are never committed.
- Content scripts may read only the active page DOM needed for the current user action. No cookies, network interception, IndexedDB, React Fiber, webpack modules or page-world bridge.
- WhatsApp text, translations, contact names, phone numbers, message/chat IDs, HTML and screenshots must never enter fixtures, logs, storage or commits.
- `src/whatsapp/` is the only location allowed to contain WhatsApp DOM selectors. Unknown structure and group chats fail closed.
- Device tokens are readable only by the MV3 background trusted context. Content and popup code call the background through typed runtime messages.
- Translation may render beside a message or replace the composer after preview. No code may click, dispatch to or invoke a send control.
- Tests use synthetic fixtures. Every selector update requires direct, group and unknown fixture regression tests.
- Build with `npm ci && npm test && npm run build`; package with `npm run package`. Do not edit generated output.
