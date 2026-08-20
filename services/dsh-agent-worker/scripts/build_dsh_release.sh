#!/usr/bin/env bash
set -euo pipefail

readonly DSH_TAG="dsh-v0.1.0-rc.8"
readonly DSH_COMMIT="141eb6fef83422698aef7a981029e843e8161534"
readonly OUTPUT_DIR="${1:?usage: build_dsh_release.sh OUTPUT_DIR}"

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

build_root="$(mktemp -d "${TMPDIR:-/tmp}/ark-dsh-build.XXXXXX")"
cleanup() {
  rm -rf -- "$build_root"
}
trap cleanup EXIT

mkdir -p "$OUTPUT_DIR"
output_dir="$(cd "$OUTPUT_DIR" && pwd)"
source_dir="$build_root/deepseek-harness"

git clone --branch "$DSH_TAG" --depth 1 https://github.com/deepseek-ai/deepseek-harness.git "$source_dir"
actual_commit="$(git -C "$source_dir" rev-parse HEAD)"
if [[ "$actual_commit" != "$DSH_COMMIT" ]]; then
  echo "DSH tag moved: expected $DSH_COMMIT, got $actual_commit" >&2
  exit 3
fi

pnpm --dir "$source_dir" install --frozen-lockfile
pnpm --dir "$source_dir" exec tsx scripts/build-exe-for-python-sdk.ts --targets="$runtime_target"
UV_PYTHON="$(command -v python3)" python3 "$source_dir/scripts/build-python-release.py" \
  --package runtime \
  --platform "$runtime_platform" \
  --runtime-exe "$source_dir/dist-exe/dsh-jsonrpc-agent-pkg-${runtime_target#node24-}" \
  --output-dir "$output_dir"
UV_PYTHON="$(command -v python3)" python3 "$source_dir/scripts/build-python-release.py" \
  --package sdk \
  --output-dir "$output_dir"

if command -v sha256sum >/dev/null; then
  (cd "$output_dir" && sha256sum deepseek_harness_*0.1.0rc8*.whl > SHA256SUMS)
else
  (cd "$output_dir" && shasum -a 256 deepseek_harness_*0.1.0rc8*.whl > SHA256SUMS)
fi

echo "DSH rc8 wheels written to $output_dir"
