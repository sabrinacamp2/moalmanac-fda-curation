from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db_fixture
from moalmanac_fda_curation.review import assembly as assembly_module
from moalmanac_fda_curation.review.assembly import assemble_reviewed
from moalmanac_fda_curation.review import decisions as decision_module
from moalmanac_fda_curation.review.packets import (
    approval_markdown,
    build_stage_packet,
    candidates_markdown,
    document_markdown,
    description_markdown,
    indication_markdown,
    revision_markdown,
)
from moalmanac_fda_curation.doctor import virtual_environment_status
from moalmanac_fda_curation.review.decisions import (
    decision_sources,
    empty_decisions,
    existing_field_overrides,
    record_decision,
    verify_decision_sources,
)
from moalmanac_fda_curation.workflows import extract_candidates, prepare_document


class ReviewWorkflowTest(unittest.TestCase):
    def test_existing_revision_fields_are_retrieved_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work_dir = Path(directory)
            intermediate = work_dir / "intermediate"
            intermediate.mkdir()
            (intermediate / "revision-targets.json").write_text(json.dumps({
                "targets": [{
                    "latest_indication_index": 4,
                    "existing_indication": {
                        "initial_approval_date": "2020-06-29",
                        "status": "Accelerated",
                    },
                }]
            }))
            self.assertEqual(
                existing_field_overrides(
                    work_dir,
                    4,
                    ["initial_approval_date", "status"],
                ),
                {
                    "initial_approval_date": "2020-06-29",
                    "status": "Accelerated",
                },
            )

    def setUp(self) -> None:
        self.proposal = {
            "document": {
                "id": "doc:fda:example",
                "type": "Document",
                "documentType": "Regulatory approval",
                "name": "Example (examplemab) [package insert]. FDA.",
                "title": None,
                "aliases": [],
                "description": (
                    "Example Co. Example (examplemab) [package insert]. U.S. Food and "
                    "Drug Administration website. https://example.test/current.pdf. "
                    "Revised January 2026. Accessed February 1, 2026."
                ),
                "urls": ["url:fda:example:label", "url:fda:example:overview"],
                "doi": None,
                "pmid": None,
                "agent_id": "agent:org:fda",
                "company": "Example Co.",
                "drug_name_brand": "Example",
                "drug_name_generic": "examplemab",
                "first_publication_date": "2026-01-02",
                "identification_number": 123456,
                "publication_date": "2026-01-02",
                "status": "Active",
            },
            "urls": [
                {"id": "url:fda:example:label", "url": "https://example.test/current.pdf"},
                {"id": "url:fda:example:overview", "url": "https://example.test/overview"},
            ],
        }
        # The fixture database has not curated this application yet.
        self.database = db_fixture.tables(documents=[], indications=[], urls=[])
        self.label_urls = {
            "2020-01-01": "https://example.test/2020.pdf",
            "2026-01-02": "https://example.test/initial.pdf",
        }
        self.indications = {
            "source_chunks": [
                {
                    "source_chunk_index": 0,
                    "source_chunk_text": "Example source for RET-positive NSCLC.",
                }
            ],
            "provenance": {
                "highlights_drug_class_phrase": "EXAMPLE is a kinase inhibitor",
                "highlights_indications_and_usage_text": "Highlights source",
            },
            "indications": [
                {
                    "indication": "EXAMPLE is a kinase inhibitor indicated for RET-positive NSCLC.",
                    "review_label": "RET-positive NSCLC",
                    "source_chunk_index": 0,
                    "highlights_drug_class_used": True,
                    "raw_biomarkers": "RET-positive",
                    "raw_cancer_types": "NSCLC",
                    "raw_therapeutics": "Example (examplemab)",
                },
                {
                    "indication": "Non-biomarker indication",
                    "review_label": "Other cancer",
                    "source_chunk_index": 0,
                    "highlights_drug_class_used": False,
                    "raw_biomarkers": None,
                    "raw_cancer_types": "other cancer",
                    "raw_therapeutics": "Example (examplemab)",
                },
            ],
        }
        self.descriptions = {
            "indications": [
                {
                    "indication_index": 0,
                    "statement_description": "FDA granted approval to examplemab for RET-positive NSCLC.",
                    "clinical_detail_used": False,
                    "supporting_label_section_selections": [],
                }
            ]
        }
        self.dates = [
            {
                "indication_index": 0,
                "llm_match": {
                    "changelog_event_number": 1,
                    "why_this_event_is_full_match": "Initial event.",
                    "matched_before_quote": None,
                    "matched_after_quote": "Example source.",
                },
                "verification": {
                    "verified": True,
                    "matched_event": {
                        "date": "2026-01-02",
                        "label_url": "https://example.test/initial.pdf",
                    },
                },
            }
        ]

    def test_packet_contains_one_indication_and_highlights(self) -> None:
        packet = build_stage_packet(
            "indication", self.proposal, self.indications, indication_index=0
        )
        self.assertEqual(packet["display_name"], "RET-positive NSCLC")
        self.assertTrue(packet["fda_highlights_source"]["used_by_pipeline"])
        markdown = indication_markdown(packet)
        self.assertLess(markdown.index("Proposal to review"), markdown.index("Supporting evidence"))
        self.assertIn("FDA source — verbatim Indications and Usage", markdown)
        self.assertIn("verbatim Highlights phrase", markdown)
        self.assertNotIn("Non-biomarker indication", markdown)

    def test_description_and_approval_repeat_current_indication(self) -> None:
        decisions = empty_decisions()
        decisions["indications"]["0"] = {
            "indication": {
                "decision": "edited",
                "overrides": {"indication": "Curator-reviewed indication text."},
            }
        }
        description_packet = build_stage_packet(
            "description",
            self.proposal,
            self.indications,
            indication_index=0,
            descriptions=self.descriptions,
            decisions=decisions,
        )
        approval_packet = build_stage_packet(
            "approval",
            self.proposal,
            self.indications,
            indication_index=0,
            date_matches=self.dates,
            decisions=decisions,
        )
        self.assertIn("Curator-reviewed indication text.", description_markdown(description_packet))
        self.assertIn("Curator-edited indication", description_markdown(description_packet))
        self.assertIn("Curator-reviewed indication text.", approval_markdown(approval_packet))
        self.assertIn("Curator-edited indication", approval_markdown(approval_packet))
        self.assertLess(
            description_markdown(description_packet).index("Proposal to review"),
            description_markdown(description_packet).index("Supporting context"),
        )
        self.assertLess(
            approval_markdown(approval_packet).index("Proposal to review"),
            approval_markdown(approval_packet).index("Supporting context"),
        )

    def test_regenerated_review_shows_resolved_edit(self) -> None:
        decisions = empty_decisions()
        decisions["indications"]["0"] = {
            "indication": {
                "decision": "edited",
                "overrides": {"raw_cancer_types": "non-small cell lung cancer"},
            }
        }
        packet = build_stage_packet(
            "indication",
            self.proposal,
            self.indications,
            indication_index=0,
            decisions=decisions,
        )
        markdown = indication_markdown(packet)
        self.assertIn("Resolved curator edit", markdown)
        self.assertIn('"raw_cancer_types": "non-small cell lung cancer"', markdown)

    def test_revision_screening_decisions_use_explicit_outcomes(self) -> None:
        decisions = empty_decisions()
        record_decision(
            decisions,
            "revision",
            "use_latest",
            0,
            {},
            None,
            {},
        )
        self.assertEqual(
            decisions["indications"]["0"]["revision"]["decision"], "use_latest"
        )
        with self.assertRaisesRegex(ValueError, "Revision screening requires"):
            record_decision(
                empty_decisions(), "revision", "accepted", 0, {}, None, {}
            )

    def test_candidate_markdown_is_a_short_biomarker_screen(self) -> None:
        packet = build_stage_packet("candidates", self.proposal, self.indications)
        markdown = candidates_markdown(packet)
        self.assertIn("RET-positive NSCLC", markdown)
        self.assertIn(self.indications["indications"][0]["indication"], markdown)
        self.assertIn("Biomarker: RET-positive", markdown)
        self.assertNotIn("Pipeline index", markdown)
        self.assertNotIn("Cancer type:", markdown)
        self.assertNotIn("Therapeutics:", markdown)
        self.assertNotIn("FDA source — verbatim", markdown)
        self.assertEqual(packet["candidates"][0]["indication_index"], 0)
        self.assertIn("fda_indications_and_usage_excerpt", packet["candidates"][0])

    def test_document_markdown_omits_url_fields_but_packet_retains_them(self) -> None:
        packet = build_stage_packet("document", self.proposal)
        markdown = document_markdown(packet)
        self.assertNotIn('"urls"', markdown)
        self.assertNotIn("url:fda:example:label", markdown)
        self.assertNotIn("https://example.test/overview", markdown)
        self.assertEqual(
            packet["pipeline_url_records"][0]["url"],
            "https://example.test/current.pdf",
        )
        self.assertEqual(
            packet["curation_target"]["selected_label_url"],
            "https://example.test/current.pdf",
        )

    def test_post_extraction_review_links_local_label_without_fda_url(self) -> None:
        artifacts = {
            "label PDF": "/tmp/Example.pdf",
            "label Markdown": "/tmp/Example.md",
        }
        packet = build_stage_packet(
            "indication",
            self.proposal,
            self.indications,
            indication_index=0,
            artifact_paths=artifacts,
        )
        markdown = indication_markdown(packet)
        self.assertIn("[label PDF](</tmp/Example.pdf>)", markdown)
        self.assertIn("[label Markdown](</tmp/Example.md>)", markdown)
        self.assertNotIn("https://example.test/current.pdf", markdown)

    def test_approval_keeps_event_evidence_and_links_selected_event(self) -> None:
        before = "Prior exact changelog text."
        after = "New exact changelog text."
        self.dates[0]["llm_match"]["matched_before_quote"] = before
        self.dates[0]["llm_match"]["matched_after_quote"] = after
        packet = build_stage_packet(
            "approval",
            self.proposal,
            self.indications,
            indication_index=0,
            date_matches=self.dates,
            artifact_paths={
                "label PDF": "/tmp/Example.pdf",
                "label Markdown": "/tmp/Example.md",
                "selected changelog event": "/tmp/changelog.md#event-1",
            },
        )
        markdown = approval_markdown(packet)
        self.assertIn(before, markdown)
        self.assertIn(after, markdown)
        self.assertIn("[selected changelog event](</tmp/changelog.md#event-1>)", markdown)
        self.assertNotIn("Label URL:", markdown)
        self.assertIn(
            "Proposed approval status: Approved (the indication text does not state "
            "accelerated approval)",
            markdown,
        )
        self.assertEqual(
            packet["current_reviewed_approval"],
            {"initial_approval_date": "2026-01-02", "status": "Approved"},
        )

    def test_approval_status_follows_reviewed_indication_text(self) -> None:
        decisions = empty_decisions()
        decisions["indications"]["0"] = {
            "indication": {
                "decision": "edited",
                "overrides": {
                    "indication": (
                        "EXAMPLE is indicated for RET-positive NSCLC. This indication is "
                        "approved under accelerated approval based on response rate."
                    )
                },
            }
        }
        packet = build_stage_packet(
            "approval",
            self.proposal,
            self.indications,
            indication_index=0,
            date_matches=self.dates,
            decisions=decisions,
        )
        self.assertEqual(packet["current_reviewed_approval"]["status"], "Accelerated")
        self.assertIn(
            "Proposed approval status: Accelerated (the indication text states "
            "accelerated approval)",
            approval_markdown(packet),
        )

    def test_revision_date_review_explains_current_form_and_baseline(self) -> None:
        packet = build_stage_packet(
            "approval",
            self.proposal,
            self.indications,
            indication_index=0,
            date_matches=self.dates,
            revision_baseline_date="2025-04-11",
        )
        markdown = approval_markdown(packet)
        self.assertIn("approval date and status review", markdown)
        self.assertIn("Proposed date current revised form first appeared", markdown)
        self.assertIn("Previous curated label date: 2025-04-11", markdown)
        self.assertNotIn("initial approval review", markdown)

    def test_revision_reviews_include_stage_specific_existing_record(self) -> None:
        existing = {
            "id": "ind:fda:example:0",
            "indication": "Existing indication wording.",
            "statement_description": "Existing description wording.",
            "initial_approval_date": "2024-03-01",
            "status": "Approved",
            "contributions": [
                {
                    "id": "ctrb:fda:2024-03-01:0",
                    "type": "Contribution",
                    "agent_id": "agent:org:fda",
                    "description": "Indication received traditional approval.",
                    "date": "2024-03-01",
                }
            ],
            "raw_biomarkers": "RET fusion",
            "raw_cancer_types": "lung cancer",
            "raw_therapeutics": "Example",
        }
        revision_targets = {
            "targets": [{
                "latest_indication_index": 0,
                "existing_indication": existing,
                "reason": "The population wording changed.",
                "label_changes": [{
                    "hunk_id": "hunk-2",
                    "baseline_text": "Previous exact label wording.",
                    "latest_text": "Newer exact label wording.",
                }],
            }]
        }
        revision_packet = build_stage_packet(
            "revision",
            self.proposal,
            self.indications,
            indication_index=0,
            revision_targets=revision_targets,
            artifact_paths={
                "latest label PDF": "/tmp/latest.pdf",
                "previous curated label PDF": "/tmp/previous.pdf",
                "revision assessment": "/tmp/revision-assessment.json",
            },
        )
        indication_packet = build_stage_packet(
            "indication",
            self.proposal,
            self.indications,
            indication_index=0,
            revision_targets=revision_targets,
        )
        description_packet = build_stage_packet(
            "description",
            self.proposal,
            self.indications,
            indication_index=0,
            descriptions=self.descriptions,
            revision_targets=revision_targets,
        )
        approval_packet = build_stage_packet(
            "approval",
            self.proposal,
            self.indications,
            indication_index=0,
            date_matches=self.dates,
            revision_baseline_date="2024-03-01",
            revision_targets=revision_targets,
        )

        indication_review = indication_markdown(indication_packet)
        self.assertIn("Existing MOAlmanac indication", indication_review)
        self.assertIn("Existing indication wording.", indication_review)
        self.assertNotIn("Existing description wording.", indication_review)
        screening_review = revision_markdown(revision_packet)
        self.assertIn("Why this was flagged", screening_review)
        self.assertIn("The population wording changed.", screening_review)
        self.assertIn("Previous exact label wording.", screening_review)
        self.assertIn("Newer exact label wording.", screening_review)
        self.assertIn("`raw_biomarkers`: RET-positive", screening_review)
        self.assertIn("`raw_cancer_types`: NSCLC", screening_review)
        self.assertIn("`raw_therapeutics`: Example (examplemab)", screening_review)
        self.assertIn("`raw_biomarkers`: RET fusion", screening_review)
        self.assertIn("`raw_cancer_types`: lung cancer", screening_review)
        self.assertIn("`raw_therapeutics`: Example", screening_review)
        self.assertNotIn("Why this was flagged", indication_review)
        self.assertLess(
            screening_review.index("Why this was flagged"),
            screening_review.index("Latest-label indication"),
        )
        self.assertLess(
            screening_review.index("Latest-label indication"),
            screening_review.index("Existing MOAlmanac indication"),
        )
        self.assertLess(
            screening_review.index("Existing MOAlmanac indication"),
            screening_review.index("Label change 1"),
        )
        self.assertIn("[latest label PDF](</tmp/latest.pdf>)", screening_review)
        self.assertIn("[previous curated label PDF](</tmp/previous.pdf>)", screening_review)
        self.assertIn(
            "[revision assessment](</tmp/revision-assessment.json>)", screening_review
        )

        description_review = description_markdown(description_packet)
        self.assertIn("Existing MOAlmanac statement description", description_review)
        self.assertIn("Existing description wording.", description_review)

        approval_review = approval_markdown(approval_packet)
        self.assertIn("Existing MOAlmanac approval", approval_review)
        self.assertIn("- Initial approval date: 2024-03-01", approval_review)
        self.assertIn("- Status: Approved", approval_review)
        self.assertIn(
            "FDA contribution 2024-03-01: Indication received traditional approval.",
            approval_review,
        )
        self.assertIn("becomes a new record that replaces the existing one", approval_review)
        self.assertIn("or the existing approval date", approval_review)

    def test_virtual_environment_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            with patch("sys.prefix", "/active/venv"), patch("sys.base_prefix", "/base"):
                ok, detail = virtual_environment_status(project)
                self.assertTrue(ok)
                self.assertIn("active:", detail)

            with patch("sys.prefix", "/base"), patch("sys.base_prefix", "/base"):
                ok, detail = virtual_environment_status(project)
                self.assertFalse(ok)
                self.assertIn("absent:", detail)

                python = project / ".venv" / "bin" / "python"
                python.parent.mkdir(parents=True)
                python.touch()
                ok, detail = virtual_environment_status(project)
                self.assertFalse(ok)
                self.assertIn("existing but inactive:", detail)

    def test_document_wrapper_writes_proposal_and_builds_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            work_dir = Path(temp_dir) / "run"
            argv = [
                "prepare-document-review",
                "--application-number",
                "NDA123456",
                "--work-dir",
                str(work_dir),
            ]
            with patch("sys.argv", argv), patch.object(
                prepare_document, "curate_document", return_value=self.proposal
            ), patch.object(prepare_document.subprocess, "run") as run:
                self.assertEqual(prepare_document.main(), 0)

            proposal = work_dir / "intermediate" / "document.proposal.json"
            self.assertTrue(proposal.is_file())
            command = run.call_args.args[0]
            self.assertIn("moalmanac_fda_curation.review.packets", command)
            self.assertIn(str(proposal.resolve()), command)

    def test_review_inputs_derive_stage_artifacts_from_work_dir(self) -> None:
        from moalmanac_fda_curation.review.decisions import review_inputs

        with tempfile.TemporaryDirectory() as temp_dir:
            work_dir = Path(temp_dir)
            intermediate = work_dir / "intermediate"
            labels = work_dir / "labels"
            changelogs = intermediate / "section1-changelogs"
            for directory in (intermediate, labels, changelogs):
                directory.mkdir(parents=True, exist_ok=True)
            paths = [
                intermediate / "document.proposal.json",
                intermediate / "Example-NDA123-claude_chunked_indication_fields.json",
                intermediate / "selected-approval-evidence.json",
                labels / "Example-NDA123.pdf",
                labels / "Example-NDA123.md",
                changelogs / "Example-nda123-section1-changelog.md",
            ]
            for path in paths:
                path.touch()

            sources, arguments = review_inputs(work_dir, "approval")
            self.assertEqual(
                sources,
                [
                    intermediate / "Example-NDA123-claude_chunked_indication_fields.json",
                    intermediate / "selected-approval-evidence.json",
                ],
            )
            self.assertIn("--changelog-markdown", arguments)
            self.assertIn(str(labels / "Example-NDA123.pdf"), arguments)

    def test_revision_approval_decision_reuses_revision_date_evidence(self) -> None:
        from moalmanac_fda_curation.review.decisions import review_inputs

        with tempfile.TemporaryDirectory() as temp_dir:
            work_dir = Path(temp_dir)
            intermediate = work_dir / "intermediate"
            labels = work_dir / "labels"
            changelogs = intermediate / "section1-changelogs"
            for directory in (intermediate, labels, changelogs):
                directory.mkdir(parents=True, exist_ok=True)
            for path in (
                intermediate / "document.proposal.json",
                intermediate / "Example-NDA123-claude_chunked_indication_fields.json",
                intermediate / "selected-revision-date-evidence.json",
                labels / "Example-NDA123.pdf",
                labels / "Example-NDA123.md",
                changelogs / "Example-nda123-section1-changelog.md",
            ):
                path.touch()
            (intermediate / "revision-targets.json").write_text(json.dumps({
                "baseline_label_date": "2025-04-11",
                "targets": [{"latest_indication_index": 2}],
            }))

            sources, arguments = review_inputs(work_dir, "approval", 2)
            self.assertIn(
                intermediate / "selected-revision-date-evidence.json", sources
            )
            self.assertIn("--revision-baseline-date", arguments)
            self.assertIn("2025-04-11", arguments)

    def test_candidate_wrapper_runs_extraction_then_review_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            work_dir = Path(temp_dir).resolve()
            document = work_dir / "intermediate" / "document.proposal.json"
            document.parent.mkdir(parents=True)
            document.write_text(json.dumps(self.proposal), encoding="utf-8")
            argv = ["extract-indication-candidates", "--work-dir", str(work_dir)]
            with patch("sys.argv", argv), patch.object(
                extract_candidates.subprocess, "run"
            ) as run, patch.object(
                extract_candidates,
                "resolve_document_application_number",
                return_value="NDA123456",
            ):
                self.assertEqual(extract_candidates.main(), 0)

            self.assertEqual(run.call_count, 2)
            extraction_command = run.call_args_list[0].args[0]
            review_command = run.call_args_list[1].args[0]
            self.assertIn("moalmanac_fda_curation.core.extract_indications_from_fda_label", extraction_command)
            self.assertIn("moalmanac_fda_curation.review.packets", review_command)
            self.assertIn("--stage", review_command)
            self.assertIn("candidates", review_command)

    def test_record_decision_rebuilds_affected_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            work_dir = Path(temp_dir).resolve()
            document = work_dir / "intermediate" / "document.proposal.json"
            document.parent.mkdir(parents=True)
            document.write_text(json.dumps(self.proposal), encoding="utf-8")
            argv = [
                "record-decision",
                "--work-dir",
                str(work_dir),
                "--stage",
                "document",
                "--decision",
                "accepted",
            ]
            with patch("sys.argv", argv), patch.object(
                decision_module.subprocess, "run"
            ) as run:
                self.assertEqual(decision_module.main(), 0)

            decisions = json.loads(
                (work_dir / "review" / "decisions.json").read_text(encoding="utf-8")
            )
            self.assertEqual(decisions["document"]["decision"], "accepted")
            command = run.call_args.args[0]
            self.assertIn("moalmanac_fda_curation.review.packets", command)
            self.assertIn("--decisions-json", command)

    def test_generated_sources_remain_unchanged_and_reviewed_output_applies_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "indications.json"
            source.write_text(json.dumps(self.indications), encoding="utf-8")
            original = source.read_bytes()
            decisions = empty_decisions()
            sources = decision_sources([source])
            record_decision(decisions, "document", "accepted", None, {}, None, sources)
            record_decision(
                decisions,
                "indication",
                "edited",
                0,
                {"raw_cancer_types": "non-small cell lung cancer"},
                "Expanded NSCLC.",
                sources,
            )
            record_decision(decisions, "description", "accepted", 0, {}, None, sources)
            record_decision(decisions, "approval", "accepted", 0, {}, None, sources)
            assembled = assemble_reviewed(
                self.proposal,
                self.indications,
                self.descriptions,
                self.dates,
                decisions,
                self.database,
                label_urls=self.label_urls,
                contribution_date="2026-10-02",
            )
            self.assertEqual(assembled["document"]["id"], "doc:fda:example")
            self.assertEqual(
                assembled["indications"][0]["raw_cancer_types"],
                "non-small cell lung cancer",
            )
            self.assertEqual(source.read_bytes(), original)

    def accepted_decisions(self, *indexes: int) -> dict:
        decisions = empty_decisions()
        decisions["document"] = {"decision": "accepted", "source_sha256": {}}
        for index in indexes:
            decisions["indications"][str(index)] = {
                stage: {"decision": "accepted", "overrides": {}, "source_sha256": {}}
                for stage in ("indication", "description", "approval")
            }
        return decisions

    def test_first_time_assembly_builds_database_records(self) -> None:
        assembled = assemble_reviewed(
            self.proposal,
            self.indications,
            self.descriptions,
            self.dates,
            self.accepted_decisions(0),
            self.database,
            label_urls=self.label_urls,
            contribution_date="2026-10-02",
        )
        self.assertEqual(
            assembled["urls"],
            [
                *self.proposal["urls"],
                {"id": "url:fda:example:label:2026-01-02", "url": "https://example.test/initial.pdf"},
            ],
        )
        dated = assembled["dated_documents"]
        self.assertEqual([record["id"] for record in dated], ["doc:fda:example:2026-01-02"])
        self.assertEqual(dated[0]["status"], "Deprecated")
        self.assertEqual(dated[0]["publication_date"], "2026-01-02")
        self.assertEqual(
            dated[0]["urls"], ["url:fda:example:label:2026-01-02", "url:fda:example:overview"]
        )
        self.assertIn("https://example.test/initial.pdf. Revised January 2026.", dated[0]["description"])
        self.assertEqual(
            assembled["indications"],
            [{
                "id": "ind:fda:example:0",
                "type": "Indication",
                "description": self.indications["indications"][0]["indication"],
                "contributions": [
                    "ctrb:vanallenlab:2026-10-02:0",
                    "ctrb:fda:2026-01-02:0",
                ],
                "reportedIn": ["doc:fda:example", "doc:fda:example:2026-01-02"],
                "status": "Approved",
                "statement_description": self.descriptions["indications"][0][
                    "statement_description"
                ],
                "raw_biomarkers": "RET-positive",
                "raw_cancer_types": "NSCLC",
                "raw_therapeutics": "Example (examplemab)",
                "superseded_by": [],
            }],
        )
        self.assertEqual(
            assembled["contributions"],
            [
                {
                    "id": "ctrb:vanallenlab:2026-10-02:0",
                    "type": "Contribution",
                    "agent_id": "agent:user:vanallenlab",
                    "description": "Initial curation of FDA's approval of Example (examplemab).",
                    "date": "2026-10-02",
                },
                {
                    "id": "ctrb:fda:2026-01-02:0",
                    "type": "Contribution",
                    "agent_id": "agent:org:fda",
                    "description": "Indication received traditional approval.",
                    "date": "2026-01-02",
                },
            ],
        )

    def test_matching_database_approval_contribution_is_reused(self) -> None:
        self.dates[0]["verification"]["matched_event"]["date"] = "2020-01-01"
        assembled = assemble_reviewed(
            self.proposal,
            self.indications,
            self.descriptions,
            self.dates,
            self.accepted_decisions(0),
            self.database,
            label_urls=self.label_urls,
            contribution_date="2026-10-02",
        )
        self.assertIn("ctrb:fda:2020-01-01:0", assembled["indications"][0]["contributions"])
        self.assertEqual(
            [record["agent_id"] for record in assembled["contributions"]],
            ["agent:user:vanallenlab"],
        )

    def test_retained_indications_are_numbered_contiguously(self) -> None:
        self.indications["indications"].append(
            {**self.indications["indications"][0], "review_label": "Second RET use"}
        )
        self.descriptions["indications"].append(
            {**self.descriptions["indications"][0], "indication_index": 2}
        )
        self.dates.append({**self.dates[0], "indication_index": 2})
        decisions = self.accepted_decisions(2)
        decisions["indications"]["0"] = {
            "indication": {"decision": "excluded", "overrides": {}, "source_sha256": {}}
        }
        assembled = assemble_reviewed(
            self.proposal,
            self.indications,
            self.descriptions,
            self.dates,
            decisions,
            self.database,
            label_urls=self.label_urls,
            contribution_date="2026-10-02",
        )
        self.assertEqual(
            [record["id"] for record in assembled["indications"]], ["ind:fda:example:0"]
        )

    def test_curator_approval_status_edit_sets_status_and_contribution(self) -> None:
        decisions = self.accepted_decisions(0)
        decisions["indications"]["0"]["approval"] = {
            "decision": "edited",
            "overrides": {"status": "Accelerated"},
            "source_sha256": {},
        }
        assembled = assemble_reviewed(
            self.proposal,
            self.indications,
            self.descriptions,
            self.dates,
            decisions,
            self.database,
            label_urls=self.label_urls,
            contribution_date="2026-10-02",
        )
        self.assertEqual(assembled["indications"][0]["status"], "Accelerated")
        self.assertEqual(
            assembled["contributions"][-1]["description"],
            "Indication received accelerated approval.",
        )

    def test_existing_document_id_is_rejected(self) -> None:
        database = db_fixture.tables(
            documents=[self.proposal["document"]], indications=[], urls=[]
        )
        with self.assertRaisesRegex(ValueError, "already contains IDs"):
            assemble_reviewed(
                self.proposal,
                self.indications,
                self.descriptions,
                self.dates,
                self.accepted_decisions(0),
                database,
                label_urls=self.label_urls,
                contribution_date="2026-10-02",
            )

    def test_assemble_reviewed_cli_writes_schema_valid_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            database = db_fixture.write_database(
                root / "moalmanac-db", documents=[], indications=[], urls=[]
            )
            work_dir = root / "run"
            intermediate = work_dir / "intermediate"
            review = work_dir / "review"
            intermediate.mkdir(parents=True)
            review.mkdir()
            for name, payload in (
                ("document.proposal.json", self.proposal),
                ("Example-NDA123456-claude_chunked_indication_fields.json", self.indications),
                ("selected-description-proposals.json", self.descriptions),
                ("selected-approval-evidence.json", self.dates),
            ):
                (intermediate / name).write_text(json.dumps(payload), encoding="utf-8")
            db_fixture.write_changelog(intermediate, self.label_urls)
            (review / "decisions.json").write_text(
                json.dumps(self.accepted_decisions(0)), encoding="utf-8"
            )
            argv = [
                "assemble-reviewed",
                "--work-dir", str(work_dir),
                "--database-dir", str(database),
                "--contribution-date", "2026-10-02",
            ]
            with patch("sys.argv", argv):
                self.assertEqual(assembly_module.main(), 0)
            reviewed = work_dir / "reviewed"
            self.assertEqual(
                json.loads((reviewed / "document.json").read_text())["id"],
                "doc:fda:example",
            )
            self.assertEqual(
                [
                    record["id"]
                    for record in json.loads((reviewed / "dated-documents.json").read_text())
                ],
                ["doc:fda:example:2026-01-02"],
            )
            self.assertEqual(len(json.loads((reviewed / "urls.json").read_text())), 3)
            self.assertEqual(len(json.loads((reviewed / "indication.json").read_text())), 1)
            self.assertEqual(
                len(json.loads((reviewed / "contributions.json").read_text())), 2
            )

    def test_approval_date_needs_a_known_label(self) -> None:
        decisions = self.accepted_decisions(0)
        decisions["indications"]["0"]["approval"] = {
            "decision": "edited",
            "overrides": {"initial_approval_date": "2019-05-05"},
            "source_sha256": {},
        }
        with self.assertRaisesRegex(ValueError, "No FDA label from 2019-05-05"):
            assemble_reviewed(
                self.proposal,
                self.indications,
                self.descriptions,
                self.dates,
                decisions,
                self.database,
                label_urls=self.label_urls,
                contribution_date="2026-10-02",
            )

    def test_assemble_reviewed_cli_rejects_schema_violations(self) -> None:
        self.indications["indications"][0]["raw_cancer_types"] = None
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            database = db_fixture.write_database(
                root / "moalmanac-db", documents=[], indications=[], urls=[]
            )
            work_dir = root / "run"
            intermediate = work_dir / "intermediate"
            (work_dir / "review").mkdir(parents=True)
            intermediate.mkdir()
            for name, payload in (
                ("document.proposal.json", self.proposal),
                ("Example-NDA123456-claude_chunked_indication_fields.json", self.indications),
                ("selected-description-proposals.json", self.descriptions),
                ("selected-approval-evidence.json", self.dates),
            ):
                (intermediate / name).write_text(json.dumps(payload), encoding="utf-8")
            db_fixture.write_changelog(intermediate, self.label_urls)
            (work_dir / "review" / "decisions.json").write_text(
                json.dumps(self.accepted_decisions(0)), encoding="utf-8"
            )
            argv = [
                "assemble-reviewed",
                "--work-dir", str(work_dir),
                "--database-dir", str(database),
            ]
            with patch("sys.argv", argv), self.assertRaisesRegex(
                ValueError, "raw_cancer_types"
            ):
                assembly_module.main()
            self.assertFalse((work_dir / "reviewed").exists())

    def test_approval_overrides_are_validated(self) -> None:
        with self.assertRaisesRegex(ValueError, "Approval status"):
            record_decision(
                empty_decisions(), "approval", "edited", 0, {"status": "Full"}, None, {}
            )
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            record_decision(
                empty_decisions(),
                "approval",
                "edited",
                0,
                {"initial_approval_date": "March 2024"},
                None,
                {},
            )

    def test_missing_explicit_decision_is_rejected(self) -> None:
        decisions = empty_decisions()
        decisions["document"] = {"decision": "accepted", "source_sha256": {}}
        with self.assertRaisesRegex(ValueError, "description"):
            decisions["indications"]["0"] = {
                "indication": {"decision": "accepted", "source_sha256": {}}
            }
            assemble_reviewed(
                self.proposal,
                self.indications,
                self.descriptions,
                self.dates,
                decisions,
                self.database,
                label_urls=self.label_urls,
                contribution_date="2026-10-02",
            )

    def test_meaningful_indication_edit_clears_downstream_decisions(self) -> None:
        decisions = empty_decisions()
        decisions["indications"]["0"] = {
            "description": {"decision": "accepted"},
            "approval": {"decision": "accepted"},
        }
        record_decision(
            decisions,
            "indication",
            "edited",
            0,
            {"indication": "Changed clinical meaning"},
            None,
            {},
        )
        self.assertNotIn("description", decisions["indications"]["0"])
        self.assertNotIn("approval", decisions["indications"]["0"])

    def test_unknown_override_field_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported indication override"):
            record_decision(
                empty_decisions(),
                "indication",
                "edited",
                0,
                {"made_up_field": "value"},
                None,
                {},
            )

    def test_changed_source_makes_decision_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "proposal.json"
            source.write_text("{}", encoding="utf-8")
            decisions = empty_decisions()
            record_decision(
                decisions,
                "document",
                "accepted",
                None,
                {},
                None,
                decision_sources([source]),
            )
            source.write_text('{"changed": true}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source changed"):
                verify_decision_sources(decisions)


if __name__ == "__main__":
    unittest.main()
