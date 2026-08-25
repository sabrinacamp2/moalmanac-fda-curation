from __future__ import annotations

import unittest

from moalmanac_fda_curation.core.revise_indication import (
    assess_update,
    build_assessment_prompt,
    build_proposal_prompt,
    events_since,
    propose_revision,
)


class ReviseIndicationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.indication = {
            "id": "ind:fda.example:0",
            "document_id": "doc:fda.example",
            "indication": "EXAMPLE is indicated for adult patients with BRAF-positive cancer.",
            "initial_approval_date": "2020-01-01",
            "initial_approval_url": "https://example.test/initial.pdf",
            "description": "FDA approved example for adults with BRAF-positive cancer.",
            "raw_biomarkers": "BRAF-positive",
            "raw_cancer_type": "cancer",
            "raw_therapeutics": "Example",
        }
        self.events = [
            {
                "event_number": 2,
                "date": "2024-02-01",
                "change_type": "replace",
                "label_url": "https://example.test/2024.pdf",
                "before_text": "adult patients",
                "after_text": "adult and pediatric patients 12 years and older",
            }
        ]

    def test_events_since_is_strictly_after_cutoff(self) -> None:
        changelog = {"events": [
            {**self.events[0], "event_number": 1, "date": "2023-01-01"},
            self.events[0],
        ]}
        self.assertEqual(events_since(changelog, "2023-01-01"), self.events)

    def test_prompts_expose_readable_scope_sections(self) -> None:
        assessment_prompt = build_assessment_prompt(self.indication, self.events)
        proposal_prompt = build_proposal_prompt(
            self.indication,
            [{
                "event_number": 2,
                "target_before_quote": "adult patients",
                "target_after_quote": "adult and pediatric patients 12 years and older",
                "target_change": "Population expanded",
            }],
        )
        self.assertIn("# Target-span requirements", assessment_prompt)
        self.assertIn("Ignore newly added or otherwise separate indications", assessment_prompt)
        self.assertIn("before-text changes information", assessment_prompt)
        self.assertIn("shares a disease name", assessment_prompt)
        self.assertIn("# Status requirements", assessment_prompt)
        self.assertIn("mutually", assessment_prompt)
        self.assertNotIn("# Fields managed by Python", proposal_prompt)
        self.assertNotIn("Do not propose changes to", proposal_prompt)
        self.assertIn("Never merge a newly added or separate indication", proposal_prompt)
        self.assertIn("later span supersedes", proposal_prompt)

    def test_assessment_hydrates_real_event(self) -> None:
        result = assess_update(
            self.indication,
            self.events,
            llm=lambda _: {
                "status": "updated",
                "relevant_event_numbers": [2],
                "scoped_evidence": [{
                    "event_number": 2,
                    "target_before_quote": "adult patients",
                    "target_after_quote": "adult and pediatric patients 12 years and older",
                    "target_change": "Population expanded",
                }],
                "what_changed": ["Population expanded"],
                "reasoning": "The event changes this indication.",
                "uncertainties": [],
            },
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["relevant_events"], self.events)
        self.assertEqual(result["scoped_evidence"][0]["event_number"], 2)

    def test_unknown_assessment_event_fails_verification(self) -> None:
        result = assess_update(
            self.indication,
            self.events,
            llm=lambda _: {
                "status": "updated",
                "relevant_event_numbers": [99],
                "scoped_evidence": [{
                    "event_number": 99,
                    "target_before_quote": None,
                    "target_after_quote": "invented",
                    "target_change": "Unknown",
                }],
                "what_changed": [],
                "reasoning": "Unknown event.",
            },
        )
        self.assertFalse(result["verified"])
        self.assertEqual(result["relevant_events"], [])

    def test_updated_assessment_requires_a_described_change(self) -> None:
        result = assess_update(
            self.indication,
            self.events,
            llm=lambda _: {
                "status": "updated",
                "relevant_event_numbers": [2],
                "scoped_evidence": [{
                    "event_number": 2,
                    "target_before_quote": "adult patients",
                    "target_after_quote": "adult and pediatric patients 12 years and older",
                    "target_change": "Population expanded",
                }],
                "what_changed": [],
                "reasoning": "The target remained unchanged.",
            },
        )
        self.assertFalse(result["verified"])
        self.assertIn(
            "Updated assessment must describe what changed",
            result["verification_errors"],
        )

    def test_not_updated_assessment_cannot_return_revision_evidence(self) -> None:
        result = assess_update(
            self.indication,
            self.events,
            llm=lambda _: {
                "status": "not_updated",
                "relevant_event_numbers": [2],
                "scoped_evidence": [{
                    "event_number": 2,
                    "target_before_quote": "adult patients",
                    "target_after_quote": "adult and pediatric patients 12 years and older",
                    "target_change": "Population expanded",
                }],
                "what_changed": [],
                "reasoning": "No update.",
            },
        )
        self.assertFalse(result["verified"])
        self.assertIn(
            "Not-updated assessment must not cite relevant events",
            result["verification_errors"],
        )

    def test_formatting_only_target_evidence_fails_verification(self) -> None:
        events = [{
            **self.events[0],
            "before_text": "• adult\npatients",
            "after_text": " adult patients",
        }]
        result = assess_update(
            self.indication,
            events,
            llm=lambda _: {
                "status": "updated",
                "relevant_event_numbers": [2],
                "scoped_evidence": [{
                    "event_number": 2,
                    "target_before_quote": "• adult\npatients",
                    "target_after_quote": " adult patients",
                    "target_change": "Formatting changed",
                }],
                "what_changed": ["Formatting changed"],
                "reasoning": "Only formatting changed.",
            },
        )
        self.assertFalse(result["verified"])
        self.assertIn(
            "Event 2 target evidence is formatting-only",
            result["verification_errors"],
        )

    def test_proposal_preserves_non_updated_fields(self) -> None:
        assessment = {
            "verified": True,
            "assessment": {"status": "updated"},
            "scoped_evidence": [{
                "event_number": 2,
                "target_before_quote": "adult patients",
                "target_after_quote": "adult and pediatric patients 12 years and older",
                "target_change": "Population expanded",
            }],
            "relevant_events": self.events,
        }
        result = propose_revision(
            self.indication,
            assessment,
            llm=lambda _: {
                "updates": [{
                    "field": "indication",
                    "new_value": "EXAMPLE is indicated for adult and pediatric patients 12 years and older with BRAF-positive cancer.",
                    "reason": "Population expansion",
                    "supporting_event_numbers": [2],
                }],
                "summary": "Expand the population.",
            },
        )
        self.assertEqual(result["proposed_indication"]["id"], self.indication["id"])
        self.assertEqual(result["proposed_indication"]["initial_approval_date"], "2024-02-01")
        self.assertEqual(
            result["proposed_indication"]["initial_approval_url"],
            "https://example.test/2024.pdf",
        )
        self.assertEqual(
            {
                key: result["changes"][key]
                for key in ("initial_approval_date", "initial_approval_url")
            },
            {
                "initial_approval_date": "2024-02-01",
                "initial_approval_url": "https://example.test/2024.pdf",
            },
        )
        self.assertEqual(
            result["source_events"],
            [{
                "event_number": 2,
                "date": "2024-02-01",
                "label_url": "https://example.test/2024.pdf",
            }],
        )
        self.assertEqual(result["notes"]["summary"], "Expand the population.")
        self.assertEqual(
            set(result),
            {"proposed_indication", "changes", "source_events", "notes"},
        )

    def test_non_verbatim_scoped_evidence_fails_verification(self) -> None:
        result = assess_update(
            self.indication,
            self.events,
            llm=lambda _: {
                "status": "updated",
                "relevant_event_numbers": [2],
                "scoped_evidence": [{
                    "event_number": 2,
                    "target_before_quote": "adult patients",
                    "target_after_quote": "invented pediatric wording",
                    "target_change": "Population expanded",
                }],
                "what_changed": ["Population expanded"],
                "reasoning": "The event changes this indication.",
            },
        )
        self.assertFalse(result["verified"])
        self.assertEqual(result["scoped_evidence"], [])


if __name__ == "__main__":
    unittest.main()
