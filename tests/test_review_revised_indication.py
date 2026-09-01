from __future__ import annotations

import unittest

from moalmanac_fda_curation.core.review_revised_indication import (
    build_revision_review_prompt,
    review_revised_indication,
)


class ReviewRevisedIndicationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.existing = {
            "id": "ind:fda.example:0",
            "indication": "Use an FDA-approved test.",
            "description": "Existing description.",
        }
        self.assessment = {
            "existing_indication_id": self.existing["id"],
            "status": "revised",
            "relevant_hunk_ids": ["change-1"],
            "changes": ["The test designation changed."],
        }
        self.changes = [{
            "hunk_id": "change-1",
            "baseline_text": "Use an FDA-approved test.",
            "latest_text": "Use an FDA-authorized test.",
        }]
        self.latest = {
            "indication": "Use an FDA-authorized test.",
            "raw_biomarkers": "marker-positive",
        }

    def test_prompt_requests_a_freeform_curator_review(self) -> None:
        prompt = build_revision_review_prompt(
            self.existing,
            self.latest,
            self.assessment,
            self.changes,
            "Event 1: FDA-approved. Event 2: FDA-authorized.",
        )
        self.assertIn("omitted from the existing", prompt)
        self.assertIn("older omission", prompt)
        self.assertIn("complete current values", prompt)
        self.assertIn("at most six plain bullets", prompt)
        self.assertIn("FDA-authorized", prompt)

    def test_returns_structured_proposal(self) -> None:
        response = {
            "rationale": "- Update the test wording.",
            "proposed_fields": {
                "indication": "Use an FDA-authorized test.",
                "description": "Updated description.",
                "raw_biomarkers": "marker-positive",
                "raw_cancer_type": "cancer",
                "raw_therapeutics": "Example",
            },
            "revision_event_number": 2,
        }
        result = review_revised_indication(
            self.existing,
            self.latest,
            self.assessment,
            self.changes,
            "Changelog",
            llm=lambda _: response,
        )
        self.assertEqual(result, response)

    def test_requires_matching_revised_assessment(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not target"):
            review_revised_indication(
                self.existing,
                self.latest,
                {**self.assessment, "existing_indication_id": "ind:other"},
                self.changes,
                "Changelog",
                llm=lambda _: {},
            )


if __name__ == "__main__":
    unittest.main()
