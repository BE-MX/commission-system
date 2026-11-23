# Devlog collector

The collector uses Python's standard library and Git. It never reads working file
contents or uploads diffs. Commit subjects are redacted before shortening;
unsafe branch identifiers are represented by stable hashes. Names in ordinary
English subjects cannot be reliably recognized by P0's rules.

Offline preview (no fetch and no HTTP):

```powershell
python scripts/devlog/collect.py --no-fetch
python scripts/devlog/backfill_releases.py
```

State is local in `.devlog_state/`: `last-payload.json`, `keymap.json`,
`patch-ids.json`, optional `releases.json`. Preserve the key map to avoid changing
item identities. A failed live ledger refresh blocks pushing even if a cached
ledger exists. Missing Git revisions and malformed caches also block uploading.
The key map records both commit SHA and patch-id ownership, keeping a hotfix's
identity when the same change is subsequently merged or cherry-picked into main.
Merge-only changes (including conflict resolutions) are independently required
as release evidence; publishing just the second parent cannot cover them. P0
conservatively requires that merge commit in release ancestry for these cases.
This applies to nested merges and unmerged feature-branch history as well as
main's first-parent history. Every parent is traversed. Two-parent merges with
no remerge delta are filtered; octopus merges retain their full first-parent
delta conservatively because Git cannot reconstruct them with `--remerge-diff`.
`collector.lock` prevents overlapping runs; after a crash, verify no collector
is running before removing that file. Git status does not acquire optional index
locks. Fetch failures are shown as a failed source, preserving server-side states.
`--no-fetch` also reports an incomplete fetch source. Missing `origin/main` blocks
uploading; local main is never substituted as evidence of a remote push.

Production ingestion requires explicit authorization and local `collector.json`
containing `base_url` (HTTPS) and `token`. Never commit or print its contents.
HTTP redirects are rejected to keep the machine token on its configured endpoint.

```powershell
python scripts/devlog/collect.py --push
```

Backfill defaults to a printable draft. File modification times are provisional:
verify each one against global release records. `--add SHA@ISO_TIME` replaces the
inferred timestamp of that revision. `--write-cache` stores a local draft for
classification checks; it does not upload. Before any authorized `--apply`, fill
missing releases since 2026-09-01 and inspect the release-date distribution.
An invalid/failed activation receipt never falls back to a candidate marker.

`register_task.ps1` only previews by default. After authorization, `-Register`
registers eight daily triggers from 08:00 through 22:00 on a UTC+08 machine,
with overlapping executions disabled. Existing tasks are not overwritten.
The script is not invoked automatically by tests, deployment, or collection.

Exit codes: `0` success, `1` Git collection failed, `2` missing configuration,
`3` release ledger unavailable, `4` push rejected/failed, `5` active/stale lock.

Offline regression tests: `python -m pytest scripts/devlog/tests -q`.
