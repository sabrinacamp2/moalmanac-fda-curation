from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from moalmanac_fda_curation import cli
from moalmanac_fda_curation.workflows import (
    assess_revisions,
    check_preflight,
    prepare_label_history,
    prepare_update_indications,
    propose_revisions,
    reconcile_indications,
)


class UpdateCliTest(unittest.TestCase):
    def test_cli_lists_update_commands(self) -> None:
        usage = cli.usage()
        self.assertIn("check-curation-preflight", usage)
        self.assertIn("reconcile-indications", usage)
        self.assertIn("prepare-label-history", usage)
        self.assertIn("prepare-update-indication-review", usage)
        self.assertIn("assess-revised-indications", usage)
        self.assertIn("propose-revised-indications", usage)

    def test_preflight_writes_an_artifact(self) -> None:
        result = {
            "application_number": "BLA125554",
            "previously_curated": True,
            "newer_label_available": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "preflight.json"
            argv = [
                "check-curation-preflight",
                "--application-number", "BLA125554",
                "--documents-json", str(root / "documents.json"),
                "--output-json", str(output),
            ]
            with patch("sys.argv", argv), patch.object(
                check_preflight, "check_curation_preflight", return_value=result
            ):
                self.assertEqual(check_preflight.main(), 0)
            self.assertEqual(json.loads(output.read_text()), result)

    def test_reconciliation_persists_new_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing_path = root / "existing.json"
            latest_path = root / "latest.json"
            output = root / "reconciliation.json"
            existing_path.write_text(json.dumps([
                {"id": "ind:1", "document_id": "doc:1", "indication": "Old"}
            ]))
            latest_path.write_text(json.dumps({"indications": [
                {"indication": "New", "raw_biomarkers": "ALK"}
            ]}))
            mapped = {
                "verified": True,
                "verification_errors": [],
                "mappings": [{
                    "classification": "new",
                    "latest_indication": {
                        "latest_indication_index": 0,
                        "indication": "New",
                        "raw_biomarkers": "ALK",
                    },
                    "reason": "No counterpart.",
                }],
            }
            argv = [
                "reconcile-indications",
                "--existing-indications-json", str(existing_path),
                "--document-id", "doc:1",
                "--latest-indications-json", str(latest_path),
                "--output-json", str(output),
            ]
            with patch("sys.argv", argv), patch.object(
                reconcile_indications,
                "map_existing_to_latest_indications",
                return_value=mapped,
            ):
                self.assertEqual(reconcile_indications.main(), 0)
            artifact = json.loads(output.read_text())
            self.assertEqual(
                artifact["new_indication_candidates"][0]["indication"], "New"
            )
            self.assertTrue(artifact["biomarker_only"])

    def test_revision_assessment_persists_diff_hunks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing_path = root / "existing.json"
            cache_path = root / "cache.json"
            output = root / "assessment.json"
            existing_path.write_text(json.dumps([
                {"id": "ind:1", "document_id": "doc:1", "indication": "Old"}
            ]))
            cache_path.write_text(json.dumps({
                "https://example.test/old.pdf": "Old text",
                "https://example.test/new.pdf": "New text",
            }))
            assessment = {
                "verified": True,
                "verification_errors": [],
                "assessments": [],
            }
            argv = [
                "assess-revised-indications",
                "--existing-indications-json", str(existing_path),
                "--document-id", "doc:1",
                "--section-cache-json", str(cache_path),
                "--baseline-label-url", "https://example.test/old.pdf",
                "--latest-label-url", "https://example.test/new.pdf",
                "--output-json", str(output),
            ]
            with patch("sys.argv", argv), patch.object(
                assess_revisions,
                "build_section_diff_hunks",
                return_value=[{"hunk_id": "hunk-1"}],
            ), patch.object(
                assess_revisions,
                "identify_revised_indications",
                return_value=assessment,
            ):
                self.assertEqual(assess_revisions.main(), 0)
            artifact = json.loads(output.read_text())
            self.assertEqual(artifact["diff_hunks"], [{"hunk_id": "hunk-1"}])
            self.assertEqual(artifact["document_id"], "doc:1")

    def test_prepare_label_history_prints_a_reusable_cache(self) -> None:
        document = {
            "id": "doc:fda.example",
            "drug_name_brand": "Example",
            "drug_name_generic": "examplemab",
            "identification_number": 123456,
            "urls": ["https://example.test/latest.pdf"],
        }
        with tempfile.TemporaryDirectory() as directory:
            work_dir = Path(directory).resolve()
            document_path = work_dir / "intermediate" / "document.proposal.json"
            document_path.parent.mkdir(parents=True)
            document_path.write_text(json.dumps(document))
            cache_path = (
                work_dir
                / "intermediate"
                / "section1-cache"
                / "Example-nda123456-section1-cache.json"
            )

            def build(**_: object) -> tuple[Path, Path]:
                cache_path.parent.mkdir(parents=True)
                cache_path.write_text("{}")
                changelog_dir = work_dir / "intermediate" / "section1-changelogs"
                changelog_dir.mkdir(parents=True)
                markdown = changelog_dir / "Example-nda123456-section1-changelog.md"
                payload = changelog_dir / "Example-nda123456-section1-changelog.json"
                markdown.write_text("history")
                payload.write_text("{}")
                return markdown, payload

            argv = ["prepare-label-history", "--work-dir", str(work_dir)]
            with patch("sys.argv", argv), patch.object(
                prepare_label_history,
                "resolve_document_application_number",
                return_value="NDA123456",
            ), patch.object(prepare_label_history, "build_changelog", side_effect=build):
                self.assertEqual(prepare_label_history.main(), 0)
            self.assertTrue(cache_path.is_file())

            with patch("sys.argv", argv), patch.object(
                prepare_label_history,
                "resolve_document_application_number",
                return_value="NDA123456",
            ), patch.object(prepare_label_history, "build_changelog") as build_again:
                self.assertEqual(prepare_label_history.main(), 0)
            build_again.assert_not_called()

    def test_exception_review_markdown_only_surfaces_unresolved_mappings(self) -> None:
        preflight = {
            "application_number": "BLA125554",
            "curated_label_date": "2025-04-11",
            "latest_label_date": "2026-08-12",
        }
        reconciliation = {
            "verified": True,
            "mappings": [
                {
                    "classification": "new",
                    "latest_indication": {"indication": "New FDA indication"},
                    "reason": "No existing counterpart.",
                },
                {
                    "classification": "not_found",
                    "existing_indication": {"indication": "Existing indication"},
                    "reason": "No latest counterpart.",
                },
            ],
        }
        markdown = prepare_update_indications.exception_review_markdown(
            preflight,
            reconciliation,
            reconciliation_path=Path("/tmp/reconciliation.json"),
            latest_indications_path=Path("/tmp/latest.json"),
        )
        self.assertIn("Existing indications not found: 1", markdown)
        self.assertIn("Existing indication", markdown)
        self.assertNotIn("New FDA indication", markdown)
        self.assertIn("not evidence that FDA removed", markdown)

    def test_combined_update_command_writes_review(self) -> None:
        document = {
            "id": "doc:fda.opdivo",
            "type": "Document",
            "drug_name_brand": "Opdivo",
            "drug_name_generic": "nivolumab",
            "identification_number": 125554,
            "publication_date": "2026-08-12",
            "urls": ["https://example.test/latest.pdf"],
        }
        preflight = {
            "application_number": "BLA125554",
            "previously_curated": True,
            "newer_label_available": True,
            "document_id": "doc:fda.opdivo",
            "curated_label_date": "2025-04-11",
            "latest_label_date": "2026-08-12",
            "latest_label_url": "https://example.test/latest.pdf",
        }
        reconciliation = {
            "verified": True,
            "verification_errors": [],
            "mappings": [{
                "classification": "new",
                "existing_indication_id": None,
                "latest_indication_index": 0,
                "reason": "No counterpart.",
                "existing_indication": None,
                "latest_indication": {
                    "latest_indication_index": 0,
                    "indication": "New indication",
                    "raw_biomarkers": "ALK",
                },
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            database = root / "moalmanac-db" / "referenced"
            database.mkdir(parents=True)
            (database / "documents.json").write_text("[]")
            (database / "indications.json").write_text(json.dumps([
                {
                    "id": "ind:1",
                    "document_id": "doc:fda.opdivo",
                    "indication": "Existing",
                }
            ]))
            work_dir = root / "run"

            def extract(command: list[str], check: bool) -> None:
                self.assertTrue(check)
                output = (
                    work_dir
                    / "intermediate"
                    / "Opdivo-BLA125554-claude_chunked_indication_fields.json"
                )
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps({"indications": [{
                    "indication": "New indication",
                    "raw_biomarkers": "ALK",
                }]}))

            argv = [
                "prepare-update-indication-review",
                "--application-number", "BLA125554",
                "--database-dir", str(root / "moalmanac-db"),
                "--work-dir", str(work_dir),
            ]
            with patch("sys.argv", argv), patch.object(
                prepare_update_indications,
                "check_curation_preflight",
                return_value=preflight,
            ), patch.object(
                prepare_update_indications, "curate_document", return_value=document
            ), patch.object(
                prepare_update_indications.subprocess, "run", side_effect=extract
            ), patch.object(
                prepare_update_indications,
                "map_existing_to_latest_indications",
                return_value=reconciliation,
            ):
                self.assertEqual(prepare_update_indications.main(), 0)

            review = work_dir / "review" / "reconciliation-exceptions.md"
            self.assertFalse(review.exists())
            reconciliation_path = (
                work_dir / "intermediate" / "indication-reconciliation.json"
            )
            self.assertTrue(reconciliation_path.is_file())

    def test_combined_update_command_writes_review_for_exceptions(self) -> None:
        preflight = {
            "application_number": "BLA125554",
            "curated_label_date": "2025-04-11",
            "latest_label_date": "2026-08-12",
        }
        reconciliation = {
            "verified": True,
            "mappings": [{
                "classification": "uncertain",
                "existing_indication": {"indication": "Existing indication"},
                "latest_indication": {"indication": "Possible counterpart"},
                "reason": "Possible split.",
            }],
        }
        markdown = prepare_update_indications.exception_review_markdown(
            preflight,
            reconciliation,
            reconciliation_path=Path("/tmp/reconciliation.json"),
            latest_indications_path=Path("/tmp/latest.json"),
        )
        self.assertIn("Existing indication", markdown)
        self.assertIn("Possible counterpart", markdown)
        self.assertIn("Possible split", markdown)

    def test_revision_proposals_only_process_revised_assessments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assessment_path = root / "assessment.json"
            output = root / "proposals.json"
            assessment_path.write_text(json.dumps({
                "verified": True,
                "document_id": "doc:1",
                "diff_hunks": [{"hunk_id": "hunk-1"}],
                "assessments": [
                    {
                        "status": "revised",
                        "existing_indication": {"id": "ind:1"},
                    },
                    {
                        "status": "not_revised",
                        "existing_indication": {"id": "ind:2"},
                    },
                ],
            }))
            argv = [
                "propose-revised-indications",
                "--assessment-json", str(assessment_path),
                "--output-json", str(output),
            ]
            proposal = {"existing_indication_id": "ind:1", "changes": {}}
            with patch("sys.argv", argv), patch.object(
                propose_revisions,
                "propose_revised_indication",
                return_value=proposal,
            ) as propose:
                self.assertEqual(propose_revisions.main(), 0)
            self.assertEqual(propose.call_count, 1)
            self.assertEqual(json.loads(output.read_text())["proposals"], [proposal])

    def test_commands_refuse_to_replace_artifacts_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "existing.json"
            output.write_text("{}")
            argv = [
                "reconcile-indications",
                "--existing-indications-json", str(root / "unused.json"),
                "--document-id", "doc:1",
                "--latest-indications-json", str(root / "unused-latest.json"),
                "--output-json", str(output),
            ]
            with patch("sys.argv", argv):
                with self.assertRaisesRegex(FileExistsError, "already exists"):
                    reconcile_indications.main()


if __name__ == "__main__":
    unittest.main()
