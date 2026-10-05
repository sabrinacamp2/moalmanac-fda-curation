# MOAlmanac output examples

Use these examples to recognize the current referenced JSON shape and common editorial
patterns. They are copied from the sibling `moalmanac-db` checkout as examples, not as
ground truth for another curation. Always derive target values from the selected label
and workflow evidence. When `moalmanac-db` is available, inspect its current files
because the schema and editorial conventions can change.

## Document and URL example

From `referenced/documents.json`:

```json
{
  "id": "doc:fda:libtayo",
  "type": "Document",
  "documentType": "Regulatory approval",
  "name": "Libtayo (cemiplimab) [package insert]. FDA.",
  "title": null,
  "aliases": [],
  "description": "Regeneron Pharmaceuticals, Inc. Libtayo (cemiplimab) [package insert]. U.S. Food and Drug Administration website. https://www.accessdata.fda.gov/drugsatfda_docs/label/2024/761097s023lbl.pdf. Revised April 2024. Accessed October 30, 2024.",
  "urls": [
    "url:fda:libtayo:label",
    "url:fda:libtayo:overview"
  ],
  "doi": null,
  "pmid": null,
  "agent_id": "agent:org:fda",
  "company": "Regeneron Pharmaceuticals, Inc.",
  "drug_name_brand": "Libtayo",
  "drug_name_generic": "cemiplimab",
  "first_publication_date": null,
  "identification_number": 761097,
  "publication_date": "2024-04-05",
  "status": "Active"
}
```

The document cites its URLs by ID. The URLs themselves live in `referenced/urls.json`:

```json
[
  {
    "id": "url:fda:libtayo:label",
    "url": "https://www.accessdata.fda.gov/drugsatfda_docs/label/2024/761097s023lbl.pdf"
  },
  {
    "id": "url:fda:libtayo:overview",
    "url": "https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo=761097"
  }
]
```

Company naming and punctuation are editorial fields, while application, label date, and
URL require source provenance.

## Indication example: indication-only statement description

From `referenced/indications.json`:

```json
{
  "id": "ind:fda:libtayo:1",
  "type": "Indication",
  "description": "LIBTAYO is a programmed death receptor-1 (PD-1) blocking antibody indicated as single agent for the first-line treatment of adult patients with NSCLC whose tumors have high PD-L1 expression [Tumor Proportion Score (TPS) >= 50%] as determined by an FDA-approved test, with no EGFR, ALK or ROS1 aberrations, and is: (i) locally advanced where patients are not candidates for surgical resection or definitive chemoradiation or (ii) metastatic.",
  "contributions": [
    "ctrb:vanallenlab:2024-10-30:0",
    "ctrb:fda:2021-02-22:0"
  ],
  "reportedIn": [
    "doc:fda:libtayo"
  ],
  "status": "Approved",
  "statement_description": "The U.S. Food and Drug Administration granted approval to cemiplimab for the first-line treatment of adult patients with NSCLC whose tumors have high PD-L1 expression [Tumor Proportion Score (TPS) >= 50%] as determined by an FDA-approved test, with no EGFR, ALK or ROS1 aberrations, and is: (i) locally advanced where patients are not candidates for surgical resection or definitive chemoradiation or (ii) metastatic.",
  "raw_biomarkers": "high PD-L1 expression [Tumor Proportion Score (TPS) >= 50%] with no EGFR, ALK or ROS1 aberrations",
  "raw_cancer_types": "non-small cell lung cancer",
  "raw_therapeutics": "Libtayo (cemiplimab)",
  "superseded_by": []
}
```

The indication's `description` is the approval as written in the label. Its
`statement_description` mainly reframes that approval; it does not add trial detail
merely because Clinical Studies text exists. The approval date is the FDA contribution,
from `referenced/contributions.json`:

```json
[
  {
    "id": "ctrb:vanallenlab:2024-10-30:0",
    "type": "Contribution",
    "agent_id": "agent:user:vanallenlab",
    "description": "Initial access of FDA approvals",
    "date": "2024-10-30"
  },
  {
    "id": "ctrb:fda:2021-02-22:0",
    "type": "Contribution",
    "agent_id": "agent:org:fda",
    "description": "Indication received traditional approval.",
    "date": "2021-02-22"
  }
]
```

## Indication example: Clinical Studies detail adds meaning

```json
{
  "id": "ind:fda:sprycel:4",
  "type": "Indication",
  "description": "SPRYCEL is a kinase inhibitor indicated for the treatment of pediatric patients 1 year of age and older with newly diagnosed Ph+ ALL in combination with chemotherapy.",
  "contributions": [
    "ctrb:vanallenlab:2025-06-26:0",
    "ctrb:vanallenlab:2024-10-30:0",
    "ctrb:fda:2018-12-21:0"
  ],
  "reportedIn": [
    "doc:fda:sprycel"
  ],
  "status": "Approved",
  "statement_description": "The U.S. Food and Drug Administration granted approval to dasatinib in combination with chemotherapy for the treatment of pediatric patients 1 year of age and older with newly diagnosed Philadelphia chromosome-positive acute lymphoblastic leukemia (Ph+ ALL). This indication is based on CA180372 (NCT01460160), a multicenter, multiple-cohort study of pediatric patients with newly diagnosed B-cell precursor Ph+ ALL, where the backbone chemotherapy regimen was AIEOP-BFM ALL 2000 multi-agent chemotherapy protocol.",
  "raw_biomarkers": "philadelphia chromosome-positive (Ph+)",
  "raw_cancer_types": "philadelphia chromosome-positive ALL",
  "raw_therapeutics": "Sprycel (dasatinib) in combination with chemotherapy",
  "superseded_by": []
}
```

Here the Clinical Studies sentence identifies what the broad term `chemotherapy`
meant in the supporting study. This is the exception to justify from evidence, not a
requirement to add trial detail to every statement description.

## Indication example: accelerated approval

`ind:fda:krazati:0` has `"status": "Accelerated"` because its label text states that the
indication "is approved under accelerated approval". Its FDA contribution reads
"Indication received accelerated approval." rather than "Indication received traditional
approval."

## Output checks

- Keep `reportedIn` aligned with the document's `id`.
- Order an indication's `contributions` by date, newest first.
- Use ISO `YYYY-MM-DD` dates.
- Preserve the approval as written in `description`, including material qualifiers.
- Keep `statement_description` concise; add Clinical Studies detail only when it
  clarifies the indication.
- Format the label drug as `Brand (generic)` in `raw_therapeutics`; do not impose that
  formatting on the indication sentence.
- Treat IDs and array indexes in these examples as illustrative, not reusable.
