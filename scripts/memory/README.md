# claude-mem → Mem0 curated sync

This directory implements the boundary between local session memory and shared
durable memory:

- `~/.claude-mem/claude-mem.db` stays local and is opened read-only.
- Only `decision`, `bugfix`, and `discovery` observations pass the first gate.
- A second conservative gate rejects temporary/unconfirmed content, unverified
  bug fixes, low-signal discoveries, non-architectural decisions, and anything
  matching the sensitive-data scanner.
- Mem0 receives the stable `user_id` `leshine-ark-owner-v1` and metadata fields
  `project`, `source_device`, `obs_id`, `source_key`, `memory_type`, and
  `source_created_at`.
- The deterministic source key is `claude-mem:<source_device>:<obs_id>`.

## Install on each Mac

Install Claude Code and claude-mem first. Then choose a different stable device
slug on every machine:

```bash
scripts/memory/install_local.sh --device mac-mini-11
```

The first run initializes its independent cursor to the current latest
observation and uploads nothing. This is the mandatory no-backfill default.

Store the Mem0 Platform API key in macOS Keychain and enable the five-minute
job only after reviewing the generated config:

```bash
scripts/memory/install_local.sh \
  --device mac-mini-11 \
  --store-api-key \
  --enable
```

No secret is written to Git, JSON config, plist, state, or logs.

## Review and operate

```bash
# Classify new observations without API calls or cursor updates
python3 scripts/memory/claude_mem_mem0_sync.py --dry-run

# One real incremental run
python3 scripts/memory/claude_mem_mem0_sync.py

# Project-first search; falls back once to user scope only when project has no hits
python3 scripts/memory/claude_mem_mem0_sync.py \
  --search "why was this architecture chosen?" \
  --project commission-system
```

Historical backfill is blocked unless both flags are present:

```bash
python3 scripts/memory/claude_mem_mem0_sync.py \
  --backfill-from 123 \
  --confirm-backfill BACKFILL_HISTORY
```

Do not copy the database, cursor, or device config to another machine. Git
syncs this code and project policy; `docs/handoff.md` carries current progress.
