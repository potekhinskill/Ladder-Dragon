import base64
import csv
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
import zipfile

from ladder_dragon.verification import semgrep_build as rebuild


class RebuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.original_digest = rebuild.SOURCE_HASHES["manylinux_2_34_x86_64"]
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(rebuild.SOURCE_HASHES.__setitem__, "manylinux_2_34_x86_64", self.original_digest)

    def source(self, extra=None, metadata=None):
        data = {
            "semgrep/engine": b"immutable binary payload",
            rebuild.OLD_INFO + "METADATA": metadata or ("Name: semgrep\n" + "\n".join(rebuild.REPLACEMENTS) + "\n\nDescription\n").encode(),
            rebuild.OLD_INFO + "licenses/LICENSE": b"Original license\n",
            rebuild.OLD_INFO + "WHEEL": b"Wheel-Version: 1.0\n",
        }
        if extra:
            data.update(extra)
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        for name, content in data.items():
            encoded = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
            writer.writerow((name, "sha256=" + encoded, len(content)))
        writer.writerow((rebuild.OLD_INFO + "RECORD", "", ""))
        data[rebuild.OLD_INFO + "RECORD"] = output.getvalue().encode()
        path = self.root / ("semgrep-1.168.0-" + rebuild.WHEEL_TAGS + "manylinux_2_34_x86_64.whl")
        with zipfile.ZipFile(path, "w") as archive:
            for name, content in data.items():
                archive.writestr(name, content)
        rebuild.SOURCE_HASHES["manylinux_2_34_x86_64"] = rebuild.digest(path.read_bytes())
        return path

    def test_determinism_and_unchanged_payload(self):
        source = self.source()
        one, two = self.root / "one", self.root / "two"
        one.mkdir()
        two.mkdir()
        first, second = rebuild.rebuild(source, one), rebuild.rebuild(source, two)
        self.assertEqual(first["wheel_sha256"], second["wheel_sha256"])
        self.assertEqual(first["unchanged_code_entries"], 1)
        self.assertFalse(first["production_allowed"])
        with zipfile.ZipFile(first["wheel"]) as archive:
            self.assertEqual(archive.read("semgrep/engine"), b"immutable binary payload")
            self.assertEqual(archive.read(rebuild.NEW_INFO + "licenses/LICENSE"), b"Original license\n")
            metadata = archive.read(rebuild.NEW_INFO + "METADATA").decode()
            for line in rebuild.REPLACEMENTS.values():
                self.assertIn(line, metadata)

    def test_existing_result_is_preserved(self):
        source = self.source()
        first = rebuild.rebuild(source, self.root)
        with self.assertRaises(FileExistsError):
            rebuild.rebuild(source, self.root)
        self.assertEqual(rebuild.digest(Path(first["wheel"]).read_bytes()), first["wheel_sha256"])

    def test_hash_mismatch_fails_before_output(self):
        source = self.source()
        rebuild.SOURCE_HASHES["manylinux_2_34_x86_64"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            rebuild.rebuild(source, self.root)
        self.assertEqual(len(list(self.root.glob("*.whl"))), 1)

    def test_metadata_preimage_is_required(self):
        source = self.source(metadata=b"Version: 1.168.0\nName: semgrep\n")
        with self.assertRaisesRegex(ValueError, "preimage mismatch"):
            rebuild.rebuild(source, self.root)

    def test_parent_traversal_is_rejected(self):
        source = self.source(extra={"../unsafe": b"x"})
        with self.assertRaisesRegex(ValueError, "invalid archive entry"):
            rebuild.rebuild(source, self.root)

    def test_absolute_path_is_rejected(self):
        source = self.source(extra={"/unsafe": b"x"})
        with self.assertRaisesRegex(ValueError, "invalid archive entry"):
            rebuild.rebuild(source, self.root)

    def test_source_symlink_is_rejected(self):
        source = self.source()
        link = self.root / "linked.whl"
        link.symlink_to(source)
        with self.assertRaisesRegex(ValueError, "invalid source"):
            rebuild.rebuild(link, self.root)

    def test_incorrect_record_is_rejected(self):
        source = self.source()
        with zipfile.ZipFile(source, "a") as archive:
            archive.writestr("unrecorded", b"x")
        rebuild.SOURCE_HASHES["manylinux_2_34_x86_64"] = rebuild.digest(source.read_bytes())
        with self.assertRaisesRegex(ValueError, "coverage mismatch"):
            rebuild.rebuild(source, self.root)


if __name__ == "__main__":
    unittest.main()
