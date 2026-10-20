from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

try:
    from services.stellaris_native_runtime.research.resolve_event_content import (
        build_catalog,
        collect_event_definitions,
        resolve_localization,
    )
except ModuleNotFoundError:
    from resolve_event_content import (  # type: ignore[no-redef]
        build_catalog,
        collect_event_definitions,
        resolve_localization,
    )


class ResolveEventContentTests(unittest.TestCase):
    def test_resolves_loose_and_dlc_localization_without_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            states = root / "states.jsonl"
            states.write_text(
                json.dumps(
                    {
                        "kind": "event_executed",
                        "content_included": True,
                        "event_definition_id": 7,
                        "event_or_type_key": "story.7",
                        "title_key": "story_title",
                        "description_key": "story_desc",
                        "options": [
                            {"option_index": 0, "text_key": "story_option"}
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            loose = root / "localisation" / "english" / "story_l_english.yml"
            loose.parent.mkdir(parents=True)
            loose.write_text(
                'l_english:\n story_title:0 "A $COUNTRY$ Story"\n'
                ' story_desc:0 "Description"\n',
                encoding="utf-8-sig",
            )
            archive_path = root / "dlc" / "test.zip"
            archive_path.parent.mkdir(parents=True)
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(
                    "localisation/english/options_l_english.yml",
                    'l_english:\n story_option:0 "Continue"\n',
                )

            definitions = collect_event_definitions([states])
            localization = resolve_localization(
                root,
                "english",
                {"story_title", "story_desc", "story_option"},
            )
            catalog = build_catalog(definitions, localization, "english")

            event = catalog["events"]["story.7"]
            self.assertEqual(event["title"]["text"], "A $COUNTRY$ Story")
            self.assertEqual(event["description"]["text"], "Description")
            self.assertEqual(event["options"][0]["text"], "Continue")
            self.assertEqual(catalog["unresolved_keys"], [])
            self.assertIn("not evaluated", catalog["dynamic_rendering_note"])


if __name__ == "__main__":
    unittest.main()
