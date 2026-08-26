from __future__ import annotations

import unittest

from moalmanac_fda_curation.core.propose_indication_revision import (
    build_latest_label_revision_prompt,
    propose_indication_revision,
)


class ProposeIndicationRevisionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.existing = {
            "id": "ind:fda.example:0",
            "document_id": "doc:fda.example",
            "indication": "EXAMPLE is indicated for patients with BRAF-positive cancer.",
            "description": "FDA approved example for patients with BRAF-positive cancer. Trial A supported approval.",
            "raw_biomarkers": "BRAF-positive",
            "raw_cancer_type": "cancer",
            "raw_therapeutics": "Example",
            "initial_approval_date": "2020-01-01",
            "initial_approval_url": "https://example.test/initial.pdf",
        }
        self.latest = {
            "indication": "EXAMPLE is indicated for adult patients with BRAF-positive cancer.",
            "raw_biomarkers": "BRAF-positive",
            "raw_cancer_type": "cancer",
            "raw_therapeutics": "Example",
            "source_chunk_index": 4,
        }
        self.assessment = {
            "classification": "revised",
            "meaningful_differences": [{
                "existing_wording": "patients",
                "latest_wording": "adult patients",
                "difference": "The newer wording specifies an adult population.",
            }],
            "reason": "Adult eligibility was added.",
        }

    def test_prompt_contains_only_editable_content_and_guidance(self) -> None:
        prompt = build_latest_label_revision_prompt(
            self.existing, self.latest, self.assessment
        )
        self.assertIn("adult patients", prompt)
        self.assertIn("The newer wording specifies an adult population", prompt)
        self.assertNotIn("document_id", prompt)
        self.assertNotIn("initial_approval_date", prompt)
        self.assertNotIn("source_chunk_index", prompt)

    def test_applies_minimal_patch_and_preserves_provenance(self) -> None:
        result = propose_indication_revision(
            self.existing,
            self.latest,
            self.assessment,
            llm=lambda _: {"updates": [
                {
                    "field": "indication",
                    "new_value": "EXAMPLE is indicated for adult patients with BRAF-positive cancer.",
                },
                {
                    "field": "description",
                    "new_value": "FDA approved example for adult patients with BRAF-positive cancer. Trial A supported approval.",
                },
                {
                    "field": "raw_biomarkers",
                    "new_value": "BRAF-positive",
                },
            ]},
        )
        self.assertEqual(
            set(result["changes"]),
            {"indication", "description"},
        )
        self.assertEqual(result["proposed_indication"]["id"], self.existing["id"])
        self.assertEqual(
            result["proposed_indication"]["initial_approval_date"],
            "2020-01-01",
        )
        self.assertIn("Trial A", result["proposed_indication"]["description"])

    def test_requires_revised_assessment(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires a pairwise 'revised'"):
            propose_indication_revision(
                self.existing,
                self.latest,
                {**self.assessment, "classification": "same"},
                llm=lambda _: {"updates": []},
            )


if __name__ == "__main__":
    unittest.main()
