# Universal AI Chat v1

## Scope and acceptance

Upgrade the existing Vue AI workspace into the platform's general chat entry. Administrators publish direct OpenAI/Anthropic text presets through `parameters.chat`, optionally restricting them to role names. Employees never receive provider keys, URLs, private prompts or raw parameters. Selection is enforced again on each new generation, including regeneration.

Reuse server-owned sessions, files, permissions and `app.ai.service`. Support model selection per turn, immutable answer model labels, private history with pagination/rename/soft delete, regeneration of the latest answer, separate reasoning display, document/image capability checks, and daily request limits. Keep existing conversation modes. Do not add search, speech, business tools or full branching in this release.

## Data and requests

- Add nullable session `selected_preset_id`, `deleted_at`; message `model_snapshot`, `reasoning_content`. Preserve existing records; historical replies without a snapshot are not assigned a guessed model.
- Only explicitly published chat presets and the existing `customer_ai_chat` default are listed. An explicit `chat.enabled=false` disables the default too. Image-generation and agent presets cannot enter the catalog.
- Model metadata: `enabled`, `label`, `vision`, `allowed_roles`. Empty role list means any user with chat access. New presets default to text-only. Existing default retains its image behavior until configured otherwise.
- Model selection, quota reservation and turn creation share one transaction, serialized per user and per conversation. Replayed request IDs do not reserve again. Generation already in progress rejects another turn. Regeneration is restricted to the last user turn, and context includes only the latest usable answer per user turn.
- Soft deletion removes access to sessions/messages/attachments and preserves accounting records. In-progress sessions cannot be deleted.
- Daily limit counts accepted generations (including stopped/failed requests), resets at Beijing midnight, and includes deleted conversations. Default 100 per user, configurable through Settings.

## Verification

Regression coverage: model allowlist and role revocation, unknown/disabled/image providers, preset metadata isolation, cross-user access, replay and changed-model conflicts, model snapshots and regeneration context, capability checks, quota/day boundaries and soft deletion. Verify actual OpenAI and Anthropic HTTP/SSE request formatting with mocked provider transport; no paid API calls or production database writes.

Run affected backend tests, frontend state tests/build, isolated migration validation, navigation contract generation/checks, independent risk review, browser acceptance at desktop/mobile widths, conventions and local Git sweep. Deliver without push, merge or deployment.

## Administrator setup

After an authorized deployment applies migration 265, open 系统管理 → AI 接入. Configure a direct OpenAI-compatible or Anthropic provider and a text preset; enable 在 AI 工作台中使用. Set its employee-facing name, whether it can understand images, and optional allowed roles. Give employees `ai_chat:read` / `ai_chat:write`; an empty allowed-role list does not bypass those permissions. Provider keys remain server-side. Native Gemini/Responses, search, speech and business tools are outside v1.

The platform-level AI 工作台 menu opens general chat; AI 生图 remains in the design group. Existing chat URLs, built-in modes and histories remain usable. Daily limits count admitted requests, not tokens or cost. A preset used elsewhere can be published without forwarding chat metadata to those consumers.

## Operational boundaries

Provider HTTP requests and SSE parsing are verified with simulated transports, not a paid vendor request. A real provider smoke test still belongs to authorized release acceptance. Normal browser disconnect/stop releases the conversation; a process kill can leave a persisted streaming message without an automatic lease recovery. Do not blindly reset it while an upstream call might still be active. Soft deletion revokes access but does not erase accounting or stored files.

Implementation and validation: [delivery report](../reports/2026-11-16-universal-ai-chat.md).
