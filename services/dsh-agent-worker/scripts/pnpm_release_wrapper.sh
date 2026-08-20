#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "dlx" && "${2:-}" == "@yao-pkg/pkg@6.21.0" ]]; then
  [[ -x "${ARK_DSH_PKG_BIN:-}" ]] || {
    echo "locked @yao-pkg/pkg executable is unavailable" >&2
    exit 2
  }
  shift 2
  exec "$ARK_DSH_PKG_BIN" "$@"
fi

[[ -x "${ARK_DSH_REAL_PNPM:-}" ]] || {
  echo "ARK_DSH_REAL_PNPM must name the pinned pnpm executable" >&2
  exit 2
}
exec "$ARK_DSH_REAL_PNPM" "$@"
