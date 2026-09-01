"""Assess revisions and create Markdown reviews only for flagged indications."""

from __future__ import annotations

import argparse
import difflib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..core.artifacts import load_json_object, write_json_atomic
from ..core.identify_new_indications import load_existing_indications
from ..core.build_section1_changelogs import build_section1_changelog_markdown
from ..core.identify_revised_indications import (
    DEFAULT_MODEL as ASSESSMENT_MODEL,
    build_section_diff_hunks,
    identify_revised_indications,
    load_section_pair_from_cache,
)
from ..core.review_revised_indication import (
    DEFAULT_MODEL as REVIEW_MODEL,
    review_revised_indication,
)
from ..core.match_indication_approval_dates_from_changelog import load_changelog_payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--existing-indications-json", type=Path, required=True)
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--section-cache-json", type=Path, required=True)
    parser.add_argument("--changelog-json", type=Path, required=True)
    parser.add_argument("--baseline-label-url", required=True)
    parser.add_argument("--latest-label-url", required=True)
    parser.add_argument("--baseline-label-date", required=True)
    parser.add_argument("--latest-label-date", required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--context-blocks", type=int, default=1)
    parser.add_argument("--assessment-model", default=ASSESSMENT_MODEL)
    parser.add_argument("--review-model", default=REVIEW_MODEL)
    parser.add_argument("--assessment-max-tokens", type=int, default=8000)
    parser.add_argument("--review-max-tokens", type=int, default=3000)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "revision"


def changed_phrases(baseline: str, latest: str) -> list[dict[str, str | None]]:
    """Return exact removed and added phrases from a deterministic word diff."""
    pattern = r"\w+(?:[-’']\w+)*|[^\w\s]"
    before = re.findall(pattern, baseline, flags=re.UNICODE)
    after = re.findall(pattern, latest, flags=re.UNICODE)
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    changes = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        changes.append(
            {
                "removed": " ".join(before[i1:i2]) or None,
                "added": " ".join(after[j1:j2]) or None,
            }
        )
    return changes


def local_label_artifacts(work_dir: Path, label_url: str) -> tuple[Path | None, Path | None]:
    """Find the locally cached PDF and Markdown corresponding to an FDA label URL."""
    filename = Path(urlparse(label_url).path).name
    if not filename:
        return None, None
    pdf_matches = sorted(work_dir.rglob(f"*{filename}"))
    markdown_name = f"{Path(filename).stem}.md"
    markdown_matches = sorted(work_dir.rglob(f"*{markdown_name}"))
    return (
        pdf_matches[0].resolve() if pdf_matches else None,
        markdown_matches[0].resolve() if markdown_matches else None,
    )


def quote_value(value: Any) -> list[str]:
    """Render one complete field value as a Markdown quote."""
    rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return [f"> {line}" for line in str(rendered).splitlines()]


def phrase_change_markdown(change: dict[str, str | None]) -> str:
    """Describe one deterministic word-level change without implying field semantics."""
    removed = change.get("removed")
    added = change.get("added")
    if removed and added:
        return f"- Replaced `{removed}` with `{added}`"
    if added:
        return f"- Added `{added}`"
    return f"- Removed `{removed}`"


def bounded_changelog(
    payload: dict[str, Any], baseline_date: str, latest_date: str
) -> dict[str, Any]:
    """Keep events from the curated baseline through the latest label."""
    events = [
        event
        for event in payload.get("events") or []
        if baseline_date <= event.get("date", "") <= latest_date
    ]
    if not events:
        raise ValueError(
            "No changelog events fall between the curated and latest label dates"
        )
    renumbered = [
        {
            **event,
            "original_event_number": event.get("event_number"),
            "event_number": index,
        }
        for index, event in enumerate(events, start=1)
    ]
    return {**payload, "events": renumbered}


def revision_markdown(
    assessment: dict[str, Any],
    proposal: dict[str, Any],
    *,
    baseline_label_url: str,
    latest_label_url: str,
    baseline_label_date: str | None,
    latest_label_date: str | None,
    assessment_path: Path,
    proposals_path: Path,
    reconciliation_path: Path,
    baseline_label_pdf_path: Path | None = None,
    baseline_label_markdown_path: Path | None = None,
    latest_label_pdf_path: Path | None = None,
    latest_label_markdown_path: Path | None = None,
    changelog_markdown_path: Path | None = None,
) -> str:
    existing = assessment["existing_indication"]
    proposed = proposal["proposed_indication"]
    changed_fields = [
        field
        for field in (
            "indication",
            "description",
            "raw_biomarkers",
            "raw_cancer_type",
            "raw_therapeutics",
        )
        if existing.get(field) != proposed.get(field)
    ]
    display_name = existing.get("raw_cancer_type") or assessment["existing_indication_id"]
    event = proposal["revision_event"]
    lines = [
        f"# Revision review — {display_name}",
        "",
        f"- Indication ID: `{assessment['existing_indication_id']}`",
        f"- Proposed revision date: [{event['date']}](<{event['label_url']}>)",
        "",
        "## Recommendation",
        "",
        proposal["rationale"],
        "",
        "## Proposed changes",
        "",
        f"- Fields affected: {', '.join(f'`{field}`' for field in changed_fields) or 'none'}",
        "",
    ]
    for field in changed_fields:
        old_value = existing.get(field)
        new_value = proposed.get(field)
        lines.extend([f"### `{field}`", ""])
        if isinstance(old_value, str) and isinstance(new_value, str):
            phrases = changed_phrases(old_value, new_value)
            lines.extend(phrase_change_markdown(change) for change in phrases)
            lines.append("")
        lines.extend(["**Old**", "", *quote_value(old_value), ""])
        lines.extend(["**Proposed**", "", *quote_value(new_value), ""])

    baseline_label = baseline_label_date or "curated baseline label"
    latest_label = latest_label_date or "latest label"
    lines.extend(
        [
            "## Sources and artifacts",
            "",
            *(
                [f"- [Baseline FDA label PDF — {baseline_label}](<{baseline_label_pdf_path}>)"]
                if baseline_label_pdf_path is not None
                else [f"- [Baseline FDA label — {baseline_label}](<{baseline_label_url}>)"]
            ),
            *(
                [f"- [Baseline FDA label Markdown](<{baseline_label_markdown_path}>)"]
                if baseline_label_markdown_path is not None
                else []
            ),
            *(
                [f"- [Latest FDA label PDF — {latest_label}](<{latest_label_pdf_path}>)"]
                if latest_label_pdf_path is not None
                else [f"- [Latest FDA label — {latest_label}](<{latest_label_url}>)"]
            ),
            *(
                [f"- [Latest FDA label Markdown](<{latest_label_markdown_path}>)"]
                if latest_label_markdown_path is not None
                else []
            ),
            *(
                [f"- [Indications and Usage changelog](<{changelog_markdown_path}>)"]
                if changelog_markdown_path is not None
                else []
            ),
            f"- [Revision assessment JSON](<{assessment_path}>)",
            f"- [Indication matching JSON](<{reconciliation_path}>)",
            f"- [Revision proposals JSON](<{proposals_path}>)",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    work_dir = args.work_dir.resolve()
    intermediate = work_dir / "intermediate"
    assessment_path = intermediate / "revision-assessment.json"
    proposals_path = intermediate / "revision-proposals.json"
    reconciliation_path = intermediate / "indication-reconciliation.json"
    review_dir = work_dir / "review" / "revisions"

    if assessment_path.exists() and not args.overwrite:
        result = load_json_object(assessment_path, "Revision assessment artifact")
        diff_hunks = result.get("diff_hunks")
        if not isinstance(diff_hunks, list):
            raise ValueError("Revision assessment must contain label changes")
    else:
        existing = load_existing_indications(
            args.existing_indications_json.resolve(), args.document_id
        )
        pair = load_section_pair_from_cache(
            args.section_cache_json.resolve(),
            baseline_label_url=args.baseline_label_url,
            latest_label_url=args.latest_label_url,
        )
        diff_hunks = build_section_diff_hunks(
            pair["baseline_section"],
            pair["latest_section"],
            context_blocks=args.context_blocks,
        )
        result = identify_revised_indications(
            existing,
            diff_hunks,
            model=args.assessment_model,
            max_tokens=args.assessment_max_tokens,
        )
        result.update(
            {
                "document_id": args.document_id,
                "baseline_label_url": pair["baseline_label_url"],
                "latest_label_url": pair["latest_label_url"],
                "diff_hunks": diff_hunks,
            }
        )
        write_json_atomic(assessment_path, result)

    if not result.get("verified"):
        raise ValueError("Revision assessment must be verified before review generation")
    revised = [
        item for item in result.get("assessments") or [] if item.get("status") == "revised"
    ]

    reconciliation = load_json_object(
        reconciliation_path, "Indication matching artifact"
    )
    matched_latest_by_id: dict[str, dict[str, Any]] = {}
    for mapping in reconciliation.get("mappings") or []:
        indication_id = mapping.get("existing_indication_id")
        latest = mapping.get("latest_indication")
        if mapping.get("classification") == "matched" and isinstance(latest, dict):
            if indication_id in matched_latest_by_id:
                raise ValueError(f"Multiple latest indications matched {indication_id}")
            matched_latest_by_id[indication_id] = latest
    missing_latest = [
        item["existing_indication_id"]
        for item in revised
        if item["existing_indication_id"] not in matched_latest_by_id
    ]
    if missing_latest:
        raise ValueError(
            "Flagged revisions require matched latest-label indications: "
            + ", ".join(missing_latest)
        )

    changelog_payload = load_changelog_payload(args.changelog_json.resolve())
    bounded = bounded_changelog(
        changelog_payload,
        args.baseline_label_date,
        args.latest_label_date,
    )
    bounded_changelog_markdown = build_section1_changelog_markdown(bounded)
    if proposals_path.exists() and not args.overwrite:
        proposal_payload = load_json_object(
            proposals_path, "Revision proposal artifact"
        )
        proposals = proposal_payload.get("proposals")
        if not isinstance(proposals, list):
            raise ValueError("Revision proposal artifact must contain proposals")
    else:
        proposals = []
        for item in revised:
            response = review_revised_indication(
                item["existing_indication"],
                matched_latest_by_id[item["existing_indication_id"]],
                item,
                diff_hunks,
                bounded_changelog_markdown,
                model=args.review_model,
                max_tokens=args.review_max_tokens,
            )
            event_number = response["revision_event_number"]
            if event_number < 1 or event_number > len(bounded["events"]):
                raise ValueError(f"Revision selected nonexistent changelog event {event_number}")
            event = bounded["events"][event_number - 1]
            if event.get("date", "") <= args.baseline_label_date:
                raise ValueError("Revision event must be later than the curated baseline label")
            if not isinstance(event.get("label_url"), str):
                raise ValueError("Revision event must provide an FDA label URL")
            proposed = {
                **item["existing_indication"],
                **response["proposed_fields"],
                "initial_approval_date": event["date"],
                "initial_approval_url": event["label_url"],
            }
            proposals.append(
                {
                    "existing_indication_id": item["existing_indication_id"],
                    "rationale": response["rationale"],
                    "revision_event_number": event_number,
                    "revision_event": event,
                    "proposed_indication": proposed,
                }
            )
        proposal_payload = {
            "document_id": args.document_id,
            "assessment_artifact": str(assessment_path),
            "proposals": proposals,
        }
        write_json_atomic(proposals_path, proposal_payload)

    proposals_by_id = {
        item.get("existing_indication_id"): item
        for item in proposals
    }
    baseline_pdf, baseline_markdown = local_label_artifacts(
        work_dir, args.baseline_label_url
    )
    latest_pdf, latest_markdown = local_label_artifacts(
        work_dir, args.latest_label_url
    )
    changelog_markdown = args.changelog_json.resolve().with_suffix(".md")
    if not changelog_markdown.is_file():
        changelog_markdown = None
    review_paths = []
    for item in revised:
        indication_id = item["existing_indication_id"]
        proposal = proposals_by_id.get(indication_id)
        if not isinstance(proposal, dict):
            raise ValueError(f"No revision proposal exists for {indication_id}")
        path = review_dir / f"{slugify(indication_id)}.md"
        markdown = revision_markdown(
            item,
            proposal,
            baseline_label_url=args.baseline_label_url,
            latest_label_url=args.latest_label_url,
            baseline_label_date=args.baseline_label_date,
            latest_label_date=args.latest_label_date,
            assessment_path=assessment_path,
            proposals_path=proposals_path,
            reconciliation_path=reconciliation_path,
            baseline_label_pdf_path=baseline_pdf,
            baseline_label_markdown_path=baseline_markdown,
            latest_label_pdf_path=latest_pdf,
            latest_label_markdown_path=latest_markdown,
            changelog_markdown_path=changelog_markdown,
        )
        if path.exists() and not args.overwrite:
            if path.read_text(encoding="utf-8") != markdown:
                raise FileExistsError(
                    f"Revision review exists with different content: {path}"
                )
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(markdown, encoding="utf-8")
        review_paths.append(path)

    unchanged = sum(
        item.get("status") == "not_revised" for item in result.get("assessments") or []
    )
    print(f"Flagged revised indications: {len(revised)}")
    print(f"Unchanged indications omitted from review: {unchanged}")
    if not review_paths:
        print("Revision reviews: none")
    for path in review_paths:
        print(f"Revision review: {path}")
    if revised:
        print("Accept or edit each revision before assembling revised indications")
    return 0


def main() -> int:
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
