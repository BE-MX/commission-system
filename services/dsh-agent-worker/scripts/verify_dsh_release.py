#!/usr/bin/env python3
"""Fail-closed verification for Ark's reviewed DSH rc8 Linux release bundle."""

from __future__ import annotations

import argparse
from base64 import urlsafe_b64decode
import csv
from datetime import datetime, timezone
from email.message import Message
from email.parser import Parser
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
from zipfile import ZipFile


SDK_WHEEL = "deepseek_harness_sdk-0.1.0rc8-py3-none-any.whl"
RUNTIME_WHEEL = "deepseek_harness_runtime_bin-0.1.0rc8-py3-none-manylinux_2_28_x86_64.whl"
CHECKSUM_FILES = {"BUILD_PROVENANCE.json", "LICENSE", "THIRD_PARTY_NOTICES.md", SDK_WHEEL, RUNTIME_WHEEL}
EXPECTED_UPSTREAM = {
    "repository": "https://github.com/deepseek-ai/deepseek-harness.git",
    "tag": "dsh-v0.1.0-rc.8",
    "commit": "141eb6fef83422698aef7a981029e843e8161534",
}
EXPECTED_BUILDER_IMAGE = "sha256:443eabd378e140996780a772e12c1a1ef10551da933fe76d74a1bab61f68a7b7"
EXPECTED_DEPLOY_PATCH_SHA256 = "0ffea168d91b55bb4976545b0eec4bc6fa055e87ed0f93ef1f3cfa1d4632d43f"
EXPECTED_RUNTIME_PAYLOADS = {
    "deepseek_harness_runtime/runtime/dsh-jsonrpc-agent-pkg-linux-x64",
    "deepseek_harness_runtime/runtime/dsh-jsonrpc-agent-pkg-linux-x64-rg",
}
ALLOWED_NEEDED_LIBRARIES = {
    "ld-linux-x86-64.so.2",
    "libc.so.6",
    "libdl.so.2",
    "libgcc_s.so.1",
    "libm.so.6",
    "libpthread.so.0",
    "libresolv.so.2",
    "librt.so.1",
    "libstdc++.so.6",
    "libutil.so.1",
}


class VerificationError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _checksum_manifest(root: Path, *, require_report: bool) -> dict[str, str]:
    manifest = root / "SHA256SUMS"
    if not manifest.is_file():
        raise VerificationError("missing SHA256SUMS")
    entries: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            raise VerificationError("invalid SHA256SUMS line")
        name = parts[1].lstrip(" *")
        if not name or Path(name).name != name or name in entries:
            raise VerificationError("unsafe or duplicate checksum filename")
        entries[name] = parts[0]
    expected = CHECKSUM_FILES | ({"VERIFICATION.json"} if require_report else set())
    if entries.keys() != expected:
        raise VerificationError("checksum manifest has missing or unexpected artifacts")
    present: set[str] = set()
    for path in root.iterdir():
        if path.is_symlink() or not path.is_file():
            raise VerificationError(f"release bundle contains non-regular artifact: {path.name}")
        present.add(path.name)
    if present != expected | {"SHA256SUMS"}:
        raise VerificationError("release bundle contains unchecksummed or missing files")
    for name, expected_hash in entries.items():
        if _sha256(root / name) != expected_hash:
            raise VerificationError(f"checksum mismatch: {name}")
    return entries


def _safe_wheel_entries(archive: ZipFile, wheel_name: str) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    seen: set[str] = set()
    for info in archive.infolist():
        name = info.filename
        pure = PurePosixPath(name)
        if name in seen or pure.is_absolute() or ".." in pure.parts:
            raise VerificationError(f"unsafe or duplicate wheel entry: {wheel_name}:{name}")
        seen.add(name)
        if stat.S_ISLNK(info.external_attr >> 16):
            raise VerificationError(f"wheel contains symlink: {wheel_name}:{name}")
        if not info.is_dir():
            files[name] = archive.read(info)
    return files


def _verify_record(files: dict[str, bytes], wheel_name: str) -> None:
    records = [name for name in files if name.endswith(".dist-info/RECORD")]
    if len(records) != 1:
        raise VerificationError(f"wheel must contain one RECORD: {wheel_name}")
    record_name = records[0]
    rows: dict[str, tuple[str, str]] = {}
    for row in csv.reader(io.StringIO(files[record_name].decode("utf-8"))):
        if len(row) != 3 or row[0] in rows:
            raise VerificationError(f"invalid or duplicate RECORD row: {wheel_name}")
        rows[row[0]] = (row[1], row[2])
    if rows.keys() != files.keys():
        raise VerificationError(f"RECORD inventory mismatch: {wheel_name}")
    for name, (encoded_hash, encoded_size) in rows.items():
        if name == record_name:
            if encoded_hash or encoded_size:
                raise VerificationError(f"RECORD must not self-hash: {wheel_name}")
            continue
        if not encoded_hash.startswith("sha256=") or not encoded_size.isdigit():
            raise VerificationError(f"RECORD must use sha256 and size: {wheel_name}:{name}")
        raw_hash = encoded_hash.removeprefix("sha256=")
        raw_hash += "=" * (-len(raw_hash) % 4)
        if urlsafe_b64decode(raw_hash) != hashlib.sha256(files[name]).digest():
            raise VerificationError(f"RECORD hash mismatch: {wheel_name}:{name}")
        if int(encoded_size) != len(files[name]):
            raise VerificationError(f"RECORD size mismatch: {wheel_name}:{name}")


def _wheel_messages(files: dict[str, bytes], wheel_name: str) -> tuple[Message, Message]:
    metadata_names = [name for name in files if name.endswith(".dist-info/METADATA")]
    wheel_names = [name for name in files if name.endswith(".dist-info/WHEEL")]
    if len(metadata_names) != 1 or len(wheel_names) != 1:
        raise VerificationError(f"invalid wheel metadata layout: {wheel_name}")
    return (
        Parser().parsestr(files[metadata_names[0]].decode("utf-8")),
        Parser().parsestr(files[wheel_names[0]].decode("utf-8")),
    )


def _inspect_wheel(path: Path, *, runtime: bool) -> dict[str, bytes]:
    with ZipFile(path) as archive:
        files = _safe_wheel_entries(archive, path.name)
    _verify_record(files, path.name)
    metadata, wheel = _wheel_messages(files, path.name)
    expected_name = "deepseek-harness-runtime-bin" if runtime else "deepseek-harness-sdk"
    expected_tag = "py3-none-manylinux_2_28_x86_64" if runtime else "py3-none-any"
    if metadata.get("Name") != expected_name or metadata.get("Version") != "0.1.0rc8":
        raise VerificationError(f"unexpected wheel identity: {path.name}")
    if metadata.get("License-Expression") != "MIT":
        raise VerificationError(f"unexpected wheel license: {path.name}")
    expected_licenses = ["LICENSE", "THIRD_PARTY_NOTICES.md"] if runtime else ["LICENSE"]
    license_files = [PurePosixPath(name).name for name in metadata.get_all("License-File") or []]
    if license_files != expected_licenses:
        raise VerificationError(f"unexpected wheel license files: {path.name}")
    packaged_licenses = {
        PurePosixPath(name).name: body
        for name, body in files.items()
        if ".dist-info/licenses/" in name
    }
    if packaged_licenses.keys() != set(expected_licenses) or any(not body.strip() for body in packaged_licenses.values()):
        raise VerificationError(f"missing or empty packaged wheel license: {path.name}")
    if wheel.get_all("Tag") != [expected_tag]:
        raise VerificationError(f"unexpected wheel tag: {path.name}")
    runtime_files = {name for name in files if "/runtime/dsh-jsonrpc-agent-pkg-" in name}
    if runtime_files != (EXPECTED_RUNTIME_PAYLOADS if runtime else set()):
        raise VerificationError(f"unexpected runtime payload inventory: {path.name}")
    if not runtime:
        requirements = metadata.get_all("Requires-Dist") or []
        if "deepseek-harness-runtime-bin==0.1.0rc8" not in requirements:
            raise VerificationError("SDK does not pin the reviewed Runtime wheel")
    return files


def _runtime_elf_contract(files: dict[str, bytes]) -> tuple[set[str], set[str], int]:
    versions: set[str] = set()
    needed: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="ark-dsh-verify-") as temp:
        for index, name in enumerate(sorted(EXPECTED_RUNTIME_PAYLOADS)):
            body = files[name]
            if not body.startswith(b"\x7fELF"):
                raise VerificationError(f"Runtime payload is not ELF: {name}")
            extracted = Path(temp) / f"elf-{index}"
            extracted.write_bytes(body)
            extracted.chmod(0o755)
            header = subprocess.run(
                ["readelf", "--file-header", str(extracted)], check=True, capture_output=True, text=True,
            ).stdout
            if not re.search(r"Class:\s+ELF64", header):
                raise VerificationError(f"Runtime payload is not ELF64: {name}")
            if not re.search(r"Machine:\s+Advanced Micro Devices X86-64", header):
                raise VerificationError(f"Runtime payload is not x86_64: {name}")
            if not re.search(r"Type:\s+(?:EXEC|DYN)\b", header):
                raise VerificationError(f"Runtime payload is not executable ELF: {name}")
            dynamic = subprocess.run(
                ["readelf", "--dynamic", str(extracted)], check=True, capture_output=True, text=True,
            ).stdout
            needed.update(re.findall(r"Shared library: \[(.*?)\]", dynamic))
            version_info = subprocess.run(
                ["readelf", "--version-info", str(extracted)], check=True, capture_output=True, text=True,
            ).stdout
            versions.update(re.findall(r"GLIBC_(\d+\.\d+)", version_info))
    too_new = sorted(version for version in versions if tuple(map(int, version.split("."))) > (2, 28))
    if too_new:
        raise VerificationError(f"Runtime requires unsupported glibc symbols: {too_new}")
    forbidden_needed = sorted(needed - ALLOWED_NEEDED_LIBRARIES)
    if forbidden_needed:
        raise VerificationError(f"Runtime links non-reviewed shared libraries: {forbidden_needed}")
    return versions, needed, len(EXPECTED_RUNTIME_PAYLOADS)


def _verify_executable_modes(path: Path) -> None:
    with ZipFile(path) as archive:
        for name in EXPECTED_RUNTIME_PAYLOADS:
            if archive.getinfo(name).external_attr >> 16 & stat.S_IXUSR == 0:
                raise VerificationError(f"Runtime payload lost executable bit: {name}")


def _auditwheel_policy(path: Path) -> str:
    result = subprocess.run(["auditwheel", "show", str(path)], check=True, capture_output=True, text=True)
    match = re.search(r'following platform tag:\s+"([^"]+)"', result.stdout)
    if not match:
        raise VerificationError("auditwheel did not report a compatible platform policy")
    policy = match.group(1)
    accepted = policy in {"manylinux1_x86_64", "manylinux2010_x86_64", "manylinux2014_x86_64"}
    version_match = re.fullmatch(r"manylinux_2_(\d+)_x86_64", policy)
    if version_match:
        accepted = int(version_match.group(1)) <= 28
    if not accepted:
        raise VerificationError(f"auditwheel policy exceeds manylinux 2.28: {policy}")
    return policy


def verify(root: Path, *, require_report: bool = True, source_sha: str | None = None) -> dict:
    root = root.resolve()
    _checksum_manifest(root, require_report=require_report)
    provenance = json.loads((root / "BUILD_PROVENANCE.json").read_text(encoding="utf-8"))
    if provenance.get("schema_version") != 1:
        raise VerificationError("unsupported provenance schema")
    upstream = provenance.get("upstream") or {}
    if any(upstream.get(key) != value for key, value in EXPECTED_UPSTREAM.items()):
        raise VerificationError("upstream provenance does not match reviewed rc8")
    artifact = provenance.get("artifact") or {}
    if artifact.get("runtime_platform") != "linux-x64" or artifact.get("architecture") != "x86_64":
        raise VerificationError("artifact provenance is not Linux x86_64")
    if artifact.get("builder_image_digest") != EXPECTED_BUILDER_IMAGE:
        raise VerificationError("builder image provenance mismatch")
    toolchain = provenance.get("toolchain") or {}
    if toolchain.get("node") != "v22.19.0" or toolchain.get("pnpm") != "11.7.0":
        raise VerificationError("build toolchain version mismatch")
    if toolchain.get("uv") != "uv 0.8.12":
        raise VerificationError("uv build tool version mismatch")
    build_patch = provenance.get("build_patch") or {}
    if (
        build_patch.get("name") != "dsh-rc8-lockfile-deploy.patch"
        or build_patch.get("sha256") != EXPECTED_DEPLOY_PATCH_SHA256
    ):
        raise VerificationError("reviewed DSH deploy patch provenance mismatch")
    if source_sha is not None:
        ci = provenance.get("ci") or {}
        if ci.get("repository") != "BE-MX/commission-system" or ci.get("source_sha") != source_sha:
            raise VerificationError("CI source provenance mismatch")
    _inspect_wheel(root / SDK_WHEEL, runtime=False)
    runtime_files = _inspect_wheel(root / RUNTIME_WHEEL, runtime=True)
    _verify_executable_modes(root / RUNTIME_WHEEL)
    glibc_versions, needed, elf_count = _runtime_elf_contract(runtime_files)
    auditwheel_policy = _auditwheel_policy(root / RUNTIME_WHEEL)
    return {
        "schema_version": 1,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed",
        "source_sha": source_sha,
        "upstream_commit": EXPECTED_UPSTREAM["commit"],
        "runtime_tag": "py3-none-manylinux_2_28_x86_64",
        "auditwheel_policy": auditwheel_policy,
        "elf_files_checked": elf_count,
        "glibc_versions": sorted(glibc_versions, key=lambda item: tuple(map(int, item.split(".")))),
        "needed_libraries": sorted(needed),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_dir", type=Path)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--initialize-report", type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_sha):
        parser.error("--source-sha must be a lowercase 40-character Git commit SHA")
    root = args.artifact_dir.resolve()
    initialize = args.initialize_report is not None
    if initialize:
        report_path = args.initialize_report.resolve()
        if report_path != root / "VERIFICATION.json" or report_path.exists():
            parser.error("initial report must be a new VERIFICATION.json inside the bundle")
    try:
        report = verify(root, require_report=not initialize, source_sha=args.source_sha)
    except (OSError, ValueError, VerificationError) as exc:
        parser.error(str(exc))
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if initialize:
        args.initialize_report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
