from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import db_fixture
from moalmanac_fda_curation.core.moalmanac_records import (
    ContributionLedger,
    DatedDocuments,
    approval_status,
    existing_indication_view,
    fda_document_id,
    fda_label_citation,
    indication_id,
    indication_number,
    initial_curation_description,
    is_dated_document,
    label_urls_by_document,
    load_existing_indications,
    next_indication_number,
    require_database,
    revised_curation_description,
    url_id,
)
from moalmanac_fda_curation.core.moalmanac_schemas import validate_records


class RecordIdentifierTest(unittest.TestCase):
    def test_ids_use_colon_delimited_hyphenated_slugs(self) -> None:
        document_id = fda_document_id("Avmapki Fakzynja")
        self.assertEqual(document_id, "doc:fda:avmapki-fakzynja")
        self.assertEqual(url_id(document_id, "label"), "url:fda:avmapki-fakzynja:label")
        self.assertEqual(indication_id(document_id, 2), "ind:fda:avmapki-fakzynja:2")

    def test_indication_number_ignores_other_documents(self) -> None:
        self.assertEqual(indication_number("ind:fda:example:3", "doc:fda:example"), 3)
        self.assertIsNone(indication_number("ind:fda:example-xr:3", "doc:fda:example"))
        self.assertIsNone(indication_number("ind:fda:example:a", "doc:fda:example"))

    def test_next_indication_number_follows_the_highest_existing_number(self) -> None:
        indications = [
            {"id": "ind:fda:example:0"},
            {"id": "ind:fda:example:3"},
            {"id": "ind:fda:other:9"},
        ]
        self.assertEqual(next_indication_number(indications, "doc:fda:example"), 4)
        self.assertEqual(next_indication_number([], "doc:fda:example"), 0)

    def test_dated_documents_are_recognized_by_their_id(self) -> None:
        self.assertTrue(is_dated_document("doc:fda:example:2020-01-01"))
        self.assertFalse(is_dated_document("doc:fda:example"))
        self.assertFalse(is_dated_document("doc:ema:example:2020-01-01"))


class CitationTest(unittest.TestCase):
    def test_citation_names_the_label_version_and_access_date(self) -> None:
        citation = fda_label_citation(
            company="Example Co",
            brand="Example",
            generic="examplemab",
            label_url="https://example.test/2020.pdf",
            label_date="2020-01-01",
            accessed_date="2026-10-06",
        )
        self.assertEqual(
            citation,
            "Example Co. Example (examplemab) [package insert]. U.S. Food and Drug "
            "Administration website. https://example.test/2020.pdf. Revised January 2020. "
            "Accessed October 6, 2026.",
        )
        self.assertTrue(
            fda_label_citation(
                company="Example Co.",
                brand="Example",
                generic="examplemab",
                label_url="https://example.test/2020.pdf",
                label_date="2020-01-01",
                accessed_date="2026-10-06",
            ).startswith("Example Co. Example")
        )


class DatedDocumentsTest(unittest.TestCase):
    def dated_documents(self, label_urls: dict[str, str]) -> DatedDocuments:
        return DatedDocuments(
            db_fixture.DOCUMENT,
            [db_fixture.DOCUMENT, db_fixture.DATED_DOCUMENT],
            label_urls,
            "2026-10-06",
        )

    def test_reuses_a_dated_document_already_in_the_database(self) -> None:
        documents = self.dated_documents({})
        self.assertEqual(documents.reference("2020-01-01"), "doc:fda:example:2020-01-01")
        self.assertEqual(documents.new_documents, [])
        self.assertEqual(documents.new_urls, [])

    def test_creates_a_deprecated_copy_of_the_evergreen_document(self) -> None:
        documents = self.dated_documents({"2026-01-02": "https://example.test/2026.pdf"})
        self.assertEqual(documents.reference("2026-01-02"), "doc:fda:example:2026-01-02")
        self.assertEqual(documents.reference("2026-01-02"), "doc:fda:example:2026-01-02")
        expected = copy.deepcopy(db_fixture.DOCUMENT)
        expected.update(
            {
                "id": "doc:fda:example:2026-01-02",
                "description": (
                    "Example Co. Example (examplemab) [package insert]. U.S. Food and Drug "
                    "Administration website. https://example.test/2026.pdf. Revised January "
                    "2026. Accessed October 6, 2026."
                ),
                "urls": ["url:fda:example:label:2026-01-02", "url:fda:example:overview"],
                "publication_date": "2026-01-02",
                "status": "Deprecated",
            }
        )
        self.assertEqual(documents.new_documents, [expected])
        self.assertEqual(list(documents.new_documents[0]), list(db_fixture.DOCUMENT))
        self.assertEqual(
            documents.new_urls,
            [{"id": "url:fda:example:label:2026-01-02", "url": "https://example.test/2026.pdf"}],
        )

    def test_requires_a_label_for_a_new_approval_date(self) -> None:
        with self.assertRaisesRegex(ValueError, "No FDA label from 2019-05-05"):
            self.dated_documents({}).reference("2019-05-05")


class CurationDescriptionTest(unittest.TestCase):
    def test_descriptions_name_the_workflow(self) -> None:
        self.assertEqual(
            initial_curation_description(db_fixture.DOCUMENT),
            "Initial curation of FDA's approval of Example (examplemab).",
        )
        self.assertEqual(
            revised_curation_description(db_fixture.DOCUMENT, "2026-01-02"),
            "Revised curation of FDA's approval of Example (examplemab) using the label "
            "published 2026-01-02.",
        )


class ApprovalStatusTest(unittest.TestCase):
    def test_accelerated_approval_language_sets_accelerated_status(self) -> None:
        self.assertEqual(
            approval_status(
                "EXAMPLE is indicated for KRAS G12C-mutated NSCLC. This indication is "
                "approved under accelerated approval based on response rate."
            ),
            "Accelerated",
        )
        self.assertEqual(approval_status("EXAMPLE is indicated for NSCLC."), "Approved")


class ExistingIndicationTest(unittest.TestCase):
    def test_view_maps_database_fields_and_approval_records(self) -> None:
        contributions = {item["id"]: item for item in db_fixture.CONTRIBUTIONS}
        label_urls = label_urls_by_document(
            [db_fixture.DOCUMENT, db_fixture.DATED_DOCUMENT], db_fixture.URLS
        )
        view = existing_indication_view(db_fixture.INDICATION, contributions, label_urls)
        self.assertEqual(view["indication"], db_fixture.INDICATION["description"])
        self.assertEqual(
            view["statement_description"], db_fixture.INDICATION["statement_description"]
        )
        self.assertEqual(view["raw_cancer_types"], "breast cancer")
        self.assertEqual(view["initial_approval_date"], "2020-01-01")
        self.assertEqual(view["initial_approval_document"], "doc:fda:example:2020-01-01")
        self.assertEqual(view["initial_approval_label_url"], "https://example.test/2020.pdf")
        self.assertEqual(view["status"], "Approved")

    def test_loads_only_current_indications_reported_in_the_document(self) -> None:
        withdrawn = copy.deepcopy(db_fixture.INDICATION)
        withdrawn.update({"id": "ind:fda:example:1", "status": "Withdrawn"})
        other = copy.deepcopy(db_fixture.INDICATION)
        other.update({"id": "ind:fda:other:0", "reportedIn": ["doc:fda:other"]})
        with tempfile.TemporaryDirectory() as directory:
            root = db_fixture.write_database(
                Path(directory),
                indications=[db_fixture.INDICATION, withdrawn, other],
            )
            existing = load_existing_indications(root, "doc:fda:example")
        self.assertEqual([item["id"] for item in existing], ["ind:fda:example:0"])

    def test_missing_database_inputs_are_reported_together(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(FileNotFoundError, "contributions.json") as raised:
                require_database(Path(directory))
        self.assertIn("schemas", str(raised.exception))


class ContributionLedgerTest(unittest.TestCase):
    def test_reuses_matching_contribution_and_allocates_next_number(self) -> None:
        ledger = ContributionLedger(db_fixture.CONTRIBUTIONS)
        self.assertEqual(
            ledger.reference(
                "agent:org:fda", "2020-01-01", "Indication received traditional approval."
            ),
            "ctrb:fda:2020-01-01:0",
        )
        self.assertEqual(
            ledger.reference(
                "agent:org:fda", "2020-01-01", "Indication received accelerated approval."
            ),
            "ctrb:fda:2020-01-01:1",
        )
        self.assertEqual(
            ledger.reference("agent:user:vanallenlab", "2026-10-02", "Curated."),
            "ctrb:vanallenlab:2026-10-02:0",
        )
        self.assertEqual(
            [record["id"] for record in ledger.new_records],
            ["ctrb:fda:2020-01-01:1", "ctrb:vanallenlab:2026-10-02:0"],
        )

    def test_orders_contributions_newest_first(self) -> None:
        ledger = ContributionLedger(db_fixture.CONTRIBUTIONS)
        new = ledger.reference("agent:user:vanallenlab", "2026-10-02", "Curated.")
        self.assertEqual(
            ledger.ordered(["ctrb:fda:2020-01-01:0", new, "ctrb:vanallenlab:2024-10-30:0"]),
            [new, "ctrb:vanallenlab:2024-10-30:0", "ctrb:fda:2020-01-01:0"],
        )


class SchemaValidationTest(unittest.TestCase):
    def test_reports_every_schema_violation(self) -> None:
        invalid = copy.deepcopy(db_fixture.INDICATION)
        invalid["raw_cancer_types"] = None
        invalid["initial_approval_url"] = "https://example.test/old.pdf"
        with tempfile.TemporaryDirectory() as directory:
            root = db_fixture.write_database(Path(directory))
            validate_records(root, {"indications": [db_fixture.INDICATION]})
            with self.assertRaisesRegex(ValueError, "raw_cancer_types") as raised:
                validate_records(root, {"indications": [invalid]})
        self.assertIn("initial_approval_url", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
