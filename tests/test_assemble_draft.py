from __future__ import annotations

import unittest

from moalmanac_curation.assemble_draft import assemble


class AssembleDraftTest(unittest.TestCase):
    def setUp(self) -> None:
        self.document = {
            "id": "doc:fda.example",
            "drug_name_brand": "Example",
            "drug_name_generic": "examplemab",
            "identification_number": 123,
            "urls": ["https://example.test/label.pdf"],
        }
        self.indications = {
            "indications": [
                {
                    "indication": "Example indication",
                    "raw_biomarkers": "GENE mutation",
                    "raw_cancer_type": "cancer",
                    "raw_therapeutics": "Example (examplemab)",
                }
            ]
        }
        self.descriptions = {
            "indications": [{"indication_index": 0, "description": "Description"}]
        }
        self.dates = [
            {
                "indication_index": 0,
                "verification": {
                    "verified": True,
                    "matched_event": {
                        "date": "2025-01-02",
                        "label_url": "https://example.test/initial.pdf",
                    },
                },
            }
        ]

    def test_assembles_verified_indication(self) -> None:
        result = assemble(
            self.document,
            self.indications,
            self.descriptions,
            self.dates,
            include_all_indications=False,
        )
        self.assertEqual(result[0]["id"], "ind:fda.example:0")
        self.assertEqual(result[0]["initial_approval_date"], "2025-01-02")

    def test_rejects_unverified_date(self) -> None:
        self.dates[0]["verification"]["verified"] = False
        with self.assertRaisesRegex(ValueError, "not verified"):
            assemble(
                self.document,
                self.indications,
                self.descriptions,
                self.dates,
                include_all_indications=False,
            )


if __name__ == "__main__":
    unittest.main()
