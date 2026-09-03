from __future__ import annotations

import unittest

from moalmanac_fda_curation.core.extract_indications_from_fda_label import (
    build_chunk_indication_prompt,
    extract_highlights_drug_class,
    extract_section,
)
from moalmanac_fda_curation.core.extract_indication_approval_dates import (
    extract_indications_section_fallback,
)


class IndicationPromptTest(unittest.TestCase):
    def test_repeats_shared_companion_diagnostic_for_applicable_indications(self) -> None:
        prompt = build_chunk_indication_prompt(
            {
                "source_chunk_text": (
                    "Drug is indicated for:\n"
                    "- population A\n"
                    "- population B\n"
                    "Select patients using a companion diagnostic."
                )
            },
            "Example",
            "examplemab",
            None,
        )
        self.assertIn(
            "repeat it in every applicable extracted indication",
            prompt,
        )
        self.assertIn("subsection or scope established by the source text", prompt)


class ExtractHighlightsDrugClassTest(unittest.TestCase):
    def test_extracts_contiguous_drug_class_phrase(self) -> None:
        highlights = """EXAMPLE is a kinase inhibitor indicated for the treatment of:
• adults with example-positive cancer.
"""

        self.assertEqual(
            extract_highlights_drug_class(highlights),
            "EXAMPLE is a kinase inhibitor",
        )

    def test_extracts_drug_class_when_two_columns_are_interleaved(self) -> None:
        highlights = """ adult patients with unresectable hepatocellular carcinoma
OPDIVO is a programmed death receptor-1 (PD-1)-blocking antibody
(HCC), as a first-line treatment in combination with ipilimumab. (1.12)
indicated for the treatment of:
 adult patients with unresectable melanoma.
"""

        self.assertEqual(
            extract_highlights_drug_class(highlights),
            "OPDIVO is a programmed death receptor-1 (PD-1)-blocking antibody",
        )


class ExtractSectionTest(unittest.TestCase):
    def test_matches_heading_without_trailing_period(self) -> None:
        text = "1 INDICATIONS AND USAGE\nEXAMPLE text.\n2 DOSAGE AND ADMINISTRATION\n"

        self.assertEqual(
            extract_section(text, "1 INDICATIONS AND USAGE", "2 DOSAGE AND ADMINISTRATION"),
            "EXAMPLE text.",
        )

    def test_matches_heading_with_trailing_period(self) -> None:
        text = "1. INDICATIONS AND USAGE\nEXAMPLE text.\n2. DOSAGE AND ADMINISTRATION\n"

        self.assertEqual(
            extract_section(text, "1 INDICATIONS AND USAGE", "2 DOSAGE AND ADMINISTRATION"),
            "EXAMPLE text.",
        )

    def test_extracts_legacy_label_without_full_prescribing_heading(self) -> None:
        text = (
            "130 CLINICAL STUDIES\n"
            "141 INDICATIONS AND USAGE\n"
            "142 Example is indicated for biomarker-positive cancer.\n"
            "143\n"
            "144 Additional indication detail.\n"
            "151 CONTRAINDICATIONS\n"
            "152 None known.\n"
        )

        self.assertEqual(
            extract_indications_section_fallback(text),
            "Example is indicated for biomarker-positive cancer.\n"
            "Additional indication detail.",
        )


if __name__ == "__main__":
    unittest.main()
