from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from moalmanac_fda_curation.assemble_reviewed import assemble_reviewed
from moalmanac_fda_curation.review_packet import (
    approval_markdown,
    build_stage_packet,
    candidates_markdown,
    document_markdown,
    description_markdown,
    indication_markdown,
)
from moalmanac_fda_curation.doctor import virtual_environment_status
from moalmanac_fda_curation.review_state import (
    decision_sources,
    empty_decisions,
    record_decision,
    verify_decision_sources,
)


class ReviewWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.document = {
            "id": "doc:fda.example",
            "type": "Document",
            "drug_name_brand": "Example",
            "drug_name_generic": "examplemab",
            "identification_number": 123456,
            "publication_date": "2026-01-02",
            "urls": ["https://example.test/current.pdf"],
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
                    "raw_cancer_type": "NSCLC",
                    "raw_therapeutics": "Example (examplemab)",
                },
                {
                    "indication": "Non-biomarker indication",
                    "review_label": "Other cancer",
                    "source_chunk_index": 0,
                    "highlights_drug_class_used": False,
                    "raw_biomarkers": None,
                    "raw_cancer_type": "other cancer",
                    "raw_therapeutics": "Example (examplemab)",
                },
            ],
        }
        self.descriptions = {
            "indications": [
                {
                    "indication_index": 0,
                    "description": "FDA granted approval to examplemab for RET-positive NSCLC.",
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
            "indication", self.document, self.indications, indication_index=0
        )
        self.assertEqual(packet["display_name"], "RET-positive NSCLC")
        self.assertTrue(packet["fda_highlights_source"]["used_by_pipeline"])
        markdown = indication_markdown(packet)
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
            self.document,
            self.indications,
            indication_index=0,
            descriptions=self.descriptions,
            decisions=decisions,
        )
        approval_packet = build_stage_packet(
            "approval",
            self.document,
            self.indications,
            indication_index=0,
            date_matches=self.dates,
            decisions=decisions,
        )
        self.assertIn("Curator-reviewed indication text.", description_markdown(description_packet))
        self.assertIn("Curator-reviewed indication text.", approval_markdown(approval_packet))

    def test_regenerated_review_shows_resolved_edit(self) -> None:
        decisions = empty_decisions()
        decisions["indications"]["0"] = {
            "indication": {
                "decision": "edited",
                "overrides": {"raw_cancer_type": "non-small cell lung cancer"},
            }
        }
        packet = build_stage_packet(
            "indication",
            self.document,
            self.indications,
            indication_index=0,
            decisions=decisions,
        )
        markdown = indication_markdown(packet)
        self.assertIn("Resolved curator edit", markdown)
        self.assertIn('"raw_cancer_type": "non-small cell lung cancer"', markdown)

    def test_candidate_markdown_is_a_short_biomarker_screen(self) -> None:
        packet = build_stage_packet("candidates", self.document, self.indications)
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

    def test_document_markdown_omits_fda_url_but_packet_retains_it(self) -> None:
        packet = build_stage_packet("document", self.document)
        markdown = document_markdown(packet)
        self.assertNotIn("https://example.test/current.pdf", markdown)
        self.assertEqual(
            packet["pipeline_document_proposal"]["urls"],
            ["https://example.test/current.pdf"],
        )

    def test_post_extraction_review_links_local_label_without_fda_url(self) -> None:
        artifacts = {
            "label PDF": "/tmp/Example.pdf",
            "label Markdown": "/tmp/Example.md",
        }
        packet = build_stage_packet(
            "indication",
            self.document,
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
            self.document,
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
                {"raw_cancer_type": "non-small cell lung cancer"},
                "Expanded NSCLC.",
                sources,
            )
            record_decision(decisions, "description", "accepted", 0, {}, None, sources)
            record_decision(decisions, "approval", "accepted", 0, {}, None, sources)
            reviewed_document, reviewed_indications = assemble_reviewed(
                self.document,
                self.indications,
                self.descriptions,
                self.dates,
                decisions,
            )
            self.assertEqual(reviewed_document["id"], "doc:fda.example")
            self.assertEqual(
                reviewed_indications[0]["raw_cancer_type"],
                "non-small cell lung cancer",
            )
            self.assertEqual(source.read_bytes(), original)

    def test_missing_explicit_decision_is_rejected(self) -> None:
        decisions = empty_decisions()
        decisions["document"] = {"decision": "accepted", "source_sha256": {}}
        with self.assertRaisesRegex(ValueError, "description"):
            decisions["indications"]["0"] = {
                "indication": {"decision": "accepted", "source_sha256": {}}
            }
            assemble_reviewed(
                self.document,
                self.indications,
                self.descriptions,
                self.dates,
                decisions,
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
