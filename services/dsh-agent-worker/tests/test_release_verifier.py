from __future__ import annotations

from base64 import urlsafe_b64encode
import hashlib
import importlib.util
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_dsh_release.py"
SPEC = importlib.util.spec_from_file_location("ark_dsh_release_verifier", SCRIPT)
verifier = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(verifier)


def _record_line(name: str, body: bytes) -> str:
    digest = urlsafe_b64encode(hashlib.sha256(body).digest()).rstrip(b"=").decode()
    return f"{name},sha256={digest},{len(body)}"


def _wheel(
    tmp_path: Path,
    *,
    runtime: bool,
    missing_dependency: bool = False,
    missing_license: bool = False,
    wrong_payload: bool = False,
) -> Path:
    filename = verifier.RUNTIME_WHEEL if runtime else verifier.SDK_WHEEL
    dist = "deepseek_harness_runtime_bin" if runtime else "deepseek_harness_sdk"
    metadata_dir = f"{dist}-0.1.0rc8.dist-info"
    requirements = "" if runtime or missing_dependency else "Requires-Dist: deepseek-harness-runtime-bin==0.1.0rc8\n"
    licenses = "License-File: LICENSE\n" + ("License-File: THIRD_PARTY_NOTICES.md\n" if runtime else "")
    files = {
        f"{metadata_dir}/METADATA": (
            "Metadata-Version: 2.4\n"
            f"Name: {'deepseek-harness-runtime-bin' if runtime else 'deepseek-harness-sdk'}\n"
            "Version: 0.1.0rc8\nLicense-Expression: MIT\n"
            f"{licenses}{requirements}\n"
        ).encode(),
        f"{metadata_dir}/WHEEL": (
            "Wheel-Version: 1.0\n"
            f"Tag: {'py3-none-manylinux_2_28_x86_64' if runtime else 'py3-none-any'}\n"
        ).encode(),
    }
    if not missing_license:
        files[f"{metadata_dir}/licenses/LICENSE"] = b"MIT"
    if runtime:
        files[f"{metadata_dir}/licenses/THIRD_PARTY_NOTICES.md"] = b"notices"
        payloads = {"totally_wrong/runtime/not-dsh"} if wrong_payload else verifier.EXPECTED_RUNTIME_PAYLOADS
        for payload in payloads:
            files[payload] = b"\x7fELFfake"
    record_name = f"{metadata_dir}/RECORD"
    record = "\n".join([*(_record_line(name, body) for name, body in files.items()), f"{record_name},,"]) + "\n"
    files[record_name] = record.encode()
    path = tmp_path / filename
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, body in files.items():
            info = ZipInfo(name)
            info.external_attr = (0o100755 if name in verifier.EXPECTED_RUNTIME_PAYLOADS else 0o100644) << 16
            archive.writestr(info, body)
    return path


def test_wheel_contract_rejects_the_previous_fake_runtime_payload(tmp_path):
    wheel = _wheel(tmp_path, runtime=True, wrong_payload=True)
    with pytest.raises(verifier.VerificationError, match="payload inventory"):
        verifier._inspect_wheel(wheel, runtime=True)


def test_wheel_contract_requires_sdk_runtime_pin(tmp_path):
    wheel = _wheel(tmp_path, runtime=False, missing_dependency=True)
    with pytest.raises(verifier.VerificationError, match="does not pin"):
        verifier._inspect_wheel(wheel, runtime=False)


def test_wheel_contract_requires_declared_license_payload(tmp_path):
    wheel = _wheel(tmp_path, runtime=False, missing_license=True)
    with pytest.raises(verifier.VerificationError, match="packaged wheel license"):
        verifier._inspect_wheel(wheel, runtime=False)


def test_wheel_contract_rejects_record_tampering(tmp_path):
    wheel = _wheel(tmp_path, runtime=False)
    with ZipFile(wheel, "a") as archive:
        archive.writestr("unexpected", b"not in record")
    with pytest.raises(verifier.VerificationError, match="RECORD inventory"):
        verifier._inspect_wheel(wheel, runtime=False)


def test_bundle_requires_sealed_report_and_rejects_extra_files(tmp_path):
    for name in verifier.CHECKSUM_FILES:
        (tmp_path / name).write_bytes(name.encode())
    lines = [f"{hashlib.sha256(name.encode()).hexdigest()}  {name}" for name in sorted(verifier.CHECKSUM_FILES)]
    (tmp_path / "SHA256SUMS").write_text("\n".join(lines) + "\n")
    verifier._checksum_manifest(tmp_path, require_report=False)
    with pytest.raises(verifier.VerificationError, match="missing or unexpected"):
        verifier._checksum_manifest(tmp_path, require_report=True)
    (tmp_path / "unchecksummed.txt").write_text("x")
    with pytest.raises(verifier.VerificationError, match="unchecksummed"):
        verifier._checksum_manifest(tmp_path, require_report=False)
