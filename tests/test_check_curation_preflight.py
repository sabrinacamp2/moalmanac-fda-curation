from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import db_fixture
from moalmanac_fda_curation.core.check_curation_preflight import (
    check_curation_preflight,
    normalize_application_number,
)


class CheckCurationPreflightTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        document = copy.deepcopy(db_fixture.DOCUMENT)
        document.update(
            {
                "id": "doc:fda:opdivo",
                "identification_number": 125554,
                "publication_date": "2025-04-11",
                "urls": ["url:fda:opdivo:label", "url:fda:opdivo:overview"],
            }
        )
        dated_document = copy.deepcopy(document)
        dated_document.update(
            {
                "id": "doc:fda:opdivo:2014-12-22",
                "urls": ["url:fda:opdivo:label:2014-12-22", "url:fda:opdivo:overview"],
                "publication_date": "2014-12-22",
                "status": "Deprecated",
            }
        )
        self.database_dir = db_fixture.write_database(
            Path(self.temporary_directory.name),
            documents=[document, dated_document],
            urls=[
                {
                    "id": "url:fda:opdivo:label",
                    "url": "https://example.test/opdivo-2025-04.pdf",
                },
                {
                    "id": "url:fda:opdivo:overview",
                    "url": "https://example.test/opdivo-overview",
                },
            ],
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
            "BLA125554",
            self.database_dir,
            fetch_record=self.latest_record,
        )
        self.assertEqual(
            result,
            {
                "application_number": "BLA125554",
                "previously_curated": True,
                "newer_label_available": True,
                "document_id": "doc:fda:opdivo",
                "curated_label_date": "2025-04-11",
                "curated_label_url": "https://example.test/opdivo-2025-04.pdf",
                "latest_label_date": "2025-10-10",
                "latest_label_url": "https://example.test/opdivo-2025-10.pdf",
            },
        )

    def test_does_not_fetch_label_for_uncurated_application(self) -> None:
        def unexpected_fetch(_: str) -> dict:
            raise AssertionError("openFDA should not be queried for an uncurated drug")

        result = check_curation_preflight(
            "NDA999999",
            self.database_dir,
            fetch_record=unexpected_fetch,
        )
        self.assertFalse(result["previously_curated"])
        self.assertIsNone(result["newer_label_available"])

    def test_rejects_number_without_application_type(self) -> None:
        with self.assertRaisesRegex(ValueError, "must include its type"):
            check_curation_preflight("125554", self.database_dir)

    def test_reports_missing_database_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(FileNotFoundError, "documents.json"):
                check_curation_preflight("BLA125554", Path(directory))


if __name__ == "__main__":
    unittest.main()
