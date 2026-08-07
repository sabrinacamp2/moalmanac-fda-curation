"""Small, offline fixture used to explore the curator experience."""

from __future__ import annotations

from copy import deepcopy


LYNPARZA_FIXTURE = {
    "curation_id": "lynparza-nda208558",
    "title": "Lynparza · NDA 208558",
    "source": {
        "application_number": "NDA208558",
        "label_date": "2023-11-06",
        "label_url": "http://www.accessdata.fda.gov/drugsatfda_docs/label/2023/208558s028lbl.pdf",
        "note": "Pinned FDA label used by the existing comparison workflow.",
    },
    "document": {
        "id": "doc:fda.lynparza",
        "type": "Document",
        "documentType": "Regulatory approval",
        "name": "Lynparza (olaparib) [package insert]. FDA.",
        "company": "Astrazeneca",
        "drug_name_brand": "Lynparza",
        "drug_name_generic": "olaparib",
        "identification_number": 208558,
        "publication_date": "2023-11-06",
        "status": "Active",
    },
    "document_evidence": {
        "company": "ASTRAZENECA PHARMACEUTICALS LP",
        "brand": "LYNPARZA",
        "generic": "OLAPARIB",
        "agent_note": "The company name was normalized from the FDA source value. Review that editorial choice before accepting.",
    },
    "indications": [
        {
            "id": "ind:fda.lynparza:1",
            "indication": "Lynparza is a poly (ADP-ribose) polymerase (PARP) inhibitor indicated in combination with bevacizumab for the maintenance treatment of adult patients with advanced epithelial ovarian, fallopian tube or primary peritoneal cancer who are in complete or partial response to first-line platinum-based chemotherapy and whose cancer is associated with homologous recombination deficiency (HRD)-positive status defined by either a deleterious or suspected deleterious BRCA mutation, and/or genomic instability. Select patients for therapy based on an FDA-approved companion diagnostic for Lynparza.",
            "raw_biomarkers": "homologous recombination deficiency (HRD)-positive status defined by either a deleterious or suspected deleterious BRCA mutation, and/or genomic instability",
            "raw_cancer_type": "advanced epithelial ovarian, fallopian tube or primary peritoneal cancer",
            "raw_therapeutics": "Lynparza (olaparib) in combination with bevacizumab",
            "source_text": "Lynparza is indicated in combination with bevacizumab for the maintenance treatment of adult patients with advanced epithelial ovarian, fallopian tube or primary peritoneal cancer who are in complete or partial response to first-line platinum-based chemotherapy and whose cancer is associated with homologous recombination deficiency (HRD)-positive status defined by either: a deleterious or suspected deleterious BRCA mutation, and/or genomic instability. Select patients for therapy based on an FDA-approved companion diagnostic for Lynparza.",
        }
    ],
    "descriptions": [
        {
            "indication_id": "ind:fda.lynparza:1",
            "description": "The U.S. Food and Drug Administration granted approval to olaparib in combination with bevacizumab for maintenance treatment of adult patients with HRD-positive advanced ovarian, fallopian tube, or primary peritoneal cancer following response to first-line platinum-based chemotherapy. The approval was supported by PAOLA-1 (NCT02477644).",
            "evidence": "PAOLA-1 was a randomized, double-blind, placebo-controlled trial comparing olaparib plus bevacizumab with placebo plus bevacizumab in the first-line maintenance setting.",
        }
    ],
    "approval_dates": [
        {
            "indication_id": "ind:fda.lynparza:1",
            "proposed_date": "2020-05-19",
            "proposed_url": "http://www.accessdata.fda.gov/drugsatfda_docs/label/2020/208558s014lbl.pdf",
            "warning": "A clinically equivalent indication appears in an earlier label. Curator review is required.",
            "events": [
                {
                    "date": "2020-05-08",
                    "url": "https://www.accessdata.fda.gov/drugsatfda_docs/label/2020/208558s013lbl.pdf",
                    "summary": "Combination indication introduced with 'HRD positive' wording.",
                    "recommended": True,
                },
                {
                    "date": "2020-05-19",
                    "url": "http://www.accessdata.fda.gov/drugsatfda_docs/label/2020/208558s014lbl.pdf",
                    "summary": "Heading revised and 'HRD-positive' hyphenated; clinical meaning unchanged.",
                    "recommended": False,
                },
            ],
        }
    ],
}


def fixture() -> dict:
    """Return an isolated fixture copy."""
    return deepcopy(LYNPARZA_FIXTURE)

