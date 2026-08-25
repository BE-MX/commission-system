#!/usr/bin/env bash
set -euo pipefail

readonly DSH_TAG="dsh-v0.1.0-rc.8"
readonly DSH_COMMIT="141eb6fef83422698aef7a981029e843e8161534"
readonly DEPLOY_PATCH_SHA256="0ffea168d91b55bb4976545b0eec4bc6fa055e87ed0f93ef1f3cfa1d4632d43f"
readonly OUTPUT_DIR="${1:?usage: build_dsh_release.sh OUTPUT_DIR}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
deploy_patch="$script_dir/../patches/dsh-rc8-lockfile-deploy.patch"

case "$(uname -s)-$(uname -m)" in
  Darwin-arm64)
    runtime_target="node24-macos-arm64"
    runtime_platform="macos-arm64"
    ;;
  Linux-x86_64)
    runtime_target="node24-linux-x64"
    runtime_platform="linux-x64"
    ;;
  Linux-aarch64|Linux-arm64)
    runtime_target="node24-linux-arm64"
    runtime_platform="linux-arm64"
    ;;
  *)
    echo "unsupported DSH build platform: $(uname -s)-$(uname -m)" >&2
    exit 2
    ;;
esac

if [[ "$runtime_platform" == linux-* && "${ARK_DSH_MANYLINUX_2_28_CONFIRMED:-}" != "1" ]]; then
  echo "Linux release builds must run in the reviewed manylinux 2.28 target environment; set ARK_DSH_MANYLINUX_2_28_CONFIRMED=1 only inside that builder." >&2
  exit 2
fi

for command_name in git node pnpm python3 uv; do
  command -v "$command_name" >/dev/null || {
    echo "missing build dependency: $command_name" >&2
    exit 2
  }
done

if [[ -n "${ARK_DSH_PKG_BIN:-}" || -n "${ARK_DSH_REAL_PNPM:-}" ]]; then
  [[ -x "${ARK_DSH_PKG_BIN:-}" && -x "${ARK_DSH_REAL_PNPM:-}" ]] || {
    echo "ARK_DSH_PKG_BIN and ARK_DSH_REAL_PNPM must both be executable" >&2
    exit 2
  }
  wrapper_dir="$(mktemp -d "${TMPDIR:-/tmp}/ark-dsh-pnpm.XXXXXX")"
  ln -s "$script_dir/pnpm_release_wrapper.sh" "$wrapper_dir/pnpm"
  export PATH="$wrapper_dir:$PATH"
fi

build_root="$(mktemp -d "${TMPDIR:-/tmp}/ark-dsh-build.XXXXXX")"
cleanup() {
  rm -rf -- "$build_root"
  if [[ -n "${wrapper_dir:-}" ]]; then
    rm -rf -- "$wrapper_dir"
  fi
}
trap cleanup EXIT

mkdir -p "$OUTPUT_DIR"
output_dir="$(cd "$OUTPUT_DIR" && pwd)"
if [[ -n "$(find "$output_dir" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
  echo "release output directory must be empty: $output_dir" >&2
  exit 2
fi
source_dir="$build_root/deepseek-harness"

git clone --branch "$DSH_TAG" --depth 1 https://github.com/deepseek-ai/deepseek-harness.git "$source_dir"
actual_commit="$(git -C "$source_dir" rev-parse HEAD)"
if [[ "$actual_commit" != "$DSH_COMMIT" ]]; then
  echo "DSH tag moved: expected $DSH_COMMIT, got $actual_commit" >&2
  exit 3
fi
if command -v sha256sum >/dev/null; then
  actual_patch_sha256="$(sha256sum "$deploy_patch" | cut -d ' ' -f 1)"
else
  actual_patch_sha256="$(shasum -a 256 "$deploy_patch" | cut -d ' ' -f 1)"
fi
if [[ "$actual_patch_sha256" != "$DEPLOY_PATCH_SHA256" ]]; then
  echo "reviewed DSH deploy patch checksum mismatch" >&2
  exit 3
fi
git -C "$source_dir" apply --unidiff-zero --check "$deploy_patch"
git -C "$source_dir" apply --unidiff-zero "$deploy_patch"
source_date_epoch="$(git -C "$source_dir" show -s --format=%ct HEAD)"
export SOURCE_DATE_EPOCH="$source_date_epoch"
cp "$source_dir/LICENSE" "$output_dir/LICENSE"
cp "$source_dir/THIRD_PARTY_NOTICES.md" "$output_dir/THIRD_PARTY_NOTICES.md"

pnpm --dir "$source_dir" install --frozen-lockfile
export npm_config_offline=true
export PNPM_CONFIG_OFFLINE=true
pnpm --dir "$source_dir" exec tsx scripts/build-exe-for-python-sdk.ts --targets="$runtime_target"
UV_PYTHON="$(command -v python3)" python3 "$source_dir/scripts/build-python-release.py" \
  --package runtime \
  --platform "$runtime_platform" \
  --runtime-exe "$source_dir/dist-exe/dsh-jsonrpc-agent-pkg-${runtime_target#node24-}" \
  --output-dir "$output_dir"
UV_PYTHON="$(command -v python3)" python3 "$source_dir/scripts/build-python-release.py" \
  --package sdk \
  --output-dir "$output_dir"

export ARK_DSH_BUILD_OUTPUT="$output_dir/BUILD_PROVENANCE.json"
export ARK_DSH_RUNTIME_PLATFORM="$runtime_platform"
export ARK_DSH_SOURCE_DATE_EPOCH="$source_date_epoch"
export ARK_DSH_DEPLOY_PATCH_SHA256="$actual_patch_sha256"
python3 - <<'PY'
import json
import os
from pathlib import Path
import platform
import subprocess


def command_version(*command: str) -> str:
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout.strip()


payload = {
    "schema_version": 1,
    "upstream": {
        "repository": "https://github.com/deepseek-ai/deepseek-harness.git",
        "tag": "dsh-v0.1.0-rc.8",
        "commit": "141eb6fef83422698aef7a981029e843e8161534",
        "source_date_epoch": int(os.environ["ARK_DSH_SOURCE_DATE_EPOCH"]),
    },
    "artifact": {
        "runtime_platform": os.environ["ARK_DSH_RUNTIME_PLATFORM"],
        "architecture": platform.machine(),
        "libc": list(platform.libc_ver()),
        "builder_image_digest": os.getenv("ARK_DSH_BUILDER_IMAGE_DIGEST"),
    },
    "toolchain": {
        "node": command_version("node", "--version"),
        "pnpm": command_version("pnpm", "--version"),
        "python": platform.python_version(),
        "uv": command_version("uv", "--version"),
    },
    "build_patch": {
        "name": "dsh-rc8-lockfile-deploy.patch",
        "sha256": os.environ["ARK_DSH_DEPLOY_PATCH_SHA256"],
    },
    "ci": {
        "repository": os.getenv("GITHUB_REPOSITORY"),
        "workflow": os.getenv("GITHUB_WORKFLOW"),
        "run_id": os.getenv("GITHUB_RUN_ID"),
        "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
        "source_sha": os.getenv("GITHUB_SHA"),
    },
}
Path(os.environ["ARK_DSH_BUILD_OUTPUT"]).write_text(
    json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

if command -v sha256sum >/dev/null; then
  (cd "$output_dir" && sha256sum \
    BUILD_PROVENANCE.json LICENSE THIRD_PARTY_NOTICES.md \
    deepseek_harness_*0.1.0rc8*.whl | LC_ALL=C sort -k 2 > SHA256SUMS)
else
  (cd "$output_dir" && shasum -a 256 \
    BUILD_PROVENANCE.json LICENSE THIRD_PARTY_NOTICES.md \
    deepseek_harness_*0.1.0rc8*.whl | LC_ALL=C sort -k 2 > SHA256SUMS)
fi

echo "DSH rc8 wheels written to $output_dir"
