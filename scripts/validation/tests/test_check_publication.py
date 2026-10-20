# SPDX-FileCopyrightText: 2026 Nostalgia and OGAS contributors
# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location("publication_check_test", Path(__file__).parents[1] / "check_publication.py")
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)


class PublicationCheckTests(unittest.TestCase):
    def test_links_are_relative_to_the_document(self):
        self.assertEqual(list(check.relative_links("docs/a.md", "[ok](../README.md#here) [web](https://example.org)")),
                         [("README.md", "../README.md")])

    def test_ignored_local_target_does_not_satisfy_staged_link(self):
        result = check.audit({"docs/a.md": b"[raw](../.runtime-evidence/report.json)"})
        self.assertIn({"file": "docs/a.md", "target": "../.runtime-evidence/report.json",
                       "reason": "not_in_staged_source_tree"}, result["errors"])

    def test_fenced_examples_are_not_links(self):
        text = "```python\nx = '[fake](missing)'\n```\n[real](present)"
        self.assertEqual(list(check.relative_links("a.md", text)), [("present", "present")])
