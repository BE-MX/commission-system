# WhatsApp Connector Service Rules

## Scope

This directory contains the standalone WhatsApp Web connector service. It is intentionally isolated from the Ark FastAPI backend.

## Directory Rules

- `src/` contains runtime source code.
- `.env.example` documents runtime configuration; real secrets stay in `.env` and must not be committed.
- `data/` is runtime state and must not be committed.
- `.wwebjs_auth/` is WhatsApp Web session state and must not be committed.

## Development Rules

- Keep the HTTP contract compatible with `docs/requirements/2026-06-16-whatsapp-connector-contract.md`.
- Do not add Ark business logic here. This service only handles WhatsApp Web binding and raw data extraction.
- Do not log message bodies by default.
- Do not hardcode API keys, tokens, QR content, phone numbers, or customer data.
