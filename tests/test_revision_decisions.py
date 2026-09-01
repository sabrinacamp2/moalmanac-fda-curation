from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from moalmanac_fda_curation.core.artifacts import file_sha256
from moalmanac_fda_curation.review.revision_decisions import (
    assemble_revised_indications,
    empty_decisions,
    record_revision_decision,
)


class RevisionDecisionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.assessment = {
            "assessments": [{
                "existing_indication_id": "ind:fda.example:0",
                "status": "revised",
                "existing_indication": {
                    "id": "ind:fda.example:0",
                    "document_id": "doc:fda.example",
                    "indication": "Old wording",
                    "description": "Old description",
                    "initial_approval_date": "2020-01-01",
                    "initial_approval_url": "https://example.test/old.pdf",
                },
            }]
        }
        self.proposals = {
            "proposals": [{
                "existing_indication_id": "ind:fda.example:0",
                "proposed_indication": {
                    "id": "ind:fda.example:0",
                    "document_id": "doc:fda.example",
                    "indication": "Proposed wording",
                    "description": "Proposed description",
                    "initial_approval_date": "2026-01-01",
                    "initial_approval_url": "https://example.test/new.pdf",
                },
            }]
        }

    def test_edited_decision_assembles_complete_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "recommendation.json"
            source.write_text("evidence")
            decisions = record_revision_decision(
                empty_decisions(),
                "ind:fda.example:0",
                "edited",
                {
                    "indication": "New wording",
                    "description": "New description",
                    "initial_approval_date": "2026-01-01",
                    "initial_approval_url": "https://example.test/new.pdf",
                },
                None,
                {str(source): file_sha256(source)},
            )
            result = assemble_revised_indications(
                self.assessment, self.proposals, decisions
            )
            self.assertEqual(result[0]["indication"], "New wording")
            self.assertEqual(result[0]["description"], "New description")
            self.assertEqual(result[0]["initial_approval_date"], "2026-01-01")
            self.assertEqual(result[0]["document_id"], "doc:fda.example")

    def test_accepted_decision_uses_proposed_record(self) -> None:
        decisions = record_revision_decision(
            empty_decisions(),
            "ind:fda.example:0",
            "accepted",
            {},
            None,
            {},
        )
        result = assemble_revised_indications(
            self.assessment, self.proposals, decisions
        )
        self.assertEqual(result[0]["indication"], "Proposed wording")
        self.assertEqual(result[0]["initial_approval_date"], "2026-01-01")

    def test_no_change_is_tracked_but_not_assembled(self) -> None:
        decisions = record_revision_decision(
            empty_decisions(),
            "ind:fda.example:0",
            "no-change",
            {},
            "No database field is affected.",
            {},
        )
        self.assertEqual(
            assemble_revised_indications(self.assessment, self.proposals, decisions), []
        )

    def test_unresolved_revision_blocks_assembly(self) -> None:
        decisions = record_revision_decision(
            empty_decisions(),
            "ind:fda.example:0",
            "unresolved",
            {},
            None,
            {},
        )
        with self.assertRaisesRegex(ValueError, "incomplete"):
            assemble_revised_indications(self.assessment, self.proposals, decisions)


if __name__ == "__main__":
    unittest.main()
