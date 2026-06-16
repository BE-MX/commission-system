# WhatsApp Connector

Standalone WhatsApp Web connector for Ark. Ark calls this service through the internal HTTP contract documented in `docs/requirements/2026-06-16-whatsapp-connector-contract.md`.

## Run

```powershell
cd services/whatsapp-connector
npm install
copy .env.example .env
npm start
```

Set the same API key in:

- Connector `.env`: `WHATSAPP_CONNECTOR_API_KEY`
- Ark backend `.env`: `WHATSAPP_CONNECTOR_API_KEY`

Set Ark backend `WHATSAPP_CONNECTOR_BASE_URL=http://127.0.0.1:8787`.

`WHATSAPP_RESTORE_ON_START=true` makes the connector load active WhatsApp Web sessions from disk after the connector process restarts. If WhatsApp rejects the stored session, the account is marked `reconnect_required` and Ark must show a new QR binding flow.

## Notes

- Runtime metadata is written to `data/`.
- WhatsApp Web session files are written to `.wwebjs_auth/`.
- Both directories must stay outside Git.
- The service uses linked-device QR binding. It can only access accounts scanned and authorized by the account holder.
- Ark backend pulls conversations and messages on its scheduler interval; the connector only exposes the internal pull API and keeps the browser clients alive.
