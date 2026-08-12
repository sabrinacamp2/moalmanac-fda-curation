#!/usr/bin/env python3
"""Build reusable FDA Section 1 changelog artifacts.

For each drug/application, this script fetches approved original and efficacy
supplement label documents from Drugs@FDA, extracts Section 1 / INDICATIONS AND
USAGE, records the first snapshot as an initial event, diffs subsequent Section
1 snapshots, and writes equivalent Markdown and JSON changelog artifacts.
Historical label PDFs and their converted Markdown are stored on disk and reused
on later runs.

Example:
    python build_section1_changelogs.py \
      --document-json outputs/Yervoy-bla125377/document.json \
      --work-dir outputs/Yervoy-bla125377
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import warnings
from pathlib import Path
from typing import Any

import requests

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL*")

from .curate_doc_from_drugsfda_endpoint import fetch_fda_record, fda_date_to_iso
from .extract_indication_approval_dates import (
    approval_relevant_label_docs,
    approved_label_docs,
    current_label_match,
    extract_indications_section_fallback,
    same_url,
)
from .extract_indications_from_fda_label import (
    convert_downloaded_pdf_to_markdown,
    download_pdf_bytes,
)
from .artifacts import (
    document_label_url,
    load_document_artifact,
    resolve_document_application_number,
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--document-json",
        type=Path,
        required=True,
        help=(
            "Generated MOAlmanac document JSON. "
            "Derives brand, application number, and selected label URL."
        ),
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        required=True,
        help=(
            "Workflow output root. Stores changelogs and Section 1 "
            "cache under intermediate/ and historical labels under "
            "historical-labels/."
        ),
    )
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    """Resolve a CLI path relative to the current working directory."""
    return path if path.is_absolute() else Path.cwd() / path


def output_stem(brand_name: str, application_number: str) -> str:
    """Build the filename stem used by FDA indication analyses."""
    brand_part = re.sub(r"[^A-Za-z0-9]+", "-", brand_name).strip("-")
    application_part = re.sub(r"[^A-Za-z0-9]+", "-", application_number).strip("-")
    return f"{brand_part}-{application_part.lower()}"


def load_cache(path: Path) -> dict[str, str]:
    """Load URL to Section 1 text cache."""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def save_cache(path: Path, cache: dict[str, str]) -> None:
    """Write URL to Section 1 text cache."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(cache, file, indent=2)
        file.write("\n")


def historical_label_stem(
    submission: dict[str, Any],
    label_url: str,
) -> str:
    """Build a stable, readable filename stem for one historical label."""
    date = fda_date_to_iso(submission["submission_status_date"])
    submission_type = submission.get("submission_type") or "submission"
    submission_number = submission.get("submission_number") or "unknown"
    url_stem = Path(label_url.split("?", 1)[0]).stem or "label"
    raw_stem = f"{date}-{submission_type}-{submission_number}-{url_stem}"
    return re.sub(r"[^A-Za-z0-9._-]+", "-", raw_stem).strip("-")


def load_or_create_label_markdown(
    submission: dict[str, Any],
    label_url: str,
    drug_labels_dir: Path,
) -> str:
    """Load saved Markdown or create it from a saved/downloaded label PDF."""
    label_stem = historical_label_stem(submission, label_url)
    pdf_path = drug_labels_dir / f"{label_stem}.pdf"
    markdown_path = drug_labels_dir / f"{label_stem}.md"

    if markdown_path.exists():
        print(f"reusing {markdown_path}")
        return markdown_path.read_text(encoding="utf-8")

    drug_labels_dir.mkdir(parents=True, exist_ok=True)
    if pdf_path.exists():
        print(f"converting saved {pdf_path}")
        pdf_bytes = pdf_path.read_bytes()
    else:
        print(f"downloading {submission['submission_status_date']} {label_url}")
        pdf_bytes = download_pdf_bytes(label_url)
        pdf_path.write_bytes(pdf_bytes)
        print(f"wrote {pdf_path}")

    markdown = convert_downloaded_pdf_to_markdown(pdf_bytes)
    markdown_path.write_text(markdown, encoding="utf-8")
    print(f"wrote {markdown_path}")
    return markdown


def section_1_snapshots(
    brand_name: str,
    application_number: str,
    current_label_url: str | None,
    cache_dir: Path,
    historical_labels_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch/cache historical Section 1 snapshots for one application."""
    fda_record = fetch_fda_record(application_number)
    label_docs = approved_label_docs(fda_record)
    relevant_label_docs = approval_relevant_label_docs(label_docs)

    current_match = (
        current_label_match(label_docs, current_label_url) if current_label_url else None
    )
    current_status_date = current_match[0]["submission_status_date"] if current_match else None
    if current_match and not any(
        same_url(doc["url"], current_match[1]["url"])
        for _, doc in relevant_label_docs
    ):
        relevant_label_docs.append(current_match)

    if current_status_date:
        relevant_label_docs = [
            (submission, doc)
            for submission, doc in relevant_label_docs
            if submission["submission_status_date"] <= current_status_date
        ]
    relevant_label_docs.sort(key=lambda item: item[0]["submission_status_date"])

    unique_label_docs = []
    for submission, doc in relevant_label_docs:
        if any(
            same_url(doc["url"], seen_doc["url"])
            for _, seen_doc in unique_label_docs
        ):
            continue
        unique_label_docs.append((submission, doc))
    relevant_label_docs = unique_label_docs

    stem = output_stem(brand_name, application_number)
    drug_labels_dir = historical_labels_dir / stem
    cache_path = cache_dir / f"{stem}-section1-cache.json"
    cache = load_cache(cache_path)
    snapshots = []
    skipped_labels = []

    for submission, doc in relevant_label_docs:
        url = doc["url"]
        try:
            markdown = load_or_create_label_markdown(
                submission=submission,
                label_url=url,
                drug_labels_dir=drug_labels_dir,
            )
            if url not in cache:
                cache[url] = extract_indications_section_fallback(markdown)
                save_cache(cache_path, cache)
        except requests.HTTPError as error:
            skipped_labels.append(
                {
                    "date": fda_date_to_iso(submission["submission_status_date"]),
                    "submission_type": submission.get("submission_type"),
                    "submission_number": submission.get("submission_number"),
                    "submission_class_code": submission.get("submission_class_code"),
                    "url": url,
                    "reason": str(error),
                }
            )
            print(
                "warning: skipping unavailable label "
                f"{submission['submission_status_date']} {url}: {error}"
            )
            continue

        snapshots.append(
            {
                "date": fda_date_to_iso(submission["submission_status_date"]),
                "submission_type": submission.get("submission_type"),
                "submission_number": submission.get("submission_number"),
                "submission_class_code": submission.get("submission_class_code"),
                "url": url,
                "section_1": cache[url],
            }
        )

    return snapshots, skipped_labels


def display_lines(text: str) -> list[str]:
    """Return non-empty stripped Section 1 lines without PDF boilerplate."""
    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if re.fullmatch(r"\d+", line):
            continue
        if re.fullmatch(r"Reference ID:\s*\d+", line, flags=re.IGNORECASE):
            continue
        if line.lower() == "this label may not be the latest approved by fda.":
            continue
        if line.lower().startswith("for current labeling information, please visit"):
            continue
        lines.append(line)
    return lines


def line_key(line: str) -> str:
    """Normalize one line for diffing while keeping display text unchanged."""
    line = line.lower()
    line = re.sub(r"reference id:\s*\d+", " ", line)
    line = re.sub(r"\s+", " ", line)
    return line.strip()


def is_subsection_heading(line: str) -> bool:
    """Return whether a line is a numbered Section 1 subsection heading."""
    return bool(re.fullmatch(r"1\.\d+\s+\S.*", line))


def logical_blocks(text: str) -> list[str]:
    """Reflow converted-PDF lines into stable Section 1 comparison blocks.

    Subsection headings define block boundaries but are omitted from comparison
    text, so adding or reformatting a heading does not become a clinical event.
    When numbered subsections are present, each subsection body is one block.
    Otherwise blank lines define blocks. Other line breaks are treated as PDF
    wrapping and joined.
    """
    blocks = []
    current = ""
    has_subsection_headings = any(
        is_subsection_heading(line.strip()) for line in text.splitlines()
    )

    def flush() -> None:
        nonlocal current
        if current:
            blocks.append(current)
            current = ""

    for raw_line in text.splitlines():
        if not raw_line.strip():
            if not has_subsection_headings:
                flush()
            continue

        cleaned = display_lines(raw_line)
        if not cleaned:
            continue
        line = cleaned[0]

        if is_subsection_heading(line):
            flush()
            continue

        line = re.sub(r"^[•▪◦]\s*", "• ", line)
        if not current:
            current = line
        elif current.endswith("-"):
            current += line
        else:
            current += f" {line}"

    flush()
    return blocks


def changed_blocks(previous_text: str, current_text: str) -> list[dict[str, Any]]:
    """Return inserted/replaced canonical Section 1 logical blocks."""
    previous_lines = logical_blocks(previous_text)
    current_lines = logical_blocks(current_text)
    previous_keys = [line_key(line) for line in previous_lines]
    current_keys = [line_key(line) for line in current_lines]

    matcher = difflib.SequenceMatcher(a=previous_keys, b=current_keys, autojunk=False)
    blocks = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag not in {"insert", "replace"}:
            continue

        added_lines = current_lines[j1:j2]
        previous_changed_lines = previous_lines[i1:i2]
        if not added_lines:
            continue

        previous_text = "\n".join(previous_changed_lines)
        added_text = "\n".join(added_lines)
        blocks.append(
            {
                "diff_tag": tag,
                "previous_text": previous_text,
                "added_text": added_text,
            }
        )

    return blocks


def section_1_changelog_events(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build an initial Section 1 event followed by consecutive changes."""
    events = []
    if snapshots:
        initial = snapshots[0]
        initial_text = "\n".join(logical_blocks(initial["section_1"]))
        if initial_text:
            events.append(
                {
                    "date": initial["date"],
                    "url": initial["url"],
                    "previous_date": None,
                    "previous_url": None,
                    "diff_tag": "initial",
                    "previous_text": "",
                    "added_text": initial_text,
                }
            )

    for previous, current in zip(snapshots, snapshots[1:]):
        for block in changed_blocks(previous["section_1"], current["section_1"]):
            events.append(
                {
                    "date": current["date"],
                    "url": current["url"],
                    "previous_date": previous["date"],
                    "previous_url": previous["url"],
                    **block,
                }
            )
    return events


def markdown_code_block(text: str) -> str:
    """Return a fenced Markdown text block."""
    fence = "```"
    while fence in text:
        fence += "`"
    return f"{fence}text\n{text.strip()}\n{fence}"


def section_1_changelog_payload(
    brand_name: str,
    application_number: str,
    events: list[dict[str, Any]],
    skipped_labels: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the shared changelog payload rendered to Markdown and JSON."""
    return {
        "brand_name": brand_name,
        "application_number": application_number,
        "skipped_labels": skipped_labels or [],
        "events": [
            {
                "event_number": event_number,
                "date": event["date"],
                "change_type": event["diff_tag"],
                "label_url": event["url"],
                "before_text": event["previous_text"] or None,
                "after_text": event["added_text"],
            }
            for event_number, event in enumerate(events, start=1)
        ],
    }


def build_section1_changelog_markdown(payload: dict[str, Any]) -> str:
    """Format the shared Section 1 changelog payload as Markdown."""
    lines = [
        f"# {payload['brand_name']} {payload['application_number']} Section 1 Changelog",
        "",
    ]

    skipped_labels = payload.get("skipped_labels") or []
    if skipped_labels:
        lines.extend(
            [
                "## Skipped Labels",
                "",
                "These FDA label records were listed in the application history but could not be downloaded or converted, so they were not used to build changelog events.",
                "",
            ]
        )
        for skipped in skipped_labels:
            lines.extend(
                [
                    f"- Date: {skipped['date']}",
                    f"  - Submission: {skipped.get('submission_type') or ''} {skipped.get('submission_number') or ''}".rstrip(),
                    f"  - Class: {skipped.get('submission_class_code') or ''}".rstrip(),
                    f"  - Label URL: {skipped['url']}",
                    f"  - Reason: {skipped['reason']}",
                ]
            )
        lines.append("")

    events = payload["events"]
    if not events:
        lines.append("No Section 1 events were detected.")
        return "\n".join(lines) + "\n"

    for event in events:
        lines.extend(
            [
                f"## Event {event['event_number']}",
                "",
                f"- Date: {event['date']}",
                f"- Change type: {event['change_type']}",
                f"- Label URL: {event['label_url']}",
                "",
            ]
        )
        if event.get("before_text"):
            lines.extend(
                [
                    "Before:",
                    "",
                    markdown_code_block(event["before_text"]),
                    "",
                    "After:",
                    "",
                ]
            )
        else:
            lines.extend(["After:", ""])
        lines.extend([markdown_code_block(event["after_text"]), ""])

    return "\n".join(lines) + "\n"


def build_changelog(
    brand_name: str,
    application_number: str,
    current_label_url: str | None,
    output_dir: Path,
    cache_dir: Path,
    historical_labels_dir: Path,
) -> tuple[Path, Path]:
    """Build and write one per-drug Section 1 changelog."""
    snapshots, skipped_labels = section_1_snapshots(
        brand_name=brand_name,
        application_number=application_number,
        current_label_url=current_label_url,
        cache_dir=cache_dir,
        historical_labels_dir=historical_labels_dir,
    )
    events = section_1_changelog_events(snapshots)
    payload = section_1_changelog_payload(
        brand_name=brand_name,
        application_number=application_number,
        events=events,
        skipped_labels=skipped_labels,
    )
    markdown = build_section1_changelog_markdown(payload)

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = output_stem(brand_name, application_number)
    markdown_path = output_dir / f"{stem}-section1-changelog.md"
    json_path = output_dir / f"{stem}-section1-changelog.json"
    markdown_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return markdown_path, json_path


def main() -> int:
    """Run the CLI."""
    args = parse_args()
    work_dir = resolve_path(args.work_dir)
    output_dir = work_dir / "intermediate" / "section1-changelogs"
    cache_dir = work_dir / "intermediate" / "section1-cache"
    historical_labels_dir = work_dir / "historical-labels"
    document = load_document_artifact(resolve_path(args.document_json))
    brand_name = document["drug_name_brand"]
    application_number = resolve_document_application_number(document)
    current_label_url = document_label_url(document)

    print(f"building {brand_name} {application_number}")
    markdown_path, json_path = build_changelog(
        brand_name=brand_name,
        application_number=application_number,
        current_label_url=current_label_url,
        output_dir=output_dir,
        cache_dir=cache_dir,
        historical_labels_dir=historical_labels_dir,
    )
    print(f"wrote {markdown_path}")
    print(f"wrote {json_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
