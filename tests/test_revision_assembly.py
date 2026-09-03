from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from moalmanac_fda_curation.review import revision_assembly
from moalmanac_fda_curation.review.revision_assembly import (
    assemble_document_updates,
    assemble_updated_indications,
)


class RevisionAssemblyTest(unittest.TestCase):
    def test_cli_writes_targeted_and_materialized_document_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / "run"
            intermediate = work / "intermediate"
            review = work / "review"
            database = root / "database" / "referenced"
            for path in (intermediate, review, database):
                path.mkdir(parents=True)
            existing_document = {
                "id": "doc:fda.example",
                "publication_date": "2024-01-01",
                "description": "Old citation",
                "urls": ["url:fda.example:label"],
            }
            latest_document = {
                "id": "doc:fda.example",
                "publication_date": "2026-01-02",
                "description": "New citation",
                "urls": ["https://example.test/latest.pdf"],
            }
            (database / "documents.json").write_text(json.dumps([existing_document]))
            (database / "urls.json").write_text(json.dumps([{
                "id": "url:fda.example:label",
                "url": "https://example.test/old.pdf",
            }]))
            (intermediate / "document.proposal.json").write_text(json.dumps(latest_document))
            (intermediate / "revision-targets.json").write_text(json.dumps({
                "document_id": "doc:fda.example",
                "targets": [],
            }))
            (intermediate / "Example-claude_chunked_indication_fields.json").write_text(
                json.dumps({"indications": []})
            )
            (intermediate / "selected-revision-description-proposals.json").write_text(
                json.dumps({"indications": []})
            )
            (intermediate / "selected-revision-date-evidence.json").write_text("[]")
            (review / "decisions.json").write_text(json.dumps({
                "schema_version": 1,
                "document": {},
                "indications": {},
            }))
            argv = [
                "assemble-revisions",
                "--work-dir", str(work),
                "--database-dir", str(root / "database"),
            ]
            with patch("sys.argv", argv):
                self.assertEqual(revision_assembly.main(), 0)
            reviewed = work / "reviewed"
            self.assertEqual(
                json.loads((reviewed / "document-update.json").read_text())["updates"]
                ["publication_date"],
                "2026-01-02",
            )
            self.assertEqual(
                json.loads((reviewed / "revised-url.json").read_text())["url"],
                "https://example.test/latest.pdf",
            )

    def test_document_update_changes_only_allow_list_and_label_url(self) -> None:
        existing = {
            "id": "doc:fda.example",
            "name": "Curated name",
            "company": "Curated Company.",
            "publication_date": "2024-01-01",
            "description": "Old citation",
            "urls": ["url:fda.example:label", "url:fda.example:overview"],
        }
        latest = {
            "id": "doc:fda.example",
            "name": "Generated different name",
            "company": "Generated Company",
            "publication_date": "2026-02-03",
            "description": "New citation",
            "urls": [
                "https://example.test/2026-label.pdf",
                "https://example.test/overview",
            ],
        }
        existing_url = {
            "id": "url:fda.example:label",
            "url": "https://example.test/2024-label.pdf",
        }
        document_patch, document, url_patch, url = assemble_document_updates(
            existing, latest, existing_url
        )
        self.assertEqual(document_patch["updates"], {
            "publication_date": "2026-02-03",
            "description": "New citation",
        })
        self.assertEqual(document["name"], "Curated name")
        self.assertEqual(document["company"], "Curated Company.")
        self.assertEqual(document["urls"], existing["urls"])
        self.assertEqual(url_patch["updates"]["url"], latest["urls"][0])
        self.assertEqual(url["id"], existing_url["id"])
        self.assertEqual(url["url"], latest["urls"][0])

    def setUp(self) -> None:
        self.existing = {
            "id": "ind:fda.example:7",
            "document_id": "doc:fda.example",
            "indication": "Old indication wording.",
            "description": "Old description.",
            "initial_approval_date": "2020-01-01",
            "initial_approval_url": "https://example.test/old.pdf",
            "raw_biomarkers": "HER2-positive",
            "raw_cancer_type": "breast cancer",
            "raw_therapeutics": "Example",
        }
        self.targets = {
            "targets": [{
                "existing_indication_id": self.existing["id"],
                "latest_indication_index": 1,
                "review_label": "HER2-positive breast cancer",
                "existing_indication": self.existing,
            }]
        }
        self.indications = {"indications": [
            {"indication": "Unused", "raw_biomarkers": None},
            {
                "indication": "New indication wording.",
                "raw_biomarkers": "HER2-positive",
                "raw_cancer_type": "metastatic breast cancer",
                "raw_therapeutics": "Example with chemotherapy",
            },
        ]}
        self.descriptions = {"indications": [{
            "indication_index": 1,
            "description": "New description.",
        }]}
        self.dates = [{
            "indication_index": 1,
            "verification": {
                "verified": True,
                "matched_event": {
                    "date": "2026-01-02",
                    "label_url": "https://example.test/new.pdf",
                },
            },
        }]
        self.decisions = {
            "schema_version": 1,
            "document": {},
            "indications": {"1": {
                "revision": {"decision": "use_latest", "overrides": {}},
                "description": {"decision": "accepted", "overrides": {}},
                "approval": {"decision": "accepted", "overrides": {}},
            }},
        }

    def test_assembly_preserves_id_and_uses_reviewed_current_form(self) -> None:
        result = assemble_updated_indications(
            self.targets,
            self.indications,
            self.descriptions,
            self.dates,
            self.decisions,
        )
        self.assertEqual(result[0]["id"], "ind:fda.example:7")
        self.assertEqual(result[0]["indication"], "New indication wording.")
        self.assertEqual(result[0]["initial_approval_date"], "2026-01-02")

    def test_revision_screening_overrides_update_latest_proposal(self) -> None:
        self.decisions["indications"]["1"]["revision"]["overrides"] = {
            "raw_cancer_type": "edited breast cancer"
        }
        result = assemble_updated_indications(
            self.targets,
            self.indications,
            self.descriptions,
            self.dates,
            self.decisions,
        )
        self.assertEqual(result[0]["raw_cancer_type"], "edited breast cancer")

    def test_incomplete_stage_decision_blocks_assembly(self) -> None:
        del self.decisions["indications"]["1"]["approval"]
        with self.assertRaisesRegex(ValueError, "label date and URL"):
            assemble_updated_indications(
                self.targets,
                self.indications,
                self.descriptions,
                self.dates,
                self.decisions,
            )

    def test_keep_existing_decision_is_omitted(self) -> None:
        self.decisions["indications"]["1"]["revision"] = {
            "decision": "keep_existing",
            "overrides": {},
        }
        self.assertEqual(
            assemble_updated_indications(
                self.targets,
                self.indications,
                self.descriptions,
                self.dates,
                self.decisions,
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
