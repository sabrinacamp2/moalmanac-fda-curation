from __future__ import annotations

import unittest

from moalmanac_fda_curation.core.propose_revised_indication import (
    build_label_diff_revision_prompt,
    propose_revised_indication,
)


class ProposeRevisedIndicationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.existing = {
            "id": "ind:fda.example:0",
            "document_id": "doc:fda.example",
            "indication": "EXAMPLE is indicated for patients tested with an FDA-approved test.",
            "description": "FDA approved EXAMPLE for this population. Trial A supported approval.",
            "raw_biomarkers": "marker-positive",
            "raw_cancer_type": "cancer",
            "raw_therapeutics": "Example",
            "initial_approval_date": "2020-01-01",
            "initial_approval_url": "https://example.test/initial.pdf",
        }
        self.assessment = {
            "existing_indication_id": self.existing["id"],
            "status": "revised",
            "relevant_hunk_ids": ["hunk-1"],
            "changes": ["The test designation changed."],
            "reason": "Supported by the source diff.",
        }
        self.hunks = [{
            "hunk_id": "hunk-1",
            "baseline_text": "Target uses an FDA-approved test. Other indication.",
            "latest_text": "Target uses an FDA-authorized test. Other indication.",
        }]

    def test_prompt_is_scoped_to_assessed_changes(self) -> None:
        prompt = build_label_diff_revision_prompt(
            self.existing, self.assessment, self.hunks
        )
        self.assertIn("The test designation changed", prompt)
        self.assertIn("FDA-authorized test", prompt)
        self.assertIn("A changed passage may contain other indications", prompt)
        self.assertIn("Preserve existing drug-class wording", prompt)
        self.assertIn("inspect `description` for the same affected wording", prompt)
        self.assertIn("meaning. Update corresponding language", prompt)
        self.assertIn("population, biomarker, treatment, or setting", prompt)
        self.assertNotIn("initial_approval_date", prompt)

    def test_applies_proposal_and_preserves_provenance(self) -> None:
        result = propose_revised_indication(
            self.existing,
            self.assessment,
            self.hunks,
            llm=lambda _: {"updates": [{
                "field": "indication",
                "new_value": self.existing["indication"].replace(
                    "FDA-approved", "FDA-authorized"
                ),
            }]},
        )
        self.assertEqual(result["supporting_hunk_ids"], ["hunk-1"])
        self.assertEqual(set(result["changes"]), {"indication"})
        self.assertEqual(
            result["proposed_indication"]["initial_approval_date"],
            self.existing["initial_approval_date"],
        )

    def test_requires_matching_revised_assessment(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not target"):
            propose_revised_indication(
                self.existing,
                {**self.assessment, "existing_indication_id": "ind:other"},
                self.hunks,
                llm=lambda _: {"updates": []},
            )
        with self.assertRaisesRegex(ValueError, "requires a 'revised'"):
            propose_revised_indication(
                self.existing,
                {**self.assessment, "status": "not_revised"},
                self.hunks,
                llm=lambda _: {"updates": []},
            )

    def test_allows_no_update_when_hunk_is_not_target_specific_enough(self) -> None:
        result = propose_revised_indication(
            self.existing,
            self.assessment,
            self.hunks,
            llm=lambda _: {"updates": []},
        )
        self.assertEqual(result["changes"], {})
        self.assertEqual(result["proposed_indication"], self.existing)

if __name__ == "__main__":
    unittest.main()
