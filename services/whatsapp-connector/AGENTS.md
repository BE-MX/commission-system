# WhatsApp Connector Service Rules

## Scope

This directory contains the standalone WhatsApp Web connector service. It is intentionally isolated from the Ark FastAPI backend.

## Directory Rules

- `src/` contains runtime source code.
- `.env.example` documents runtime configuration; real secrets stay in `.env` and must not be committed.
- `data/` is runtime state and must not be committed.
- `.wwebjs_auth/` is legacy provider state; retain it only for documented recovery and never commit it. Current encrypted SQLite state and external encryption keys must also remain outside Git.

## Development Rules

- Maintain the current HTTP contract in this directory's `README.md` and `docs/requirements/2026-10-13-whatsapp-baileys.md`. The 2026-06-16 contract is historical; it does not require retaining the retired provider or obsolete endpoints.
- Do not add Ark business logic here. This service only handles WhatsApp Web binding and raw data extraction.
- Do not log message bodies by default.
- Do not hardcode API keys, tokens, QR content, phone numbers, or customer data.
