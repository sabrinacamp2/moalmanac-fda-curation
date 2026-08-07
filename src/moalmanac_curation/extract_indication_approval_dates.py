#!/usr/bin/env python3
"""Create conservative FDA indication approval-date candidates.

This script is a downstream step after ``extract_indications_from_fda_label.py``.
It uses the chunked indication extraction JSON from that script and tries to
assign an approval date and label URL candidate to each extracted indication.

The workflow is intentionally conservative:
1. Fetch the FDA submissions record for one application number.
2. Find approved label PDFs from the original application and EFFICACY
   supplements.
3. Extract Section 1, INDICATIONS AND USAGE, from those labels.
4. For each extracted indication, use its deterministic source chunk.
5. If the chunk produced exactly one indication, exact-match normalized source
   chunk text against historical Section 1 text.
6. If there is no exact match, or if the chunk produced multiple indications,
   leave the date and URL as null.

The output is intentionally minimal and aligns by ``indication_index`` with the
input ``indications`` list.

Example:
    python extract_indication_approval_dates.py \
      --application-number NDA208558 \
      --current-label-url https://www.accessdata.fda.gov/drugsatfda_docs/label/2023/208558s028lbl.pdf \
      --chunked-indications-json extracted-indications/Lynparza-nda208558-claude_chunked_indication_fields.json
"""

from __future__ import annotations

import argparse
import json
import re
import warnings
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL*")

from .curate_doc_from_drugsfda_endpoint import fetch_fda_record, fda_date_to_iso
from .extract_indications_from_fda_label import (
    convert_downloaded_pdf_to_markdown,
    download_pdf_bytes,
    extract_indications_section,
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for one approval-date candidate run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--application-number",
        required=True,
        help='FDA application number, e.g. "NDA208558".',
    )
    parser.add_argument(
        "--current-label-url",
        required=True,
        help="FDA label PDF URL used for the upstream indication extraction.",
    )
    parser.add_argument(
        "--chunked-indications-json",
        type=Path,
        required=True,
        help="Path to the *-claude_chunked_indication_fields.json file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Optional output JSON path. Defaults beside the chunked indications "
            "JSON as *-approval_date_candidates.json."
        ),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Rewrite the output file when it already exists.",
    )
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    """Resolve a CLI path relative to the current working directory."""
    return path if path.is_absolute() else Path.cwd() / path


def same_url(a: str, b: str) -> bool:
    """Compare FDA label URLs by path so http/https differences do not matter."""
    return urlparse(a).path == urlparse(b).path


def default_output_path(chunked_indications_json: Path) -> Path:
    """Build the default output path from the upstream extraction JSON path."""
    suffix = "-claude_chunked_indication_fields.json"
    name = chunked_indications_json.name

    if name.endswith(suffix):
        stem = name[: -len(suffix)]
    else:
        stem = chunked_indications_json.stem

    return chunked_indications_json.with_name(f"{stem}-approval_date_candidates.json")


def extract_indications_section_fallback(label_markdown: str) -> str:
    """Extract Section 1 with a fallback for older converted label markdown."""
    try:
        return extract_indications_section(label_markdown)
    except ValueError:
        full_prescribing_headings = list(
            re.finditer(
                r"(?m)^FULL PRESCRIBING INFORMATION\s*$",
                label_markdown,
            )
        )
        if full_prescribing_headings:
            # Older labels can contain a contents page followed by the actual
            # full prescribing section. Use the last exact heading.
            full_prescribing_heading = full_prescribing_headings[-1]
            full_prescribing_text = label_markdown[
                full_prescribing_heading.end() :
            ]
        else:
            # Some older two-column PDFs are converted with sequential OCR line
            # numbers prefixed to every full-prescribing line, for example:
            # "1 FULL PRESCRIBING INFORMATION", "2 1 INDICATIONS...",
            # and "7 2 DOSAGE...". Strip those prefixes only after detecting
            # this specific numbered full-prescribing heading.
            numbered_headings = list(
                re.finditer(
                    r"(?m)^\s*\d+\s+FULL PRESCRIBING INFORMATION\s*$",
                    label_markdown,
                )
            )
            if not numbered_headings:
                raise
            numbered_heading = numbered_headings[-1]
            numbered_text = label_markdown[numbered_heading.end() :]
            full_prescribing_text = "\n".join(
                re.sub(r"^\s*\d+\s+", "", line)
                for line in numbered_text.splitlines()
            )
        start = re.search(
            r"(?m)^(?:1\s+)?INDICATIONS AND USAGE\s*$",
            full_prescribing_text,
        )
        if not start:
            raise

        remaining = full_prescribing_text[start.end() :]
        end = re.search(r"(?m)^\s*2(?:\s|\.|$)", remaining)
        if not end:
            raise

        return remaining[: end.start()].strip()


def raw_indications_from_url(label_url: str) -> str:
    """Download one FDA label PDF and return its raw Section 1 text."""
    pdf = download_pdf_bytes(label_url)
    markdown = convert_downloaded_pdf_to_markdown(pdf)
    return extract_indications_section_fallback(markdown)


def source_chunk_body(text: str) -> str:
    """Remove deterministic source-chunk heading text before exact matching."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    for index, line in enumerate(lines):
        if "indicated" in line.lower():
            return "\n".join(lines[index:])

    return "\n".join(lines)


def norm(text: str) -> str:
    """Normalize label text for conservative exact containment checks."""
    text = text.lower()
    text = re.sub(r"\[[^\]]+\]", " ", text)
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def approved_label_docs(fda_record: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Return approved FDA label documents from the application record."""
    return sorted(
        [
            (submission, doc)
            for submission in fda_record["submissions"]
            if submission.get("submission_status") == "AP"
            for doc in submission.get("application_docs", [])
            if doc.get("type") == "Label"
        ],
        key=lambda item: item[0]["submission_status_date"],
    )


def approval_relevant_label_docs(
    label_docs: list[tuple[dict[str, Any], dict[str, Any]]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Keep the original label plus EFFICACY supplement labels."""
    return [
        (submission, label_doc)
        for submission, label_doc in label_docs
        if submission.get("submission_type") == "ORIG"
        or submission.get("submission_class_code") == "EFFICACY"
    ]


def first_original_label(
    label_docs: list[tuple[dict[str, Any], dict[str, Any]]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the first approved original label submission."""
    return next(
        (submission, doc)
        for submission, doc in label_docs
        if submission.get("submission_type") == "ORIG"
    )


def current_label_match(
    label_docs: list[tuple[dict[str, Any], dict[str, Any]]],
    current_label_url: str,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Find the FDA submission record matching the current label URL."""
    return next(
        (
            (submission, doc)
            for submission, doc in label_docs
            if same_url(current_label_url, doc["url"])
        ),
        None,
    )


def load_historical_raw_sections(
    label_docs: list[tuple[dict[str, Any], dict[str, Any]]],
    current_submission: dict[str, Any] | None,
) -> list[dict[str, str]]:
    """Extract normalized Section 1 text for historical approval-relevant labels."""
    current_status_date = (
        current_submission["submission_status_date"] if current_submission else None
    )
    historical_raw_sections = []

    for submission, label_doc in label_docs:
        if current_status_date and submission["submission_status_date"] > current_status_date:
            continue

        raw = raw_indications_from_url(label_doc["url"])
        historical_raw_sections.append(
            {
                "date": fda_date_to_iso(submission["submission_status_date"]),
                "url": label_doc["url"],
                "raw_norm": norm(raw),
            }
        )

    return historical_raw_sections


def count_indications_per_chunk(indications: list[dict[str, Any]]) -> dict[int, int]:
    """Count how many extracted indications came from each source chunk."""
    counts: dict[int, int] = {}

    for indication in indications:
        chunk_index = indication["source_chunk_index"]
        counts[chunk_index] = counts.get(chunk_index, 0) + 1

    return counts


def build_approval_date_candidates(
    application_number: str,
    current_label_url: str,
    chunked_indications: dict[str, Any],
) -> dict[str, Any]:
    """Build minimal per-indication approval-date candidate metadata."""
    fda_record = fetch_fda_record(application_number)
    label_docs = approved_label_docs(fda_record)
    relevant_label_docs = approval_relevant_label_docs(label_docs)

    original_submission, original_label = first_original_label(label_docs)
    current_match = current_label_match(label_docs, current_label_url)
    current_submission = current_match[0] if current_match else None

    current_raw_indications = raw_indications_from_url(current_label_url)
    original_raw_indications = raw_indications_from_url(original_label["url"])
    same_indication_section_as_original = (
        norm(current_raw_indications) == norm(original_raw_indications)
    )

    historical_raw_sections = load_historical_raw_sections(
        relevant_label_docs,
        current_submission,
    )

    source_chunks = chunked_indications["source_chunks"]
    extracted_indications = chunked_indications["indications"]
    source_chunk_text_by_index = {
        chunk["source_chunk_index"]: chunk["source_chunk_text"]
        for chunk in source_chunks
    }
    chunk_indication_counts = count_indications_per_chunk(extracted_indications)

    is_original_label = same_url(current_label_url, original_label["url"])
    original_approval_date = fda_date_to_iso(original_submission["submission_status_date"])
    original_approval_url = original_label["url"]

    indication_approval_metadata = []

    for index, indication in enumerate(extracted_indications):
        chunk_index = indication["source_chunk_index"]
        chunk_count = chunk_indication_counts[chunk_index]
        source_chunk_text = source_chunk_text_by_index[chunk_index]
        source_chunk_match_text = source_chunk_body(source_chunk_text)

        if is_original_label or same_indication_section_as_original:
            candidate_date = original_approval_date
            candidate_url = original_approval_url
        elif chunk_count > 1:
            candidate_date = None
            candidate_url = None
        else:
            query_norm = norm(source_chunk_match_text)
            matched_label = next(
                (
                    historical
                    for historical in historical_raw_sections
                    if query_norm in historical["raw_norm"]
                ),
                None,
            )
            candidate_date = matched_label["date"] if matched_label else None
            candidate_url = matched_label["url"] if matched_label else None

        indication_approval_metadata.append(
            {
                "indication_index": index,
                "initial_approval_date_candidate": candidate_date,
                "initial_approval_url_candidate": candidate_url,
            }
        )

    return {
        "application_number": application_number,
        "current_label_url": current_label_url,
        "indication_approval_metadata": indication_approval_metadata,
    }


def main() -> int:
    """Run the CLI and write the approval-date candidate JSON."""
    args = parse_args()
    chunked_indications_json = resolve_path(args.chunked_indications_json)
    output_path = resolve_path(args.output) if args.output else default_output_path(
        chunked_indications_json
    )

    if output_path.exists() and not args.overwrite:
        raise FileExistsError(f"{output_path} already exists. Use --overwrite to rewrite it.")

    with chunked_indications_json.open(encoding="utf-8") as f:
        chunked_indications = json.load(f)

    output = build_approval_date_candidates(
        application_number=args.application_number,
        current_label_url=args.current_label_url,
        chunked_indications=chunked_indications,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")

    print(f"approval_date_candidates: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
