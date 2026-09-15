# Browser extension rules

- This extension lives in `extensions/whatsapp-translation/`; generated `dist/`, ZIP and release manifests are never committed.
- Content scripts may read only the active page DOM needed for the current user action. No cookies, network interception, IndexedDB, React Fiber, webpack modules or page-world bridge.
- WhatsApp text, translations, contact names, phone numbers, message/chat IDs, HTML and screenshots must never enter fixtures, logs, storage or commits.
- User-initiated reply JSON download may save the masked active-chat capture to a local file. No automatic transcript persistence or raw AI logging. DOM message IDs may be used transiently for overlap matching, but must never be serialized, uploaded or saved.
- The user-authorized reply continuity feature may persist bounded inquiry summaries, masked evidence excerpts and human corrections only in the backend `ark_whatsapp_reply_inquiries` table. Access is scoped to the exact user and paired device, with fixed expiry and deletion. Never persist them in extension storage or AI logs; no transcript, draft, WhatsApp identifier or automatic name-based association. A generated draft is never evidence of a sent message or completed task.
- `src/whatsapp/` is the only location allowed to contain WhatsApp DOM selectors. Unknown structure and group chats fail closed.
- Device tokens are readable only by the MV3 background trusted context. Content and popup code call the background through typed runtime messages.
- Translation and manual reply remain preview/fill-only. User-authorized auto takeover may invoke the current direct-chat send control only while explicitly enabled for that chat. Stop on user input, chat changes, unsupported DOM or uncertain send outcome; never retry an uncertain send or persist takeover across page reloads. Tests send synthetic messages only.
- Tests use synthetic fixtures. Every selector update requires direct, group and unknown fixture regression tests.
- Build with `npm ci && npm test && npm run build`; package with `npm run package`. Do not edit generated output.
