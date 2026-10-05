from __future__ import annotations

import copy
import itertools
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db_fixture
from moalmanac_fda_curation.core.moalmanac_records import (
    ContributionLedger,
    existing_indication_view,
    next_indication_number,
)
from moalmanac_fda_curation.review import revision_assembly
from moalmanac_fda_curation.review.revision_assembly import (
    assemble_document_updates,
    assemble_new_indications,
    assemble_replacement_indications,
)

CURATOR_CONTRIBUTION = "ctrb:vanallenlab:2026-10-02:0"
LATEST_INDICATION = {
    "indication": "New indication wording.",
    "raw_biomarkers": "HER2-positive",
    "raw_cancer_types": "metastatic breast cancer",
    "raw_therapeutics": "Example (examplemab) with chemotherapy",
}
VERIFIED_DATE = {
    "verification": {
        "verified": True,
        "matched_event": {"date": "2026-01-02", "label_url": "https://example.test/latest.pdf"},
    },
}
ACCEPTED = {"decision": "accepted", "overrides": {}}


def write_work_dir(work: Path, **artifacts: object) -> None:
    """Write intermediate artifacts and decisions for an assemble-revisions run."""
    intermediate = work / "intermediate"
    review = work / "review"
    intermediate.mkdir(parents=True)
    review.mkdir()
    defaults = {
        "document.proposal.json": db_fixture.latest_proposal(),
        "revision-targets.json": {"document_id": "doc:fda:example", "targets": []},
        "Example-claude_chunked_indication_fields.json": {"indications": []},
        "indication-matches.json": {"new_indication_candidates": []},
    }
    decisions = artifacts.pop(
        "decisions", {"schema_version": 1, "document": {}, "indications": {}}
    )
    for name, payload in {**defaults, **artifacts}.items():
        (intermediate / name).write_text(json.dumps(payload))
    (review / "decisions.json").write_text(json.dumps(decisions))


class RevisionAssemblyCliTest(unittest.TestCase):
    def run_cli(self, root: Path) -> Path:
        argv = [
            "assemble-revisions",
            "--work-dir", str(root / "run"),
            "--database-dir", str(root / "database"),
            "--contribution-date", "2026-10-02",
        ]
        with patch("sys.argv", argv):
            self.assertEqual(revision_assembly.main(), 0)
        return root / "run" / "reviewed"

    @staticmethod
    def read(reviewed: Path, name: str) -> object:
        return json.loads((reviewed / name).read_text())

    def test_cli_writes_targeted_and_materialized_document_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db_fixture.write_database(root / "database")
            write_work_dir(root / "run")
            reviewed = self.run_cli(root)
            self.assertEqual(
                self.read(reviewed, "document-update.json")["updates"]["publication_date"],
                "2026-01-02",
            )
            self.assertEqual(
                self.read(reviewed, "revised-url.json"),
                {"id": "url:fda:example:label", "url": "https://example.test/latest.pdf"},
            )
            self.assertEqual(
                self.read(reviewed, "revised-document.json")["urls"],
                db_fixture.DOCUMENT["urls"],
            )
            for name in ("new-indications.json", "replacements.json", "contributions.json"):
                self.assertEqual(self.read(reviewed, name), [], name)

    def test_cli_assembles_new_indication_with_no_selected_revisions(self) -> None:
        """Regression test: assemble-revisions must not require revision-only
        artifacts (selected-revision-description-proposals.json etc.) when no
        existing indication was screened to use_latest, and must still assemble
        an accepted newly discovered indication using a fresh, non-colliding ID.
        """
        second = copy.deepcopy(db_fixture.INDICATION)
        second["id"] = "ind:fda:example:1"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db_fixture.write_database(
                root / "database", indications=[db_fixture.INDICATION, second]
            )
            write_work_dir(
                root / "run",
                **{
                    "Example-claude_chunked_indication_fields.json": {
                        "indications": [LATEST_INDICATION]
                    },
                    "indication-matches.json": {
                        "new_indication_candidates": [{
                            "latest_indication_index": 0,
                            "review_label": "HER2-positive metastatic breast cancer",
                        }],
                    },
                    "selected-description-proposals.json": {
                        "indications": [{
                            "indication_index": 0,
                            "statement_description": "New description.",
                        }],
                    },
                    "selected-approval-evidence.json": [
                        {"indication_index": 0, **VERIFIED_DATE}
                    ],
                    "decisions": {
                        "schema_version": 1,
                        "document": {},
                        "indications": {"0": {
                            stage: ACCEPTED for stage in ("indication", "description", "approval")
                        }},
                    },
                },
            )
            reviewed = self.run_cli(root)
            new_indications = self.read(reviewed, "new-indications.json")
            contributions = self.read(reviewed, "contributions.json")
        self.assertEqual(len(new_indications), 1)
        self.assertEqual(new_indications[0]["id"], "ind:fda:example:2")
        self.assertEqual(new_indications[0]["description"], "New indication wording.")
        self.assertEqual(new_indications[0]["reportedIn"], ["doc:fda:example"])
        self.assertEqual(
            new_indications[0]["contributions"],
            [CURATOR_CONTRIBUTION, "ctrb:fda:2026-01-02:0"],
        )
        self.assertEqual(
            contributions[0]["description"],
            "Initial curation of FDA's approval of Example (examplemab).",
        )

    def test_cli_suggests_only_a_replacement_for_a_changed_indication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db_fixture.write_database(root / "database")
            contributions = {item["id"]: item for item in db_fixture.CONTRIBUTIONS}
            write_work_dir(
                root / "run",
                **{
                    "revision-targets.json": {
                        "document_id": "doc:fda:example",
                        "targets": [{
                            "existing_indication_id": "ind:fda:example:0",
                            "latest_indication_index": 0,
                            "existing_indication": existing_indication_view(
                                db_fixture.INDICATION, contributions
                            ),
                        }],
                    },
                    "Example-claude_chunked_indication_fields.json": {
                        "indications": [LATEST_INDICATION]
                    },
                    "selected-revision-description-proposals.json": {
                        "indications": [{
                            "indication_index": 0,
                            "statement_description": "New description.",
                        }],
                    },
                    "selected-revision-date-evidence.json": [
                        {"indication_index": 0, **VERIFIED_DATE}
                    ],
                    "decisions": {
                        "schema_version": 1,
                        "document": {},
                        "indications": {"0": {
                            "revision": {"decision": "use_latest", "overrides": {}},
                            "description": ACCEPTED,
                            "approval": ACCEPTED,
                        }},
                    },
                },
            )
            reviewed = self.run_cli(root)
            new_indications = self.read(reviewed, "new-indications.json")
            replacements = self.read(reviewed, "replacements.json")
            new_contributions = self.read(reviewed, "contributions.json")
            written = sorted(path.name for path in reviewed.iterdir())
        self.assertEqual([record["id"] for record in new_indications], ["ind:fda:example:1"])
        self.assertEqual(new_indications[0]["description"], "New indication wording.")
        self.assertEqual(new_indications[0]["status"], "Approved")
        self.assertEqual(
            replacements,
            [{"indication_id": "ind:fda:example:1", "replaces": "ind:fda:example:0"}],
        )
        self.assertEqual(
            new_contributions[0]["description"],
            "Revised curation of FDA's approval of Example (examplemab) using the label "
            "published 2026-01-02.",
        )
        self.assertEqual(
            written,
            [
                "contributions.json",
                "document-update.json",
                "new-indications.json",
                "replacements.json",
                "revised-document.json",
                "revised-url.json",
                "url-update.json",
            ],
        )


class DocumentUpdateTest(unittest.TestCase):
    def test_document_update_changes_only_allow_list_and_label_url(self) -> None:
        existing = copy.deepcopy(db_fixture.DOCUMENT)
        existing["company"] = "Curated Company."
        latest = db_fixture.latest_proposal("https://example.test/2026-label.pdf")
        latest["document"]["company"] = "Generated Company"
        document_patch, document, url_patch, url = assemble_document_updates(
            existing, latest, db_fixture.URLS[0]
        )
        self.assertEqual(document_patch["updates"], {
            "publication_date": "2026-01-02",
            "description": latest["document"]["description"],
        })
        self.assertEqual(document["company"], "Curated Company.")
        self.assertEqual(document["urls"], existing["urls"])
        self.assertEqual(url_patch["updates"]["url"], "https://example.test/2026-label.pdf")
        self.assertEqual(url["id"], "url:fda:example:label")
        self.assertEqual(url["url"], "https://example.test/2026-label.pdf")

    def test_document_update_requires_the_same_application(self) -> None:
        latest = db_fixture.latest_proposal()
        latest["document"]["identification_number"] = 999999
        with self.assertRaisesRegex(ValueError, "different applications"):
            assemble_document_updates(db_fixture.DOCUMENT, latest, db_fixture.URLS[0])


class AssembleReplacementIndicationsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.database = db_fixture.tables()
        contributions = {item["id"]: item for item in self.database["contributions"]}
        self.targets = {
            "targets": [{
                "existing_indication_id": "ind:fda:example:0",
                "latest_indication_index": 1,
                "review_label": "HER2-positive breast cancer",
                "existing_indication": existing_indication_view(
                    db_fixture.INDICATION, contributions
                ),
            }]
        }
        self.indications = {"indications": [
            {"indication": "Unused", "raw_biomarkers": None},
            copy.deepcopy(LATEST_INDICATION),
        ]}
        self.descriptions = {"indications": [{
            "indication_index": 1,
            "statement_description": "New description.",
        }]}
        self.dates = [{"indication_index": 1, **copy.deepcopy(VERIFIED_DATE)}]
        self.decisions = {
            "schema_version": 1,
            "document": {},
            "indications": {"1": {
                "revision": {"decision": "use_latest", "overrides": {}},
                "description": copy.deepcopy(ACCEPTED),
                "approval": copy.deepcopy(ACCEPTED),
            }},
        }

    def assemble(self) -> list[dict]:
        """Return the new records, checking each replaces the targeted indication."""
        ledger = ContributionLedger(self.database["contributions"])
        pairs = assemble_replacement_indications(
            self.targets,
            self.indications,
            self.descriptions,
            self.dates,
            self.decisions,
            document_id="doc:fda:example",
            numbers=itertools.count(
                next_indication_number(self.database["indications"], "doc:fda:example")
            ),
            ledger=ledger,
            curator_contribution=lambda: ledger.reference(
                "agent:user:vanallenlab", "2026-10-02", "Revised."
            ),
        )
        self.assertTrue(all(replaced == "ind:fda:example:0" for replaced, _ in pairs))
        return [record for _, record in pairs]

    def test_replacement_is_a_new_record_for_the_changed_indication(self) -> None:
        replacements = self.assemble()
        self.assertEqual(replacements[0]["id"], "ind:fda:example:1")
        self.assertEqual(replacements[0]["description"], "New indication wording.")
        self.assertEqual(replacements[0]["statement_description"], "New description.")
        self.assertEqual(replacements[0]["reportedIn"], ["doc:fda:example"])
        self.assertEqual(replacements[0]["status"], "Approved")
        self.assertEqual(replacements[0]["superseded_by"], [])
        self.assertEqual(
            replacements[0]["contributions"], [CURATOR_CONTRIBUTION, "ctrb:fda:2026-01-02:0"]
        )

    def test_keeping_existing_approval_date_reuses_its_fda_contribution(self) -> None:
        self.decisions["indications"]["1"]["approval"] = {
            "decision": "edited",
            "overrides": {"initial_approval_date": "2020-01-01", "status": "Approved"},
        }
        replacements = self.assemble()
        self.assertEqual(
            replacements[0]["contributions"], [CURATOR_CONTRIBUTION, "ctrb:fda:2020-01-01:0"]
        )

    def test_accelerated_label_text_sets_replacement_status(self) -> None:
        self.indications["indications"][1]["indication"] += (
            " This indication is approved under accelerated approval."
        )
        self.assertEqual(self.assemble()[0]["status"], "Accelerated")

    def test_revision_screening_overrides_update_latest_proposal(self) -> None:
        self.decisions["indications"]["1"]["revision"]["overrides"] = {
            "raw_cancer_types": "edited breast cancer"
        }
        self.assertEqual(self.assemble()[0]["raw_cancer_types"], "edited breast cancer")

    def test_incomplete_stage_decision_blocks_assembly(self) -> None:
        del self.decisions["indications"]["1"]["approval"]
        with self.assertRaisesRegex(ValueError, "indication 1 approval"):
            self.assemble()

    def test_keep_existing_decision_suggests_nothing(self) -> None:
        self.decisions["indications"]["1"]["revision"] = {
            "decision": "keep_existing",
            "overrides": {},
        }
        self.assertEqual(self.assemble(), [])


class AssembleNewIndicationsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.new_candidates = [{
            "latest_indication_index": 3,
            "review_label": "New subtype",
        }]
        self.indications = {"indications": [
            None, None, None, copy.deepcopy(LATEST_INDICATION),
        ]}
        self.descriptions = {"indications": [{
            "indication_index": 3,
            "statement_description": "New description.",
        }]}
        self.dates = [{"indication_index": 3, **copy.deepcopy(VERIFIED_DATE)}]
        self.decisions = {
            "indications": {"3": {
                stage: copy.deepcopy(ACCEPTED)
                for stage in ("indication", "description", "approval")
            }},
        }
        # Existing indications for this document already occupy IDs 0-3, which
        # collide with the latest label's own positional index (3) for the new
        # candidate -- the assembler must not reuse that index verbatim.
        self.existing_indications = [
            {**db_fixture.INDICATION, "id": f"ind:fda:example:{i}"} for i in range(4)
        ]

    def assemble(self) -> list[dict]:
        ledger = ContributionLedger(db_fixture.CONTRIBUTIONS)
        return assemble_new_indications(
            self.new_candidates,
            self.indications,
            self.descriptions,
            self.dates,
            self.decisions,
            document_id="doc:fda:example",
            numbers=itertools.count(
                next_indication_number(self.existing_indications, "doc:fda:example")
            ),
            ledger=ledger,
            curator_contribution=lambda: ledger.reference(
                "agent:user:vanallenlab", "2026-10-02", "Initial."
            ),
        )

    def test_new_indication_gets_fresh_non_colliding_id(self) -> None:
        result = self.assemble()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "ind:fda:example:4")
        self.assertEqual(result[0]["description"], "New indication wording.")
        self.assertEqual(
            result[0]["contributions"], [CURATOR_CONTRIBUTION, "ctrb:fda:2026-01-02:0"]
        )

    def test_unresolved_new_candidate_is_omitted(self) -> None:
        self.decisions["indications"] = {}
        self.assertEqual(self.assemble(), [])

    def test_excluded_new_candidate_is_omitted(self) -> None:
        self.decisions["indications"]["3"]["indication"]["decision"] = "excluded"
        self.assertEqual(self.assemble(), [])

    def test_incomplete_decision_raises(self) -> None:
        del self.decisions["indications"]["3"]["approval"]
        with self.assertRaisesRegex(ValueError, "indication 3 approval"):
            self.assemble()


if __name__ == "__main__":
    unittest.main()
