#!/usr/bin/env python3
"""Create a MOAlmanac FDA document proposal from the openFDA drug/drugsfda endpoint.

The proposal holds one `documents.json` record and the `urls.json` records it cites.

Example:
    python curate_doc_from_drugsfda_endpoint.py --application-number NDA211651

"""

from __future__ import annotations

import argparse
import json
import re
import warnings
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL*")

import requests

from .moalmanac_records import FDA_AGENT_ID, fda_document_id, fda_label_citation, url_id


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--application-number",
        required=True,
        help='FDA application number exactly as indexed by openFDA, e.g. "NDA211651".',
    )
    parser.add_argument(
        "--accessed-date",
        type=lambda value: datetime.strptime(value, "%Y-%m-%d").date(),
        default=date.today(),
        help="Access date for the citation, YYYY-MM-DD. Defaults to today.",
    )
    parser.add_argument(
        "--company",
        help=(
            "Optional curator-supplied company name. If omitted, the script uses "
            "drug/drugsfda.sponsor_name, which may need cleanup."
        ),
    )
    parser.add_argument(
        "--label-url",
        help=(
            "Optional historical FDA label URL. When supplied, use the matching "
            "approved label submission instead of the latest approved label."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write the document JSON.",
    )
    return parser.parse_args()


def fetch_fda_record(application_number: str) -> dict[str, Any]:
    """Fetch one Drugs@FDA application record by exact application number."""
    response = requests.get(
        "https://api.fda.gov/drug/drugsfda.json",
        params={"search": f'application_number:"{application_number}"'},
        timeout=30,
    )
    response.raise_for_status()

    results = response.json().get("results", [])
    if not results:
        raise ValueError(f"No drug/drugsfda record found for {application_number}")
    return results[0]


def get_application_identifiers(fda_record: dict[str, Any]) -> dict[str, Any]:
    """Prepare application-number fields and the Drugs@FDA overview URL."""
    application_number = fda_record["application_number"]
    identification_number = re.sub(r"\D", "", application_number)
    overview_url = (
        "https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm"
        f"?event=overview.process&ApplNo={identification_number}"
    )

    return {
        "application_number": application_number,
        "identification_number": int(identification_number),
        "overview_url": overview_url,
    }


def same_url_path(first: str, second: str) -> bool:
    """Compare FDA URLs by path so HTTP/HTTPS differences do not matter."""
    return urlparse(first).path == urlparse(second).path


def get_label_version_fields(
    fda_record: dict[str, Any],
    label_url_override: str | None = None,
) -> dict[str, Any]:
    """Find the original approval and selected approved label submission."""
    submissions = fda_record["submissions"]

    original_submission = next(
        submission
        for submission in submissions
        if submission.get("submission_type") == "ORIG"
        and submission.get("submission_status") == "AP"
    )

    approved_label_submissions = []
    for submission in submissions:
        if submission.get("submission_status") != "AP":
            continue

        for doc in submission.get("application_docs", []) or []:
            if doc.get("type") == "Label":
                approved_label_submissions.append((submission, doc))

    if not approved_label_submissions:
        raise ValueError("No approved label documents found in drug/drugsfda submissions")

    if label_url_override:
        selected = next(
            (
                (submission, doc)
                for submission, doc in approved_label_submissions
                if same_url_path(doc["url"], label_url_override)
            ),
            None,
        )
        if selected is None:
            raise ValueError(
                "The requested label URL was not found among approved labels for "
                f"{fda_record['application_number']}: {label_url_override}"
            )
        selected_label_submission, selected_label_doc = selected
    else:
        selected_label_submission, selected_label_doc = max(
            approved_label_submissions,
            key=lambda item: item[0].get("submission_status_date", ""),
        )

    return {
        "first_publication_date_raw": original_submission["submission_status_date"],
        "publication_date_raw": selected_label_submission["submission_status_date"],
        "label_url": selected_label_doc["url"],
    }


def fda_date_to_iso(value: str) -> str:
    """Convert an FDA YYYYMMDD date string to YYYY-MM-DD."""
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def get_date_fields(label_fields: dict[str, Any], accessed_date: date) -> dict[str, str]:
    """Prepare normalized ISO dates for the document and its citation."""
    return {
        "first_publication_date": fda_date_to_iso(label_fields["first_publication_date_raw"]),
        "publication_date": fda_date_to_iso(label_fields["publication_date_raw"]),
        "accessed_date": accessed_date.isoformat(),
    }


def get_drug_and_company_fields(
    fda_record: dict[str, Any],
    company_override: str | None = None,
) -> dict[str, str]:
    """Prepare brand, generic, and company display fields."""
    openfda = fda_record.get("openfda") or {}
    if not openfda.get("brand_name") or not openfda.get("generic_name"):
        application_number = fda_record.get("application_number", "<unknown>")
        raise ValueError(
            f"drug/drugsfda record for {application_number} has no openfda "
            "brand_name/generic_name (openFDA's SPL-to-application linkage did "
            "not populate for this record). This tool has no supported fallback "
            "for deriving normalized brand/generic names from another field; "
            "curate this application manually."
        )

    brand = openfda["brand_name"][0].title()
    generic = openfda["generic_name"][0].lower()
    company = company_override or fda_record["sponsor_name"].title()

    return {
        "brand": brand,
        "generic": generic,
        "company": company,
    }


def get_formatted_text_fields(
    drug_fields: dict[str, str],
    label_fields: dict[str, Any],
    date_fields: dict[str, str],
) -> dict[str, str]:
    """Build MOAlmanac-formatted ID, name, and description strings."""
    brand = drug_fields["brand"]
    generic = drug_fields["generic"]
    return {
        "document_id": fda_document_id(brand),
        "name": f"{brand} ({generic}) [package insert]. FDA.",
        "description": fda_label_citation(
            company=drug_fields["company"],
            brand=brand,
            generic=generic,
            label_url=label_fields["label_url"],
            label_date=date_fields["publication_date"],
            accessed_date=date_fields["accessed_date"],
        ),
    }


def build_document_proposal(
    application_fields: dict[str, Any],
    label_fields: dict[str, Any],
    date_fields: dict[str, str],
    drug_fields: dict[str, str],
    text_fields: dict[str, str],
) -> dict[str, Any]:
    """Assemble one documents.json record and the urls.json records it cites."""
    document_id = text_fields["document_id"]
    label_url_id = url_id(document_id, "label")
    overview_url_id = url_id(document_id, "overview")
    return {
        "document": {
            "id": document_id,
            "type": "Document",
            "documentType": "Regulatory approval",
            "name": text_fields["name"],
            "title": None,
            "aliases": [],
            "description": text_fields["description"],
            "urls": [label_url_id, overview_url_id],
            "doi": None,
            "pmid": None,
            "agent_id": FDA_AGENT_ID,
            "company": drug_fields["company"],
            "drug_name_brand": drug_fields["brand"],
            "drug_name_generic": drug_fields["generic"],
            "first_publication_date": date_fields["first_publication_date"],
            "identification_number": application_fields["identification_number"],
            "publication_date": date_fields["publication_date"],
            "status": "Active",
        },
        "urls": [
            {"id": label_url_id, "url": label_fields["label_url"]},
            {"id": overview_url_id, "url": application_fields["overview_url"]},
        ],
    }


def curate_document(args: argparse.Namespace) -> dict[str, Any]:
    """Run each curation step and return the document proposal."""
    fda_record = fetch_fda_record(args.application_number)

    application_fields = get_application_identifiers(fda_record)
    label_fields = get_label_version_fields(fda_record, args.label_url)
    date_fields = get_date_fields(label_fields, args.accessed_date)
    drug_fields = get_drug_and_company_fields(fda_record, args.company)
    text_fields = get_formatted_text_fields(drug_fields, label_fields, date_fields)

    return build_document_proposal(
        application_fields=application_fields,
        label_fields=label_fields,
        date_fields=date_fields,
        drug_fields=drug_fields,
        text_fields=text_fields,
    )


def main() -> int:
    """Create and print or write one FDA document proposal."""
    args = parse_args()
    proposal = curate_document(args)
    text = json.dumps(proposal, indent=2) + "\n"

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        print(text, end="")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
