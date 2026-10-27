# Kindle personal dashboard

Scope: PW3 5.15.1.1; tasks, personal notes and explicit message delivery. Membership usage is deferred. Implementation is local only; no production migration or release has run.

Entry: Personal efficiency / Kindle dashboard (`/inkboard`). New permissions `inkboard:read` and `inkboard:write`; the task projection additionally checks the current `task:read/write` permission. All data is scoped to the bound user's live account and permissions. Device tokens are opaque, hashed at rest, revocable, and cannot write tasks/notes or manage credentials.

HTTP namespace: `/api/inkboard`; JSON envelope is `{code, message, data}`.

| Method / path | Identity | Behavior |
| --- | --- | --- |
| GET /devices | User, read | List own devices without secrets |
| POST /devices | User, write | Issue a device token once; max 5 active devices |
| POST /devices/{id}/revoke | User, write | Revoke only own device |
| GET /notes | User, read | List active personal notes |
| POST /notes | User, write | Create note, max 10; title <=120, body <=2000 |
| PUT /notes/{id} | User, write | Update with required version; stale version returns 409 |
| POST /notes/{id}/delete | User, write | Soft-delete with required version |
| GET /messages | User, read | Most recent 50 sent messages and per-device receipt counts |
| POST /messages | User, write | title/body/priority/request_key; idempotent, body <=1000, retained 7 days |
| POST /messages/{id}/withdraw | User, write | Withdraw own message; client removes it at next sync |
| GET /device/sync | Device token | Bounded owner snapshot; open tasks, notes, recent/pending messages, active IDs; no read side effect |
| POST /device/receipts | Device token | ids[] (max20), read=false/true; receipt does not imply human read |

Device sync schema 1: `device_id`, `server_time` (ISO +08:00), `refresh_seconds` (300), `tasks` (max20), `task_total`, `tasks_allowed`, `notes` (max10), `messages` (max20), `pending` (max10 IDs), `pending_count`, `active_message_ids` (max2000). Unreceived messages are included until a durable device receipt. Existing receipts retain the first received/read time under repeated and concurrent upserts. Read acknowledgements are explicit and never downgrade an existing read.

For business integrations, use POST /messages with an authorized current user's identity and stable event request_key. Identical retries return the original message, and changed content under the same key returns 409. This release does not automatically forward every existing announcement or business notification.

Migration `207_inkboard` adds `ark_ink_devices`, `ark_ink_notes`, `ark_ink_messages`, `ark_ink_receipts`. All business times use naive Beijing time through the core helper. User FK matches production's unsigned integer. No existing business table is changed. Downgrade refuses to delete data. Revision 207 follows 206_domestic_shipment_cancel; the integrated graph has one head.

Client source and reproducible package tooling: `extensions/kindle-inkboard/`. PW3 startup, Chinese interface and corrected layout were confirmed on hardware by the user on 2026-10-26. Production service release, account binding, live push, timed wake and battery acceptance remain pending. Validation includes 13 SQLite/HTTP/migration tests, real Lua/FastAPI/SQLite integration, LuaJIT client/TLS/runtime tests and a browser QA with synthetic data. None of those checks connects to shared production databases.
