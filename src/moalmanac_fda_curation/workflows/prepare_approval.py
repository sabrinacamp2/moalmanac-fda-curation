"""Build/reuse label history and match retained indications to approval events."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..core.build_section1_changelogs import (
    build_changelog,
    build_section1_changelog_markdown,
    output_stem,
)
from ..core.match_indication_approval_dates_from_changelog import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    build_changelog_approval_date_matches,
    load_changelog_payload,
    load_chunked_indication_fields,
    selected_indication_indexes,
)
from ..core.artifacts import (
    document_label_url,
    load_document_artifact,
    resolve_document_application_number,
    write_json_atomic,
)


def post_baseline_changelog(
    payload: dict, baseline_date: str, latest_date: str
) -> dict:
    """Return only selectable events for the current revised indication form."""
    events = [
        event
        for event in payload["events"]
        if baseline_date < event.get("date", "") <= latest_date
    ]
    if not events:
        raise ValueError(
            "No changelog events fall after the curated label through the latest label"
        )
    return {**payload, "events": events}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document-json", type=Path, required=True)
    parser.add_argument("--indication-fields-json", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="Optional explicit approval-evidence JSON path.")
    parser.add_argument("--indication-index", type=int, action="append")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument(
        "--revision-baseline-date",
        help="Use only changelog events after this previously curated label date.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Rebuild existing history and date-match outputs.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    work_dir = args.work_dir.resolve()
    document = load_document_artifact(args.document_json.resolve())
    indications = load_chunked_indication_fields(args.indication_fields_json.resolve())
    brand = document["drug_name_brand"]
    application = resolve_document_application_number(document)
    stem = output_stem(brand, application)
    changelog_dir = work_dir / "intermediate" / "section1-changelogs"
    changelog_json = changelog_dir / f"{stem}-section1-changelog.json"
    changelog_markdown = changelog_dir / f"{stem}-section1-changelog.md"

    if changelog_json.exists() and changelog_markdown.exists() and not args.overwrite:
        print(f"Reusing {changelog_json}")
    else:
        changelog_markdown, changelog_json = build_changelog(
            brand_name=brand,
            application_number=application,
            current_label_url=document_label_url(document),
            output_dir=changelog_dir,
            cache_dir=work_dir / "intermediate" / "section1-cache",
            historical_labels_dir=work_dir / "historical-labels",
        )

    output_path = (
        args.output.resolve()
        if args.output
        else work_dir / "intermediate" / f"{stem}-approval-evidence.json"
    )
    if output_path.exists() and not args.overwrite:
        existing = json.loads(output_path.read_text(encoding="utf-8"))
        requested = selected_indication_indexes(
            indications["indications"], args.indication_index
        )
        existing_indexes = {
            item.get("indication_index") for item in existing if isinstance(item, dict)
        }
        if existing_indexes.issuperset(requested):
            print(f"Reusing {output_path}")
            return 0
        raise FileExistsError(
            f"{output_path} does not contain every requested indication. "
            "Use --overwrite after confirming regeneration."
        )

    changelog_payload = load_changelog_payload(changelog_json)
    if args.revision_baseline_date:
        changelog_payload = post_baseline_changelog(
            changelog_payload,
            args.revision_baseline_date,
            document["publication_date"],
        )
    indexes = selected_indication_indexes(
        indications["indications"], args.indication_index
    )
    matches = build_changelog_approval_date_matches(
        chunked_indications=indications,
        changelog_markdown=build_section1_changelog_markdown(changelog_payload),
        changelog_payload=changelog_payload,
        model=args.model,
        max_tokens=args.max_tokens,
        requested_indexes=indexes,
    )
    write_json_atomic(output_path, matches)
    skipped = changelog_payload.get("skipped_labels") or []
    print(f"Wrote {changelog_markdown}")
    print(f"Wrote {changelog_json}")
    print(f"Wrote {output_path}")
    if skipped:
        print(f"WARNING: {len(skipped)} historical label(s) were skipped; review before accepting dates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
