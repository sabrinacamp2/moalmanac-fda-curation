from __future__ import annotations

import unittest
from pathlib import Path

from moalmanac_fda_curation.review.revision_assembly import (
    assemble_updated_indications,
    comparison_markdown,
)


class RevisionAssemblyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.existing = {
            "id": "ind:fda.example:7",
            "document_id": "doc:fda.example",
            "indication": "Old indication wording.",
            "description": "Old description.",
            "initial_approval_date": "2020-01-01",
            "initial_approval_url": "https://example.test/old.pdf",
            "raw_biomarkers": "HER2-positive",
            "raw_cancer_type": "breast cancer",
            "raw_therapeutics": "Example",
        }
        self.targets = {
            "targets": [{
                "existing_indication_id": self.existing["id"],
                "latest_indication_index": 1,
                "review_label": "HER2-positive breast cancer",
                "existing_indication": self.existing,
            }]
        }
        self.indications = {"indications": [
            {"indication": "Unused", "raw_biomarkers": None},
            {
                "indication": "New indication wording.",
                "raw_biomarkers": "HER2-positive",
                "raw_cancer_type": "metastatic breast cancer",
                "raw_therapeutics": "Example with chemotherapy",
            },
        ]}
        self.descriptions = {"indications": [{
            "indication_index": 1,
            "description": "New description.",
        }]}
        self.dates = [{
            "indication_index": 1,
            "verification": {
                "verified": True,
                "matched_event": {
                    "date": "2026-01-02",
                    "label_url": "https://example.test/new.pdf",
                },
            },
        }]
        self.decisions = {
            "schema_version": 1,
            "document": {},
            "indications": {"1": {
                "indication": {"decision": "accepted", "overrides": {}},
                "description": {"decision": "accepted", "overrides": {}},
                "approval": {"decision": "accepted", "overrides": {}},
            }},
        }

    def test_assembly_preserves_id_and_uses_reviewed_current_form(self) -> None:
        result = assemble_updated_indications(
            self.targets,
            self.indications,
            self.descriptions,
            self.dates,
            self.decisions,
        )
        self.assertEqual(result[0]["id"], "ind:fda.example:7")
        self.assertEqual(result[0]["indication"], "New indication wording.")
        self.assertEqual(result[0]["initial_approval_date"], "2026-01-02")

    def test_comparison_highlights_removed_and_added_text(self) -> None:
        proposed = assemble_updated_indications(
            self.targets,
            self.indications,
            self.descriptions,
            self.dates,
            self.decisions,
        )[0]
        markdown = comparison_markdown(
            self.targets["targets"][0], proposed, Path("/tmp/review")
        )
        self.assertIn("Existing versus newly curated indication", markdown)
        self.assertIn("Replaced `Old` with `New`", markdown)
        self.assertIn("Current-form date review", markdown)

    def test_incomplete_stage_decision_blocks_assembly(self) -> None:
        del self.decisions["indications"]["1"]["approval"]
        with self.assertRaisesRegex(ValueError, "current-form date"):
            assemble_updated_indications(
                self.targets,
                self.indications,
                self.descriptions,
                self.dates,
                self.decisions,
            )


if __name__ == "__main__":
    unittest.main()
