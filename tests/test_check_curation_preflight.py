from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from moalmanac_fda_curation.core.check_curation_preflight import (
    check_curation_preflight,
    normalize_application_number,
)


class CheckCurationPreflightTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.documents_path = Path(self.temporary_directory.name) / "documents.json"
        self.documents_path.write_text(
            json.dumps(
                [
                    {
                        "id": "doc:fda.opdivo",
                        "agent_id": "fda",
                        "identification_number": 125554,
                        "publication_date": "2025-04-11",
                    }
                ]
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @staticmethod
    def latest_record(_: str) -> dict:
        return {
            "application_number": "BLA125554",
            "submissions": [
                {
                    "submission_type": "ORIG",
                    "submission_status": "AP",
                    "submission_status_date": "20141222",
                    "application_docs": [],
                },
                {
                    "submission_type": "SUPPL",
                    "submission_status": "AP",
                    "submission_status_date": "20251010",
                    "application_docs": [
                        {
                            "type": "Label",
                            "url": "https://example.test/opdivo-2025-10.pdf",
                        }
                    ],
                },
            ],
        }

    def test_normalizes_application_number(self) -> None:
        self.assertEqual(
            normalize_application_number("bla 125554"), ("BLA125554", 125554)
        )

    def test_reports_curated_application_with_newer_label(self) -> None:
        result = check_curation_preflight(
            "BLA125554", self.documents_path, fetch_record=self.latest_record
        )
        self.assertEqual(
            result,
            {
                "application_number": "BLA125554",
                "previously_curated": True,
                "newer_label_available": True,
                "document_id": "doc:fda.opdivo",
                "curated_label_date": "2025-04-11",
                "latest_label_date": "2025-10-10",
                "latest_label_url": "https://example.test/opdivo-2025-10.pdf",
            },
        )

    def test_does_not_fetch_label_for_uncurated_application(self) -> None:
        def unexpected_fetch(_: str) -> dict:
            raise AssertionError("openFDA should not be queried for an uncurated drug")

        result = check_curation_preflight(
            "NDA999999", self.documents_path, fetch_record=unexpected_fetch
        )
        self.assertFalse(result["previously_curated"])
        self.assertIsNone(result["newer_label_available"])

    def test_rejects_number_without_application_type(self) -> None:
        with self.assertRaisesRegex(ValueError, "must include its type"):
            check_curation_preflight("125554", self.documents_path)


if __name__ == "__main__":
    unittest.main()
