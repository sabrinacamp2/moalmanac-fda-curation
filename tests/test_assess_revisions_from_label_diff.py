from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from moalmanac_fda_curation.core.assess_revisions_from_label_diff import (
    assess_revisions_from_label_diff,
    build_revision_assessment_prompt,
    build_section_diff_hunks,
    load_section_pair_from_cache,
)


class AssessRevisionsFromLabelDiffTest(unittest.TestCase):
    def test_loads_cached_sections_while_ignoring_url_scheme(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            path.write_text(json.dumps({
                "http://example.test/old.pdf": "old section",
                "http://example.test/new.pdf": "new section",
            }))
            pair = load_section_pair_from_cache(
                path,
                baseline_label_url="https://example.test/old.pdf",
                latest_label_url="https://example.test/new.pdf",
            )
        self.assertEqual(pair["baseline_section"], "old section")
        self.assertEqual(pair["latest_section"], "new section")

    def test_builds_deterministic_hunks_with_context(self) -> None:
        baseline = """1.1 First\nDrug is indicated for population A.\n1.2 Second\nDrug is indicated for population B."""
        latest = """1.1 First\nDrug is indicated for adult population A.\n1.2 Second\nDrug is indicated for population B."""
        hunks = build_section_diff_hunks(baseline, latest, context_blocks=1)
        self.assertEqual(len(hunks), 1)
        self.assertEqual(hunks[0]["hunk_id"], "hunk-1")
        self.assertIn("population A", hunks[0]["baseline_text"])
        self.assertIn("adult population A", hunks[0]["latest_text"])
        self.assertEqual(hunks[0]["latest_context_after"], ["Drug is indicated for population B."])

    def test_assesses_every_existing_indication_and_hydrates_hunks(self) -> None:
        existing = [{"id": "ind:1", "indication": "Drug for population A"}]
        hunks = [{
            "hunk_id": "hunk-1",
            "change_type": "replace",
            "baseline_text": "Drug for population A",
            "latest_text": "Drug for adult population A",
            "baseline_context_before": [],
            "baseline_context_after": [],
            "latest_context_before": [],
            "latest_context_after": [],
        }]
        result = assess_revisions_from_label_diff(
            existing,
            hunks,
            llm=lambda _: {"assessments": [{
                "existing_indication_id": "ind:1",
                "status": "revised",
                "relevant_hunk_ids": ["hunk-1"],
                "changes": ["The population is now explicitly adult."],
                "reason": "The hunk changes the target population wording.",
            }]},
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["assessments"][0]["relevant_hunks"][0], hunks[0])

    def test_prompt_is_source_diff_focused(self) -> None:
        prompt = build_revision_assessment_prompt(
            [{"id": "ind:1", "indication": "Drug for population A", "description": "omit"}],
            [{"hunk_id": "hunk-1", "baseline_text": "before", "latest_text": "after"}],
        )
        self.assertIn("generated deterministically from the source label text", prompt)
        self.assertIn("A new indication", prompt)
        self.assertNotIn("description", prompt)


if __name__ == "__main__":
    unittest.main()
