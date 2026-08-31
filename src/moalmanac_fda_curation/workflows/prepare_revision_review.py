"""Assess revisions and create Markdown reviews only for flagged indications."""

from __future__ import annotations

import argparse
import copy
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
from ..core.propose_revised_indication import (
    DEFAULT_MODEL as PROPOSAL_MODEL,
    propose_revised_indication,
)
from ..core.match_indication_approval_dates_from_changelog import (
    DEFAULT_MAX_TOKENS as DATE_MAX_TOKENS,
    DEFAULT_MODEL as DATE_MODEL,
    build_changelog_approval_date_matches,
    load_changelog_payload,
)


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
    parser.add_argument("--proposal-model", default=PROPOSAL_MODEL)
    parser.add_argument("--date-model", default=DATE_MODEL)
    parser.add_argument("--assessment-max-tokens", type=int, default=8000)
    parser.add_argument("--proposal-max-tokens", type=int, default=3000)
    parser.add_argument("--date-max-tokens", type=int, default=DATE_MAX_TOKENS)
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


def revision_date_matches(
    revised: list[dict[str, Any]],
    proposals: list[dict[str, Any]],
    changelog_payload: dict[str, Any],
    *,
    baseline_date: str,
    latest_date: str,
    model: str,
    max_tokens: int,
) -> list[dict[str, Any]]:
    """Run the existing indication matcher over the bounded changelog."""
    proposal_by_id = {
        proposal["existing_indication_id"]: proposal for proposal in proposals
    }
    indications = []
    for item in revised:
        indication_id = item["existing_indication_id"]
        proposal = proposal_by_id.get(indication_id)
        if proposal is None:
            raise ValueError(f"No revision proposal exists for {indication_id}")
        indications.append(
            {
                **proposal["proposed_indication"],
                "source_chunk_index": 0,
            }
        )
    bounded = bounded_changelog(changelog_payload, baseline_date, latest_date)
    chunked = {
        "source_chunks": [
            {
                "source_chunk_index": 0,
                "source_chunk_text": "Revision proposal generated from the label diff.",
            }
        ],
        "indications": indications,
    }
    return build_changelog_approval_date_matches(
        chunked_indications=chunked,
        changelog_markdown=build_section1_changelog_markdown(bounded),
        changelog_payload=bounded,
        model=model,
        max_tokens=max_tokens,
        requested_indexes=None,
    )


def assemble_revision_candidates(
    revised: list[dict[str, Any]],
    proposals: list[dict[str, Any]],
    date_matches: list[dict[str, Any]],
    *,
    baseline_date: str,
) -> list[dict[str, Any]]:
    """Apply verified later-event provenance to full proposed indications."""
    if len(date_matches) != len(revised):
        raise ValueError(
            "Revision approval evidence must contain one result per revised indication"
        )
    proposals_by_id = {
        proposal["existing_indication_id"]: proposal for proposal in proposals
    }
    output = []
    for index, item in enumerate(revised):
        indication_id = item["existing_indication_id"]
        proposal = proposals_by_id[indication_id]
        date_match = date_matches[index]
        matched_indication = date_match.get("indication") or {}
        if matched_indication.get("id") not in {None, indication_id}:
            raise ValueError(
                f"Revision approval evidence {index} targets "
                f"{matched_indication.get('id')}, not {indication_id}"
            )
        verification = date_match.get("verification") or {}
        event = verification.get("matched_event") or {}
        resolved = bool(
            verification.get("verified")
            and event
            and isinstance(event.get("date"), str)
            and event["date"] > baseline_date
            and isinstance(event.get("label_url"), str)
        )
        proposed_indication = copy.deepcopy(proposal["proposed_indication"])
        if resolved:
            proposed_indication["initial_approval_date"] = event["date"]
            proposed_indication["initial_approval_url"] = event["label_url"]
        output.append(
            {
                "existing_indication_id": indication_id,
                "complete": resolved,
                "proposed_indication": proposed_indication,
                "field_changes": proposal.get("changes") or {},
                "date_match": date_match,
            }
        )
    return output


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
    baseline_label_pdf_path: Path | None = None,
    baseline_label_markdown_path: Path | None = None,
    latest_label_pdf_path: Path | None = None,
    latest_label_markdown_path: Path | None = None,
    changelog_markdown_path: Path | None = None,
    candidate: dict[str, Any] | None = None,
    candidates_path: Path | None = None,
) -> str:
    existing = assessment["existing_indication"]
    changes = proposal.get("changes") or {}
    display_name = existing.get("raw_cancer_type") or assessment["existing_indication_id"]
    lines = [
        f"# Revision review — {display_name}",
        "",
        f"- Indication ID: `{assessment['existing_indication_id']}`",
        "",
        "## Result",
        "",
        f"- MOAlmanac update proposed: {'yes' if changes else 'no'}",
        f"- Fields affected: {', '.join(f'`{field}`' for field in changes) if changes else 'none'}",
        "- Label changes: "
        + "; ".join(assessment.get("changes") or ["Not provided"]),
    ]
    if not changes:
        lines.extend(
            [
                "",
                "The FDA label changed, but the changed wording is not represented in",
                "this MOAlmanac indication record.",
                "",
            ]
        )
    else:
        lines.extend(["", "## Proposed field changes", ""])
    for field, new_value in changes.items():
        lines.extend([f"### `{field}`", ""])
        old_value = existing.get(field)
        field_phrases = (
            changed_phrases(old_value, new_value)
            if isinstance(old_value, str) and isinstance(new_value, str)
            else []
        )
        if field_phrases:
            lines.extend(
                [
                    "**Word changes (deterministic)**",
                    "",
                    *(phrase_change_markdown(phrase) for phrase in field_phrases),
                    "",
                ]
            )
        lines.extend(["**Old value**", "", *quote_value(old_value), ""])
        lines.extend(["**New value**", "", *quote_value(new_value), ""])

    revision_event: dict[str, Any] = {}
    if candidate is not None:
        revision_event = (
            ((candidate.get("date_match") or {}).get("verification") or {}).get(
                "matched_event"
            )
            or {}
        )

    original_date = existing.get("initial_approval_date") or "Not available"
    original_url = existing.get("initial_approval_url")
    original_display = f"[{original_date}](<{original_url}>)" if original_url else original_date
    revision_date = revision_event.get("date")
    revision_url = revision_event.get("label_url")
    revision_display = (
        f"[{revision_date}](<{revision_url}>)"
        if revision_date and revision_url
        else "Unresolved"
    )
    lines.extend(
        [
            "## Dates",
            "",
            f"- Original indication approval: {original_display}",
            f"- Revised wording first appeared: {revision_display}",
            "",
        ]
    )

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
            f"- [Revision proposal JSON](<{proposals_path}>)",
            *(
                [f"- [Full proposed revision records](<{candidates_path}>)"]
                if candidates_path is not None
                else []
            ),
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    work_dir = args.work_dir.resolve()
    intermediate = work_dir / "intermediate"
    assessment_path = intermediate / "revision-assessment.json"
    proposals_path = intermediate / "revision-proposals.json"
    date_matches_path = intermediate / "revision-approval-evidence.json"
    candidates_path = intermediate / "revision-indications.proposal.json"
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

    if proposals_path.exists() and not args.overwrite:
        proposal_payload = load_json_object(
            proposals_path, "Revision proposal artifact"
        )
        proposals = proposal_payload.get("proposals")
        if not isinstance(proposals, list):
            raise ValueError("Revision proposal artifact must contain proposals")
    else:
        proposals = [
            propose_revised_indication(
                item["existing_indication"],
                item,
                diff_hunks,
                model=args.proposal_model,
                max_tokens=args.proposal_max_tokens,
            )
            for item in revised
        ]
        proposal_payload = {
            "document_id": args.document_id,
            "assessment_artifact": str(assessment_path),
            "proposals": proposals,
        }
        write_json_atomic(proposals_path, proposal_payload)

    proposals_by_id = {
        proposal.get("existing_indication_id"): proposal for proposal in proposals
    }
    if not revised:
        date_matches = []
        write_json_atomic(date_matches_path, date_matches)
    elif date_matches_path.exists() and not args.overwrite:
        date_matches_payload = json.loads(date_matches_path.read_text(encoding="utf-8"))
        if not isinstance(date_matches_payload, list):
            raise ValueError("Revision approval evidence must contain a JSON list")
        date_matches = date_matches_payload
    else:
        date_matches = revision_date_matches(
            revised,
            proposals,
            load_changelog_payload(args.changelog_json.resolve()),
            baseline_date=args.baseline_label_date,
            latest_date=args.latest_label_date,
            model=args.date_model,
            max_tokens=args.date_max_tokens,
        )
        write_json_atomic(date_matches_path, date_matches)

    candidates = assemble_revision_candidates(
        revised,
        proposals,
        date_matches,
        baseline_date=args.baseline_label_date,
    )
    complete_indications = [
        candidate["proposed_indication"]
        for candidate in candidates
        if candidate["complete"]
    ]
    if candidates_path.exists() and not args.overwrite:
        existing_candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
        if existing_candidates != complete_indications:
            raise FileExistsError(
                f"Revision indication proposals differ from {candidates_path}; "
                "use --overwrite after confirming regeneration"
            )
    else:
        write_json_atomic(candidates_path, complete_indications)
    candidates_by_id = {
        candidate["existing_indication_id"]: candidate for candidate in candidates
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
        if proposal is None:
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
            baseline_label_pdf_path=baseline_pdf,
            baseline_label_markdown_path=baseline_markdown,
            latest_label_pdf_path=latest_pdf,
            latest_label_markdown_path=latest_markdown,
            changelog_markdown_path=changelog_markdown,
            candidate=candidates_by_id[indication_id],
            candidates_path=candidates_path,
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
    unresolved = [
        item["existing_indication_id"] for item in candidates if not item["complete"]
    ]
    if unresolved:
        print("Unresolved revision approval evidence: " + ", ".join(unresolved))
    if complete_indications:
        print(f"Full proposed revision records: {candidates_path}")
    return 0


def main() -> int:
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
