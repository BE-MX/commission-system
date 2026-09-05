"""Temporary-filesystem deployment safety regression tests; no production access."""

import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import remote_static as release
import static_sync


def digest(value):
    return hashlib.sha256(value).hexdigest()


@unittest.skipUnless(sys.platform == "linux", "Remote filesystem semantics are tested on Linux")
class StaticReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.root = self.directory / "site"

    def tearDown(self):
        self.temporary.cleanup()

    def bundle(self, files):
        path = self.directory / "bundle.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            for name, content in files.items():
                entry = tarfile.TarInfo(name)
                entry.size = len(content)
                archive.addfile(entry, io.BytesIO(content))
        return path

    def publish(self, files):
        manifest = {name: digest(content) for name, content in files.items()}
        expected = release.plan(self.root, manifest)["active_artifact"]
        release.stage(self.root, manifest, self.bundle(files))
        release.activate(self.root, manifest, expected)
        return manifest

    def test_roundtrip_and_noop(self):
        manifest = self.publish({"index.html": b"A", "assets/a.js": b"a"})
        self.assertEqual((self.root / "index.html").read_bytes(), b"A")
        self.assertEqual(release.plan(self.root, manifest)["missing"], [])
        self.assertEqual(release.activate(self.root, manifest, release.artifact_id(manifest))["status"], "unchanged")

    def test_initial_directory_is_exchanged_without_nginx_changes(self):
        self.root.mkdir()
        (self.root / "index.html").write_bytes(b"legacy")
        self.publish({"index.html": b"new"})
        self.assertTrue(self.root.is_symlink())
        self.assertEqual((self.root / "index.html").read_bytes(), b"new")
        legacy = list((self.directory / ".site-releases").glob("legacy-*"))
        self.assertEqual((legacy[0] / "index.html").read_bytes(), b"legacy")

    def test_first_http_failure_restores_original_directory(self):
        self.root.mkdir()
        (self.root / "index.html").write_bytes(b"legacy")
        files = {"index.html": digest(b"new")}
        release.stage(self.root, files, self.bundle({"index.html": b"new"}))
        with patch.object(release, "verify_http", side_effect=RuntimeError("wrong vhost")):
            with self.assertRaises(RuntimeError):
                release.activate(self.root, files, None, "leshine.cloud")
        self.assertFalse(self.root.is_symlink())
        self.assertEqual((self.root / "index.html").read_bytes(), b"legacy")

    def test_rollback_keeps_newer_browser_chunks(self):
        a = self.publish({"index.html": b"A", "assets/a.js": b"a"})
        b = self.publish({"index.html": b"B", "assets/b.js": b"b"})
        release.stage(self.root, a, self.bundle({}))
        release.activate(self.root, a, release.artifact_id(b))
        self.assertEqual((self.root / "index.html").read_bytes(), b"A")
        self.assertEqual((self.root / "assets/b.js").read_bytes(), b"b")

    def test_corrupt_transfer_never_changes_live(self):
        old = self.publish({"index.html": b"old"})
        new = {"index.html": digest(b"new")}
        with self.assertRaisesRegex(ValueError, "checksum"):
            release.stage(self.root, new, self.bundle({"index.html": b"corrupt"}))
        self.assertEqual(release.plan(self.root, old)["active_artifact"], release.artifact_id(old))

    def test_symlinked_asset_directory_is_rejected(self):
        self.root.mkdir()
        external = self.directory / "external"
        external.mkdir()
        (external / "secret.js").write_bytes(b"secret")
        (self.root / "assets").symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            release.stage(self.root, {"index.html": digest(b"A")}, self.bundle({"index.html": b"A"}))

    def test_compare_and_swap_refuses_another_publisher(self):
        a = self.publish({"index.html": b"A"})
        b = self.publish({"index.html": b"B"})
        c = {"index.html": digest(b"C")}
        release.stage(self.root, c, self.bundle({"index.html": b"C"}))
        with self.assertRaisesRegex(ValueError, "Another publisher"):
            release.activate(self.root, c, release.artifact_id(a))
        self.assertEqual((self.root / "index.html").read_bytes(), b"B")

    def test_http_failure_restores_previous_pointer(self):
        a = self.publish({"index.html": b"A"})
        b = {"index.html": digest(b"B")}
        release.stage(self.root, b, self.bundle({"index.html": b"B"}))
        with patch.object(release, "verify_http", side_effect=RuntimeError("wrong vhost")):
            with self.assertRaises(RuntimeError):
                release.activate(self.root, b, release.artifact_id(a), "leshine.cloud")
        self.assertEqual((self.root / "index.html").read_bytes(), b"A")

    def test_path_traversal_and_links_rejected(self):
        for name in ("../secret", "/secret", "a/../secret", ".env", "a\\b", "a//b", "release.json"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                release.safe_relative(name)
        path = self.directory / "link.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            entry = tarfile.TarInfo("index.html")
            entry.type = tarfile.SYMTYPE
            entry.linkname = "/etc/passwd"
            archive.addfile(entry)
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            release.stage(self.root, {"index.html": digest(b"A")}, path)

    def test_client_noop_has_no_scp_or_stage(self):
        source = self.directory / "source"
        source.mkdir()
        (source / "index.html").write_bytes(b"A")
        manifest = static_sync.manifest(source)
        ident = release.artifact_id(manifest)
        response = {"missing": [], "initialized": True, "active_artifact": ident, "artifact": ident}
        with patch.object(static_sync, "remote", return_value=response) as remote, patch.object(static_sync, "run") as run:
            result = static_sync.prepare(source, "target", "/var/www/ark-dist", self.directory, "leshine.cloud")
        self.assertEqual(result["bytes"], 0)
        self.assertEqual(remote.call_count, 1)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
