from __future__ import annotations

import unittest

from moalmanac_fda_curation.core.reconcile_indications import reconcile_indications


class ReconcileIndicationsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.existing = [
            {"id": "ind:1", "indication": "Drug for BRAF-positive melanoma", "document_id": "doc:1"},
            {"id": "ind:2", "indication": "Drug for RET-positive lung cancer", "document_id": "doc:1"},
        ]
        self.latest = [
            {"latest_indication_index": 0, "indication": "Drug for adult BRAF-positive melanoma", "raw_biomarkers": "BRAF"},
            {"latest_indication_index": 1, "indication": "Drug for ALK-positive lung cancer", "raw_biomarkers": "ALK"},
        ]

    def test_maps_identity_in_one_call(self) -> None:
        prompts = []
        result = reconcile_indications(
            self.existing,
            self.latest,
            llm=lambda prompt: prompts.append(prompt) or {"mappings": [
                {
                    "existing_indication_id": "ind:1",
                    "latest_indication_index": 0,
                    "classification": "matched",
                    "reason": "Same use with an adult qualifier.",
                },
                {"existing_indication_id": "ind:2", "latest_indication_index": None, "classification": "not_found", "reason": "No counterpart."},
                {"existing_indication_id": None, "latest_indication_index": 1, "classification": "new", "reason": "No counterpart."},
            ]},
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["mappings"][0]["classification"], "matched")
        self.assertEqual(result["mappings"][0]["existing_indication"]["id"], "ind:1")
        prompt = prompts[0]
        self.assertIn("only about identity across label versions", prompt)
        self.assertIn("Do not compare or report wording differences", prompt)
        self.assertNotIn("`same`:", prompt)
        self.assertNotIn("`revised`:", prompt)
        self.assertNotIn("document_id", prompt)
        self.assertNotIn("raw_biomarkers", prompt)

    def test_matched_pair_requires_both_sides(self) -> None:
        result = reconcile_indications(
            [self.existing[0]],
            [self.latest[0]],
            llm=lambda _: {"mappings": [
                {
                    "existing_indication_id": "ind:1",
                    "latest_indication_index": None,
                    "classification": "matched",
                    "reason": "Match missing its latest side.",
                },
                {
                    "existing_indication_id": None,
                    "latest_indication_index": 0,
                    "classification": "new",
                    "reason": "No counterpart.",
                },
            ]},
        )
        self.assertFalse(result["verified"])
        self.assertIn(
            "Mapping 0 classification matched requires both sides",
            result["verification_errors"],
        )

    def test_missing_and_duplicate_coverage_fail_verification(self) -> None:
        result = reconcile_indications(
            self.existing,
            self.latest,
            llm=lambda _: {"mappings": [
                {"existing_indication_id": "ind:1", "latest_indication_index": 0, "classification": "matched", "reason": "Matched."},
                {"existing_indication_id": "ind:1", "latest_indication_index": 1, "classification": "uncertain", "reason": "Ambiguous."},
            ]},
        )
        self.assertFalse(result["verified"])
        self.assertIn("Existing indication mapped more than once: ind:1", result["verification_errors"])
        self.assertIn("Existing indication not accounted for: ind:2", result["verification_errors"])


if __name__ == "__main__":
    unittest.main()
