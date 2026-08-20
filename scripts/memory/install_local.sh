#!/bin/bash
set -euo pipefail

USER_ID="leshine-ark-owner-v1"
DEVICE=""
ENABLE=0
STORE_KEY=0

usage() {
  echo "Usage: $0 --device <stable-device-slug> [--store-api-key] [--enable]"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --device)
      DEVICE="${2:-}"
      shift 2
      ;;
    --store-api-key)
      STORE_KEY=1
      shift
      ;;
    --enable)
      ENABLE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

if ! printf '%s' "$DEVICE" | grep -Eq '^[a-z0-9][a-z0-9._-]{1,62}$'; then
  echo "--device must be a stable 2-63 character lowercase slug" >&2
  exit 2
fi

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
LOCAL_LIBEXEC="$HOME/.local/libexec"
CONFIG_DIR="$HOME/.config/leshine-memory"
STATE_DIR="$HOME/.local/state/claude-mem-mem0"
CONFIG_PATH="$CONFIG_DIR/config.json"
INSTALLED_SYNC="$LOCAL_LIBEXEC/claude_mem_mem0_sync.py"
KEYCHAIN_SERVICE="leshine-mem0-api-key"
KEYCHAIN_ACCOUNT="$(id -un)"
PLIST_PATH="$HOME/Library/LaunchAgents/com.leshine.claude-mem-mem0-sync.plist"

mkdir -p "$LOCAL_LIBEXEC" "$CONFIG_DIR" "$STATE_DIR" "$HOME/Library/LaunchAgents"
install -m 755 "$SCRIPT_DIR/claude_mem_mem0_sync.py" "$INSTALLED_SYNC"
install -m 644 "$SCRIPT_DIR/memory_policy.py" "$LOCAL_LIBEXEC/memory_policy.py"
install -m 644 "$SCRIPT_DIR/mem0_client.py" "$LOCAL_LIBEXEC/mem0_client.py"

if [ ! -e "$CONFIG_PATH" ]; then
  /usr/bin/python3 - "$CONFIG_PATH" "$DEVICE" "$KEYCHAIN_ACCOUNT" "$REPO_ROOT" <<'PY'
import json
import os
import sys

path, device, account, repo_root = sys.argv[1:]
value = {
    "schema_version": 1,
    "user_id": "leshine-ark-owner-v1",
    "source_device": device,
    "db_path": "~/.claude-mem/claude-mem.db",
    "state_path": "~/.local/state/claude-mem-mem0/cursor.json",
    "lock_path": "~/.local/state/claude-mem-mem0/sync.lock",
    "api_base_url": "https://api.mem0.ai",
    "api_key_env": "MEM0_API_KEY",
    "api_key_keychain_service": "leshine-mem0-api-key",
    "api_key_keychain_account": account,
    "retry_attempts": 4,
    "event_poll_attempts": 20,
    "project_aliases": {
        repo_root: "commission-system",
        os.path.basename(repo_root): "commission-system",
        "commission-system": "commission-system",
        "commission-system-*": "commission-system",
    },
}
with open(path, "x", encoding="utf-8") as handle:
    json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
    handle.write("\n")
os.chmod(path, 0o600)
PY
  echo "Created machine-local config: $CONFIG_PATH"
else
  configured_device="$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["source_device"])' "$CONFIG_PATH")"
  if [ "$configured_device" != "$DEVICE" ]; then
    echo "Existing config belongs to device '$configured_device'; refusing to overwrite" >&2
    exit 1
  fi
fi

if [ "$STORE_KEY" -eq 1 ]; then
  printf 'Mem0 API key (stored only in macOS Keychain): '
  IFS= read -r -s MEM0_KEY
  printf '\n'
  if [ -z "$MEM0_KEY" ]; then
    echo "Empty key; Keychain was not changed" >&2
    exit 1
  fi
  /usr/bin/security add-generic-password -U \
    -s "$KEYCHAIN_SERVICE" \
    -a "$KEYCHAIN_ACCOUNT" \
    -w "$MEM0_KEY" >/dev/null
  unset MEM0_KEY
  echo "Stored Mem0 API key in macOS Keychain service '$KEYCHAIN_SERVICE'"
fi

"$INSTALLED_SYNC" --config "$CONFIG_PATH"

if [ "$ENABLE" -eq 1 ]; then
  if ! /usr/bin/security find-generic-password -w -s "$KEYCHAIN_SERVICE" -a "$KEYCHAIN_ACCOUNT" >/dev/null 2>&1; then
    echo "No Keychain API key. Re-run with --store-api-key before --enable." >&2
    exit 1
  fi
  /usr/bin/python3 - "$PLIST_PATH" "$INSTALLED_SYNC" "$CONFIG_PATH" "$STATE_DIR" <<'PY'
import os
import plistlib
import sys

path, executable, config, state_dir = sys.argv[1:]
value = {
    "Label": "com.leshine.claude-mem-mem0-sync",
    "ProgramArguments": ["/usr/bin/python3", executable, "--config", config],
    "RunAtLoad": True,
    "StartInterval": 300,
    "ProcessType": "Background",
    "StandardOutPath": os.path.join(state_dir, "launchd.log"),
    "StandardErrorPath": os.path.join(state_dir, "launchd.log"),
}
with open(path, "wb") as handle:
    plistlib.dump(value, handle, sort_keys=True)
PY
  chmod 600 "$PLIST_PATH"
  launchctl bootout "gui/$(id -u)" "$PLIST_PATH" >/dev/null 2>&1 || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
  echo "Enabled five-minute incremental sync"
else
  echo "Sync code/config installed but scheduler not enabled (no API key required for initialization)."
fi

echo "Shared user_id: $USER_ID"
echo "Local device: $DEVICE"
