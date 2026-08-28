from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from moalmanac_fda_curation import cli
from moalmanac_fda_curation.workflows import (
    assess_revisions,
    check_preflight,
    find_revised_indications,
    prepare_label_history,
    prepare_revision_review,
    prepare_update_indications,
    propose_revisions,
    reconcile_indications,
)


class UpdateCliTest(unittest.TestCase):
    def test_cli_lists_update_commands(self) -> None:
        usage = cli.usage()
        self.assertIn("check-setup", usage)
        self.assertIn("check-curation-status", usage)
        self.assertIn("reconcile-indications", usage)
        self.assertIn("find-new-indications", usage)
        self.assertIn("find-revised-indications", usage)
        self.assertNotIn("check-curation-preflight", usage)
        self.assertNotIn("prepare-update-indication-review", usage)
        self.assertNotIn("prepare-label-history", usage)
        self.assertNotIn("prepare-revision-review", usage)
        self.assertNotIn("assess-revised-indications", usage)
        self.assertNotIn("propose-revised-indications", usage)
        self.assertNotIn("  doctor", usage)

    def test_curation_status_writes_an_artifact(self) -> None:
        result = {
            "application_number": "BLA125554",
            "previously_curated": True,
            "newer_label_available": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "curation-status.json"
            argv = [
                "check-curation-status",
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

    def test_match_review_markdown_only_surfaces_unresolved_mappings(self) -> None:
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
        markdown = prepare_update_indications.match_review_markdown(
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
            (database / "urls.json").write_text("[]")
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
                "find-new-indications",
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

            review = work_dir / "review" / "indication-match-review.md"
            self.assertFalse(review.exists())
            reconciliation_path = (
                work_dir / "intermediate" / "indication-reconciliation.json"
            )
            self.assertTrue(reconciliation_path.is_file())

    def test_combined_update_command_writes_review_for_unresolved_matches(self) -> None:
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
        markdown = prepare_update_indications.match_review_markdown(
            preflight,
            reconciliation,
            reconciliation_path=Path("/tmp/reconciliation.json"),
            latest_indications_path=Path("/tmp/latest.json"),
        )
        self.assertIn("Existing indication", markdown)
        self.assertIn("Possible counterpart", markdown)
        self.assertIn("Possible split", markdown)

    def test_new_indication_summary_separates_findings_from_curation_candidates(self) -> None:
        mappings = [
            {
                "latest_indication": {
                    "latest_indication_index": 1,
                    "review_label": "ALK-positive lung cancer",
                    "indication": "Drug for ALK-positive lung cancer",
                    "raw_biomarkers": "ALK",
                }
            },
            {
                "latest_indication": {
                    "latest_indication_index": 2,
                    "review_label": "Advanced RCC",
                    "indication": "Drug for advanced RCC",
                    "raw_biomarkers": None,
                }
            },
        ]
        candidates = [{"latest_indication_index": 1}]
        output = StringIO()
        with redirect_stdout(output):
            prepare_update_indications.print_new_indication_summary(
                mappings, candidates
            )
        summary = output.getvalue()
        self.assertIn(
            "New indication 1: ALK-positive lung cancer | Biomarker: ALK | curation candidate",
            summary,
        )
        self.assertIn(
            "New indication 2: Advanced RCC | Biomarker: none | outside biomarker scope",
            summary,
        )
        self.assertIn("New indications eligible for curation: 1", summary)
        self.assertIn("New indication indexes: 1", summary)

    def test_new_indication_review_shows_exact_text_biomarker_and_scope(self) -> None:
        mappings = [{
            "latest_indication": {
                "latest_indication_index": 2,
                "review_label": "Advanced RCC",
                "indication": "AFINITOR is indicated for advanced RCC.",
                "raw_biomarkers": None,
                "source_chunk_index": 4,
            },
            "reason": "No existing counterpart.",
        }]
        markdown = prepare_update_indications.new_indication_review_markdown(
            {
                "application_number": "NDA022334",
                "latest_label_date": "2026-06-01",
            },
            mappings,
            [],
            label_markdown_path=Path("/tmp/label.md"),
            label_pdf_path=Path("/tmp/label.pdf"),
            reconciliation_path=Path("/tmp/reconciliation.json"),
            latest_indications_path=Path("/tmp/indications.json"),
        )
        self.assertIn("## 2 — Advanced RCC", markdown)
        self.assertIn("- Biomarker: none", markdown)
        self.assertIn("- Scope: outside biomarker scope", markdown)
        self.assertIn("> AFINITOR is indicated for advanced RCC.", markdown)
        self.assertIn("[Latest FDA label Markdown](</tmp/label.md>)", markdown)

    def test_find_revised_indications_owns_history_and_revision_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            work_dir = root / "run"
            intermediate = work_dir / "intermediate"
            intermediate.mkdir(parents=True)
            status = {
                "previously_curated": True,
                "newer_label_available": True,
                "document_id": "doc:fda.example",
                "curated_label_url": "https://example.test/old.pdf",
                "latest_label_url": "https://example.test/new.pdf",
                "curated_label_date": "2025-04-11",
                "latest_label_date": "2026-08-12",
            }
            (intermediate / "curation-status.json").write_text(json.dumps(status))
            database = root / "moalmanac-db" / "referenced"
            database.mkdir(parents=True)
            indications = database / "indications.json"
            indications.write_text("[]")
            history = prepare_label_history.LabelHistoryPaths(
                intermediate / "history.json",
                intermediate / "cache.json",
            )
            argv = [
                "find-revised-indications",
                "--database-dir", str(root / "moalmanac-db"),
                "--work-dir", str(work_dir),
            ]
            with patch("sys.argv", argv), patch.object(
                find_revised_indications,
                "prepare_label_history",
                return_value=history,
            ) as prepare_history, patch.object(
                find_revised_indications,
                "run_revision_review",
                return_value=0,
            ) as review:
                self.assertEqual(find_revised_indications.main(), 0)
            prepare_history.assert_called_once_with(
                work_dir,
                overwrite=False,
                baseline_label_url="https://example.test/old.pdf",
            )
            review_args = review.call_args.args[0]
            self.assertEqual(review_args.existing_indications_json, indications)
            self.assertEqual(review_args.document_id, "doc:fda.example")
            self.assertEqual(review_args.section_cache_json, history.cache_json)
            self.assertEqual(review_args.changelog_json, history.changelog_json)
            self.assertEqual(review_args.baseline_label_date, "2025-04-11")
            self.assertEqual(review_args.latest_label_date, "2026-08-12")

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

    def test_revision_markdown_shows_exact_words_and_only_proposed_fields(self) -> None:
        existing = {
            "id": "ind:fda.opdivo:1",
            "indication": "Use an FDA-approved test.",
            "description": "Existing description.",
        }
        assessment = {
            "existing_indication_id": existing["id"],
            "status": "revised",
            "changes": ["Test designation changed."],
            "reason": "The cited hunk changes the test designation.",
            "existing_indication": existing,
            "relevant_hunks": [{
                "hunk_id": "hunk-1",
                "baseline_text": "Use an FDA-approved test.",
                "latest_text": "Use an FDA-authorized test.",
            }],
        }
        proposal = {
            "existing_indication_id": existing["id"],
            "changes": {"indication": "Use an FDA-authorized test."},
        }
        markdown = prepare_revision_review.revision_markdown(
            assessment,
            proposal,
            baseline_label_url="https://example.test/old.pdf",
            latest_label_url="https://example.test/new.pdf",
            baseline_label_date="2025-04-11",
            latest_label_date="2026-08-12",
            assessment_path=Path("/tmp/assessment.json"),
            proposals_path=Path("/tmp/proposals.json"),
        )
        self.assertIn("`FDA-approved` → `FDA-authorized`", markdown)
        self.assertIn("MOAlmanac update proposed: yes", markdown)
        self.assertIn("### `indication`", markdown)
        self.assertNotIn("### `description`", markdown)
        self.assertNotIn("Full proposed indication record", markdown)
        self.assertNotIn("```diff", markdown)

    def test_combined_revision_review_omits_unchanged_indications(self) -> None:
        revised = {
            "existing_indication_id": "ind:revised",
            "status": "revised",
            "relevant_hunk_ids": ["hunk-1"],
            "changes": ["Changed wording."],
            "reason": "Source changed.",
            "existing_indication": {
                "id": "ind:revised",
                "indication": "Old wording",
            },
            "relevant_hunks": [{
                "hunk_id": "hunk-1",
                "baseline_text": "Old wording",
                "latest_text": "New wording",
            }],
        }
        unchanged = {
            "existing_indication_id": "ind:unchanged",
            "status": "not_revised",
            "relevant_hunk_ids": [],
            "changes": [],
            "reason": "No relevant diff.",
            "existing_indication": {
                "id": "ind:unchanged",
                "indication": "Unchanged wording",
            },
            "relevant_hunks": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            intermediate = root / "intermediate"
            intermediate.mkdir()
            (intermediate / "revision-assessment.json").write_text(json.dumps({
                "verified": True,
                "document_id": "doc:1",
                "diff_hunks": revised["relevant_hunks"],
                "assessments": [revised, unchanged],
            }))
            argv = [
                "prepare-revision-review",
                "--existing-indications-json", str(root / "unused.json"),
                "--document-id", "doc:1",
                "--section-cache-json", str(root / "unused-cache.json"),
                "--changelog-json", str(root / "unused-changelog.json"),
                "--baseline-label-url", "https://example.test/old.pdf",
                "--latest-label-url", "https://example.test/new.pdf",
                "--baseline-label-date", "2025-04-11",
                "--latest-label-date", "2026-08-12",
                "--work-dir", str(root),
            ]
            proposal = {
                "existing_indication_id": "ind:revised",
                "changes": {"indication": "New wording"},
                "proposed_indication": {"id": "ind:revised", "indication": "New wording"},
            }
            date_matches = [{
                "indication_index": 0,
                "verification": {
                    "verified": True,
                    "matched_event": {
                        "date": "2026-08-12",
                        "label_url": "https://example.test/new.pdf",
                    },
                },
            }]
            with patch("sys.argv", argv), patch.object(
                prepare_revision_review,
                "propose_revised_indication",
                return_value=proposal,
            ) as propose, patch.object(
                prepare_revision_review,
                "load_changelog_payload",
                return_value={"events": []},
            ), patch.object(
                prepare_revision_review,
                "revision_date_matches",
                return_value=date_matches,
            ):
                self.assertEqual(prepare_revision_review.main(), 0)
            self.assertEqual(propose.call_count, 1)
            reviews = list((root / "review" / "revisions").glob("*.md"))
            self.assertEqual(len(reviews), 1)
            self.assertIn("ind:revised", reviews[0].read_text())
            self.assertNotIn("ind:unchanged", reviews[0].read_text())
            candidates = json.loads(
                (intermediate / "revision-indications.proposal.json").read_text()
            )
            self.assertEqual(
                candidates[0]["initial_approval_date"],
                "2026-08-12",
            )
            self.assertEqual(
                candidates[0]["initial_approval_url"],
                "https://example.test/new.pdf",
            )

    def test_bounded_changelog_filters_dates_and_renumbers_events(self) -> None:
        payload = {"events": [
            {"event_number": 4, "date": "2025-01-01"},
            {"event_number": 5, "date": "2025-04-11"},
            {"event_number": 8, "date": "2026-08-12"},
            {"event_number": 9, "date": "2026-09-01"},
        ]}
        bounded = prepare_revision_review.bounded_changelog(
            payload, "2025-04-11", "2026-08-12"
        )
        self.assertEqual(
            [item["event_number"] for item in bounded["events"]], [1, 2]
        )
        self.assertEqual(
            [item["original_event_number"] for item in bounded["events"]], [5, 8]
        )

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
