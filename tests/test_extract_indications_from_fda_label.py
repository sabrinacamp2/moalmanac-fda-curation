from __future__ import annotations

import unittest

from moalmanac_fda_curation.core.extract_indications_from_fda_label import (
    extract_highlights_drug_class,
    extract_section,
)


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


if __name__ == "__main__":
    unittest.main()
