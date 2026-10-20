from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


class TestDiscoveryTests(unittest.TestCase):
    def test_immutable_evidence_snapshots_are_not_maintained_test_modules(self):
        runner = Path(__file__).resolve().parents[1] / "run_tests.py"
        spec = importlib.util.spec_from_file_location("test_discovery_runner", runner)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            maintained = root / "src/tests/test_current.py"
            archived = root / ".runtime-evidence/round/source/test_current.py"
            scratch = root / ".tmp/experiment/test_current.py"
            for path in (maintained, archived, scratch):
                path.parent.mkdir(parents=True)
                path.touch()
            self.assertEqual(module.test_modules(root), [maintained.resolve()])
            self.assertTrue(archived.is_file())


if __name__ == "__main__":
    unittest.main()
