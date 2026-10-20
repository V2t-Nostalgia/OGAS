# SPDX-FileCopyrightText: 2026 Nostalgia and OGAS contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Publication never removes originals or confuses a derivative with raw data."""

import gzip
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "ogas_archive_test_module", Path(__file__).resolve().parents[2] / "research/archive_evidence.py"
)
archive = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(archive)


class EvidenceArchiveTests(unittest.TestCase):
    def test_review_withholds_all_aliases_without_removing_originals(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / 'input'
            source.mkdir()
            raw = b'Uncleared source text'
            for name in ('uncleared.txt', 'duplicate.txt'):
                (source / name).write_bytes(raw)
            (source / 'observations.json').write_bytes(b'{"command_count":2}')
            archive.build([('batch', source)], base / 'export', {}, 'a' * 40)
            result = archive.review(base / 'export/public', base / 'reviewed', ['uncleared'])
            self.assertEqual(result['restricted_by_review'], 2)
            self.assertEqual(result['public_objects'], 1)
            self.assertTrue((source / 'uncleared.txt').is_file())
            rows = [json.loads(line) for line in (base / 'reviewed/index.jsonl').read_text().splitlines()]
            denied = next(r for r in rows if r['path'].endswith('duplicate.txt'))
            self.assertIsNone(denied['object'])
            archive.verify(base / 'export/local-vault/original-index.jsonl', base / 'export/local-vault/objects', original=True)

    def test_fast_credential_filter_preserves_unicode_and_ascii_rules(self):
        samples = ['{"password":"example-secret"}', '{"prıvate_key":"example-secret"}',
                   'https://example:example@example.invalid/', 'Bearer ' + 'X' * 20,
                   '{"command":"CExampleCommand","token":123}', 'normal 只读观察']
        for text in samples:
            self.assertEqual(archive.contains_credentials(text), archive.SECRET.search(text) is not None)

    def test_partial_export_objects_are_verified_before_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "input"
            source.mkdir()
            raw = b'{"result":false}\n'
            (source / 'record.json').write_bytes(raw)
            previous = base / 'previous'
            for store in ('local-vault', 'public'):
                archive.put(previous / store / 'objects', raw)
            expected = archive.sha(raw)
            old = previous / 'public/objects' / expected[:2] / (expected + '.gz')
            old.write_bytes(b'not gzip')
            archive.build([('batch', source)], base / 'new', {}, 'a' * 40, reuse_from=[previous])
            result = archive.verify(base / 'new/public/index.jsonl', base / 'new/public/objects')
            self.assertEqual(result['verified_objects'], 1)
            self.assertEqual(old.read_bytes(), b'not gzip')
            self.assertTrue((base / 'new/local-vault/snapshot-journal.jsonl').is_file())

    def test_all_outcomes_deduplicate_and_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "input"
            source.mkdir()
            body = b'{"result":"failed","reason":"interrupted"}\n'
            for name in ("success.json", "failure.json", "interrupted.json"):
                (source / name).write_bytes(body)
            summary = archive.build([("batch", source)], base / "export", {}, "a" * 40)
            self.assertEqual(summary["counts"]["files"], 3)
            self.assertEqual(summary["unique_public_objects"], 1)
            public = base / "export/public"
            result = archive.verify(public / "index.jsonl", public / "objects")
            self.assertEqual(result["mapped_files"], 3)
            archive.restore(public / "index.jsonl", public / "objects", base / "restored")
            self.assertEqual((base / "restored/batch/failure.json").read_bytes(), body)
            self.assertEqual((source / "failure.json").read_bytes(), body)
            with self.assertRaises(FileExistsError):
                archive.build([("batch", source)], base / "export", {}, "a" * 40)

    def test_private_derivative_is_valid_json_and_original_is_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "input"
            source.mkdir()
            raw = json.dumps({"path": "C:\\Users\\Example\\study.json", "result": False}).encode()
            (source / "review.json").write_bytes(raw)
            archive.build([("batch", source)], base / "export", {}, "a" * 40)
            public = base / "export/public"
            row = json.loads((public / "index.jsonl").read_text())
            self.assertNotEqual(row["original_sha256"], row["public_sha256"])
            self.assertEqual(row["access"], "public_redacted_derivative_original_retained")
            with gzip.open(public / row["object"], "rb") as stream:
                self.assertFalse(json.load(stream)["result"])
            vault = base / "export/local-vault"
            archive.verify(vault / "original-index.jsonl", vault / "objects", original=True)
            archive.restore(vault / "original-index.jsonl", vault / "objects", base / "private-restored", original=True)
            self.assertEqual((base / "private-restored/batch/review.json").read_bytes(), raw)
            with gzip.open(vault / "objects" / archive.sha(raw)[:2] / (archive.sha(raw) + ".gz"), "rb") as stream:
                self.assertEqual(stream.read(), raw)

    def test_restricted_inputs_never_published(self):
        for path, raw in (("x.sav", b"save"), ("game", b"\x7fELFxx"),
                          ("image.png", b"image"), ("raw.json", b'{"password":"example-secret"}')):
            with self.subTest(path=path):
                self.assertIsNone(archive.public_copy(path, raw, {})[0])

    def test_rotated_gzip_keeps_original_or_explicit_derivative(self):
        raw = gzip.compress(b'{"command":"CExampleCommand"}\n', mtime=0)
        self.assertEqual(archive.public_copy("x.jsonl.1.ready.gz", raw, {}), (raw, "public_original"))
        raw = gzip.compress(b'{"path":"/home/example/a"}\n', mtime=0)
        exported, label = archive.public_copy("x.jsonl.1.ready.gz", raw, {})
        self.assertIn("derivative", label)
        self.assertIn("LOCAL_USER", json.loads(gzip.decompress(exported))["path"])

    def test_remote_stability_not_hidden_by_local_transfer(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "input"
            source.mkdir()
            raw = b"{}"
            (source / "record.json").write_bytes(raw)
            remote = base / "remote.jsonl"
            remote.write_text(json.dumps({"path": "record.json", "sha256": archive.sha(raw),
                                          "size": len(raw), "stable": False}) + "\n")
            archive.build([("remote", source)], base / "export", {}, "a" * 40, [remote])
            row = json.loads((base / "export/public/index.jsonl").read_text())
            self.assertFalse(row["stable_snapshot"])

    def test_hash_and_path_traversal_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            index = base / "index.jsonl"
            index.write_text(json.dumps({"path": "../escape", "public_sha256": "a" * 64}) + "\n")
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                archive.restore(index, base, base / "restore")
            index.write_text(json.dumps({"public_sha256": "../../escape"}) + "\n")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                archive.verify(index, base)


if __name__ == "__main__":
    unittest.main()
