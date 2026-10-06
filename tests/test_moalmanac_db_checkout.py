"""Validate assembled records against a real moalmanac-db checkout.

Set MOALMANAC_DB_ROOT to a local moalmanac-db repository to run these tests. They
catch schema changes in moalmanac-db that the trimmed test fixture cannot.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from moalmanac_fda_curation.core.moalmanac_records import load_database
from moalmanac_fda_curation.core.moalmanac_schemas import validate_records
from moalmanac_fda_curation.review.assembly import assemble_reviewed

DATABASE = os.environ.get("MOALMANAC_DB_ROOT")


@unittest.skipUnless(DATABASE, "set MOALMANAC_DB_ROOT to a moalmanac-db checkout")
class MoalmanacDbCheckoutTest(unittest.TestCase):
    def test_first_time_assembly_matches_checkout_schemas(self) -> None:
        database_dir = Path(DATABASE).resolve()
        document_id = "doc:fda:schema-check"
        proposal = {
            "document": {
                "id": document_id,
                "type": "Document",
                "documentType": "Regulatory approval",
                "name": "Schema Check (checkamab) [package insert]. FDA.",
                "title": None,
                "aliases": [],
                "description": (
                    "Example Co. Schema Check (checkamab) [package insert]. U.S. Food and "
                    "Drug Administration website. https://example.test/label.pdf. "
                    "Revised January 2026. Accessed February 1, 2026."
                ),
                "urls": ["url:fda:schema-check:label", "url:fda:schema-check:overview"],
                "doi": None,
                "pmid": None,
                "agent_id": "agent:org:fda",
                "company": "Example Co.",
                "drug_name_brand": "Schema Check",
                "drug_name_generic": "checkamab",
                "first_publication_date": "2026-01-02",
                "identification_number": 999999,
                "publication_date": "2026-01-02",
                "status": "Active",
            },
            "urls": [
                {"id": "url:fda:schema-check:label", "url": "https://example.test/label.pdf"},
                {"id": "url:fda:schema-check:overview", "url": "https://example.test/overview"},
            ],
        }
        accepted = {"decision": "accepted", "overrides": {}, "source_sha256": {}}
        assembled = assemble_reviewed(
            proposal,
            {"indications": [{
                "indication": (
                    "SCHEMA CHECK is indicated for KRAS G12C-mutated NSCLC. This indication "
                    "is approved under accelerated approval based on response rate."
                ),
                "raw_biomarkers": "KRAS G12C",
                "raw_cancer_types": "non-small cell lung cancer",
                "raw_therapeutics": "Schema Check (checkamab)",
            }]},
            {"indications": [{
                "indication_index": 0,
                "statement_description": (
                    "The U.S. Food and Drug Administration granted accelerated approval to "
                    "checkamab for patients with KRAS G12C-mutated NSCLC."
                ),
            }]},
            [{
                "indication_index": 0,
                "verification": {
                    "verified": True,
                    "matched_event": {"date": "2026-01-02", "label_url": "https://example.test/label.pdf"},
                },
            }],
            {
                "schema_version": 1,
                "document": accepted,
                "indications": {
                    "0": {stage: accepted for stage in ("indication", "description", "approval")}
                },
            },
            load_database(database_dir),
            label_urls={"2026-01-02": "https://example.test/label.pdf"},
            contribution_date="2026-10-02",
        )
        self.assertEqual(assembled["indications"][0]["status"], "Accelerated")
        self.assertEqual(
            assembled["indications"][0]["reportedIn"],
            ["doc:fda:schema-check", "doc:fda:schema-check:2026-01-02"],
        )
        validate_records(
            database_dir,
            {
                "documents": [assembled["document"], *assembled["dated_documents"]],
                "urls": assembled["urls"],
                "indications": assembled["indications"],
                "contributions": assembled["contributions"],
            },
        )


if __name__ == "__main__":
    unittest.main()
