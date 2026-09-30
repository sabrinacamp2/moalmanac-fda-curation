from __future__ import annotations

import unittest

from moalmanac_fda_curation.core.curate_doc_from_drugsfda_endpoint import (
    get_drug_and_company_fields,
)


class GetDrugAndCompanyFieldsTest(unittest.TestCase):
    def test_reads_brand_and_generic_from_openfda(self) -> None:
        fda_record = {
            "application_number": "BLA125554",
            "sponsor_name": "BRISTOL-MYERS SQUIBB CO",
            "openfda": {
                "brand_name": ["OPDIVO"],
                "generic_name": ["NIVOLUMAB"],
            },
        }

        fields = get_drug_and_company_fields(fda_record)

        self.assertEqual(fields["brand"], "Opdivo")
        self.assertEqual(fields["generic"], "nivolumab")
        self.assertEqual(fields["company"], "Bristol-Myers Squibb Co")

    def test_missing_openfda_raises_clear_error(self) -> None:
        fda_record = {
            "application_number": "BLA761170",
            "sponsor_name": "GENENTECH INC",
            "products": [{"brand_name": "PHESGO"}],
        }

        with self.assertRaises(ValueError) as context:
            get_drug_and_company_fields(fda_record)

        self.assertIn("BLA761170", str(context.exception))
        self.assertIn("no supported fallback", str(context.exception))

    def test_openfda_missing_brand_name_raises_clear_error(self) -> None:
        fda_record = {
            "application_number": "BLA761170",
            "sponsor_name": "GENENTECH INC",
            "openfda": {"generic_name": ["SOME GENERIC"]},
        }

        with self.assertRaises(ValueError):
            get_drug_and_company_fields(fda_record)


if __name__ == "__main__":
    unittest.main()
