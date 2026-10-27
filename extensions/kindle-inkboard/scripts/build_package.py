"""Build a credential-free, pinned, source-included Kindle add-on package."""
from pathlib import Path
import hashlib
import json
import shutil
import tempfile
import zipfile

import certifi
from prepare_runtime import ROOT, PIN, prepare

VERSION = "0.1.1"
output = ROOT / "dist"
output.mkdir(exist_ok=True)
archive = output / f"ark-board-pw3-{VERSION}.zip"
with tempfile.TemporaryDirectory(prefix="package-", dir=ROOT / ".deps") as temporary:
    stage = Path(temporary)
    plugin = stage / "koreader/plugins/tinta.koplugin"
    prepare(plugin)
    app = stage / "koreader/tinta-apps/ark_board"
    shutil.copytree(ROOT / "client/ark_board", app)
    (app / "certs").mkdir()
    shutil.copyfile(certifi.where(), app / "certs/ca-bundle.crt")
    shutil.copyfile(ROOT / ".deps/tinta/LICENSE", stage / "LICENSE-tinta.txt")
    cert_license = next((Path(certifi.__file__).parent.parent / f"certifi-{certifi.__version__}.dist-info").rglob("LICENSE"))
    shutil.copyfile(cert_license, stage / "LICENSE-certifi.txt")
    shutil.copyfile(ROOT / "docs/INSTALL-PW3.md", stage / "INSTALL-PW3.md")
    shutil.copyfile(ROOT / "scripts/install.ps1", stage / "install.ps1")
    shutil.copyfile(ROOT / "scripts/prepare_runtime.py", stage / "runtime-patch-source.py")
    shutil.copyfile(ROOT / "scripts/localize_runtime.py", stage / "localize-runtime-source.py")
    shutil.copytree(ROOT / "client/locales/zh", stage / "locale-sources/zh")
    (stage / "SOURCE.txt").write_text(
        f"Tinta source: https://github.com/henriquefps/tinta-koreader\nRevision: {PIN}\n"
        "Modifications: after-commit callbacks, persistence guard, app-owned popup dismissal, network wake requests, physical-pixel font sizing, Simplified Chinese UI.\n"
        "All installed Lua source is included. Ark app: AGPL-3.0-or-later. No credentials are included.\n"
        f"CA bundle: certifi {certifi.__version__}, Mozilla CA collection.\n", encoding="utf-8")
    # Plugin entry files such as _meta.lua must be retained; only private dev-app directories are excluded.
    manifest = {}
    for path in stage.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(stage)
        if "tests" in rel.parts or "__pycache__" in rel.parts or ".local." in rel.name:
            continue
        if path.is_relative_to(plugin / "apps") and path.relative_to(plugin / "apps").parts[0].startswith("_"):
            continue
        manifest[rel.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    (stage / "manifest.json").write_text(json.dumps({"version": VERSION, "tinta_revision": PIN,
        "files": manifest}, ensure_ascii=False, indent=2), encoding="utf-8")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
        for name in sorted([*manifest, "manifest.json"]):
            package.write(stage / name, name)
    with zipfile.ZipFile(archive) as package:
        assert package.testzip() is None
        for name, digest in manifest.items():
            assert hashlib.sha256(package.read(name)).hexdigest() == digest
        assert "koreader/plugins/tinta.koplugin/_meta.lua" in package.namelist()
        assert "koreader/tinta-apps/ark_board/init.lua" in package.namelist()
        assert not any(".local." in name for name in package.namelist())
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
(output / (archive.name + ".sha256")).write_text(f"{digest}  {archive.name}\n", encoding="ascii")
print(f"{archive}\n{len(manifest)} files; ZIP CRC and SHA256 manifest verified; {archive.stat().st_size} bytes")
