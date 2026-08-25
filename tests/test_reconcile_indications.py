from __future__ import annotations

import unittest

from moalmanac_fda_curation.core.reconcile_indications import reconcile_indications


class ReconcileIndicationsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.existing = [
            {
                "id": "ind:1",
                "indication": "Drug for BRAF-positive melanoma",
                "document_id": "doc:fda.example",
                "initial_approval_date": "2020-01-01",
            },
            {
                "id": "ind:2",
                "indication": "Drug for RET-positive lung cancer",
                "document_id": "doc:fda.example",
            },
        ]
        self.latest = [
            {
                "latest_indication_index": 0,
                "indication": "Drug for adult BRAF-positive melanoma",
                "raw_biomarkers": "BRAF-positive",
                "source_chunk_index": 3,
            },
            {
                "latest_indication_index": 1,
                "indication": "Drug for ALK-positive lung cancer",
                "raw_biomarkers": "ALK-positive",
                "source_chunk_index": 4,
            },
        ]

    def test_prompt_contains_only_trace_ids_and_indication_strings(self) -> None:
        prompts = []

        reconcile_indications(
            self.existing,
            self.latest,
            llm=lambda prompt: prompts.append(prompt) or {"mappings": []},
        )

        prompt = prompts[0]
        self.assertIn('"id": "ind:1"', prompt)
        self.assertIn('"latest_indication_index": 0', prompt)
        self.assertIn('"indication": "Drug for BRAF-positive melanoma"', prompt)
        self.assertNotIn("document_id", prompt)
        self.assertNotIn("initial_approval_date", prompt)
        self.assertNotIn("raw_biomarkers", prompt)
        self.assertNotIn("source_chunk_index", prompt)
        self.assertIn("same underlying", prompt)
        self.assertIn("details or wording have changed", prompt)
        self.assertIn("separate downstream task", prompt)
        self.assertNotIn("same`:", prompt)
        self.assertNotIn("revised`:", prompt)

    def test_reconciliation_hydrates_and_verifies_complete_mapping(self) -> None:
        result = reconcile_indications(
            self.existing,
            self.latest,
            llm=lambda _: {"mappings": [
                {
                    "existing_indication_id": "ind:1",
                    "latest_indication_index": 0,
                    "classification": "matched",
                    "reason": "Adult qualifier added.",
                },
                {
                    "existing_indication_id": "ind:2",
                    "latest_indication_index": None,
                    "classification": "not_found",
                    "reason": "No latest counterpart.",
                },
                {
                    "existing_indication_id": None,
                    "latest_indication_index": 1,
                    "classification": "new",
                    "reason": "No existing counterpart.",
                },
            ]},
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["mappings"][0]["existing_indication"]["id"], "ind:1")
        self.assertEqual(result["mappings"][0]["latest_indication"]["latest_indication_index"], 0)

    def test_missing_and_duplicate_coverage_fail_verification(self) -> None:
        result = reconcile_indications(
            self.existing,
            self.latest,
            llm=lambda _: {"mappings": [
                {
                    "existing_indication_id": "ind:1",
                    "latest_indication_index": 0,
                    "classification": "matched",
                    "reason": "Same.",
                },
                {
                    "existing_indication_id": "ind:1",
                    "latest_indication_index": 1,
                    "classification": "uncertain",
                    "reason": "Ambiguous.",
                },
            ]},
        )
        self.assertFalse(result["verified"])
        self.assertIn("Existing indication mapped more than once: ind:1", result["verification_errors"])
        self.assertIn("Existing indication not accounted for: ind:2", result["verification_errors"])


if __name__ == "__main__":
    unittest.main()
