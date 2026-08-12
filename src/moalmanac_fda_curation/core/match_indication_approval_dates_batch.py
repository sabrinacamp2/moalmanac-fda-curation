#!/usr/bin/env python3
"""Match all FDA indications to Section 1 changelog events in one Claude call.

This standalone experiment is the batched counterpart to
``match_indication_approval_dates_from_changelog.py``. It sends the changelog
once, requires one result per indexed indication, and applies the existing
deterministic event/date/type/quote verification to every returned match.

Example:
    python match_indication_approval_dates_batch.py \
      --indication-fields-json outputs/Keytruda-bla125514/intermediate/Keytruda-BLA125514-claude_chunked_indication_fields.json \
      --changelog-json outputs/Keytruda-bla125514/intermediate/section1-changelogs/Keytruda-bla125514-section1-changelog.json
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .build_section1_changelogs import build_section1_changelog_markdown
from .match_indication_approval_dates_from_changelog import (
    event_by_number,
    load_changelog_payload,
    load_chunked_indication_fields,
    pydantic_to_dict,
    source_chunk_text_by_index,
    target_fields_block,
    verify_llm_changelog_match,
)
from .artifacts import file_sha256, write_json_atomic

DEFAULT_MODEL = "claude-sonnet-4-5"
DEFAULT_MAX_TOKENS = 8000


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for one batch changelog-matching run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--indication-fields-json",
        type=Path,
        required=True,
        help="Upstream *-claude_chunked_indication_fields.json artifact.",
    )
    parser.add_argument(
        "--changelog-json",
        type=Path,
        required=True,
        help="Section 1 changelog JSON artifact.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional output path. Defaults beside the indication-fields JSON.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Claude model ID. Defaults to {DEFAULT_MODEL}.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help=f"Maximum Claude output tokens. Defaults to {DEFAULT_MAX_TOKENS}.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Rewrite the output when it already exists.",
    )
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    """Resolve a CLI path relative to the current working directory."""
    return path if path.is_absolute() else Path.cwd() / path


def default_output_path(indication_fields_path: Path) -> Path:
    """Build the standard batch-match output path."""
    suffix = "-claude_chunked_indication_fields.json"
    if indication_fields_path.name.endswith(suffix):
        stem = indication_fields_path.name[: -len(suffix)]
    else:
        stem = indication_fields_path.stem
    return indication_fields_path.with_name(
        f"{stem}-llm_changelog_approval_date_batch_matches.json"
    )


def indexed_indication_inputs(
    indications: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return compact indication inputs with stable indexes."""
    return [
        {
            "indication_index": index,
            "indication": indication["indication"],
            "structured_fields": target_fields_block(indication),
        }
        for index, indication in enumerate(indications)
    ]


def build_batch_changelog_match_prompt(
    indications: list[dict[str, Any]],
    changelog_markdown: str,
) -> str:
    """Build one prompt that matches every indication to the changelog."""
    return f"""
You are matching current FDA indications to a Section 1 changelog.

For every indexed target indication, identify the earliest changelog event
whose After text fully supports the indication.

Strict matching rules:
- Use only the target indications, structured fields, and changelog below.
- A match requires the event After text to contain or unambiguously preserve
  every clinically meaningful qualifier in the target indication.
- Clinically meaningful qualifiers include adult/pediatric population, age
  group, disease stage, resectability, line of therapy, biomarker status,
  companion diagnostic language, therapeutic regimen, combination partners,
  prior-treatment requirements, limitations of use, and accelerated/full
  approval conditions when relevant.
- If an earlier event introduces the disease or regimen but a later event adds
  a qualifier from the current target indication, choose the later event.
- If the target says "adult patients" and an earlier event says only
  "patients", do not choose the earlier event unless that event establishes
  the adult population.
- For replace events, compare Before and After. Choose the event only if the
  After text is the first full match.
- Treat an initial event as the baseline Section 1 text from the application's
  first usable approved label.
- Prefer exact wording matches, but allow formatting differences or
  abbreviation expansion when all qualifiers are preserved.
- Return status "unresolved" when the changelog lacks enough evidence.
- Do not infer from outside knowledge.
- Return exactly one result for every indication_index, in input order. Never
  duplicate, omit, or invent an indication_index.
- Keep all explanation fields brief.

For each result return:
- indication_index
- status: "matched" or "unresolved"
- changelog_event_number
- selection_reason
- why_earlier_events_are_incomplete
- missing_or_uncertain_details

Do not return the event date, URL, change type, Before text, or After text.
Those fields will be populated deterministically from changelog_event_number.

Target indications:
{json.dumps(indexed_indication_inputs(indications), indent=2)}

Changelog Markdown:
{changelog_markdown}
""".strip()


def call_claude_for_batch_changelog_matches(
    prompt: str,
    model: str,
    max_tokens: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Ask Claude to match every indication in one structured response."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Export it before running this script."
        )

    try:
        from anthropic import Anthropic
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise ImportError(
            "Install required packages, e.g. `pip install anthropic pydantic`"
        ) from exc

    class IndexedChangelogEventMatch(BaseModel):
        indication_index: int
        status: str = Field(description="matched or unresolved")
        changelog_event_number: int | None = None
        selection_reason: str
        why_earlier_events_are_incomplete: str | None = None
        missing_or_uncertain_details: list[str] = Field(default_factory=list)

    class BatchChangelogMatchResponse(BaseModel):
        matches: list[IndexedChangelogEventMatch]

    if hasattr(BatchChangelogMatchResponse, "model_rebuild"):
        BatchChangelogMatchResponse.model_rebuild()
    else:
        BatchChangelogMatchResponse.update_forward_refs(
            IndexedChangelogEventMatch=IndexedChangelogEventMatch
        )

    client = Anthropic()
    response = client.messages.parse(
        model=model,
        max_tokens=max_tokens,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
        output_format=BatchChangelogMatchResponse,
    )
    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
    return (
        [pydantic_to_dict(match) for match in response.parsed_output.matches],
        usage,
    )


def validate_batch_indexes(
    matches: list[dict[str, Any]],
    indication_count: int,
) -> list[dict[str, Any]]:
    """Require exactly one result for every expected indication index."""
    expected_indexes = set(range(indication_count))
    returned_indexes = [match.get("indication_index") for match in matches]
    duplicate_indexes = sorted(
        {
            index
            for index in returned_indexes
            if returned_indexes.count(index) > 1
        }
    )
    if duplicate_indexes:
        raise ValueError(f"Claude returned duplicate indexes: {duplicate_indexes}")

    returned_index_set = set(returned_indexes)
    missing_indexes = sorted(expected_indexes - returned_index_set)
    unexpected_indexes = sorted(returned_index_set - expected_indexes)
    if missing_indexes or unexpected_indexes:
        raise ValueError(
            "Claude returned an incomplete indication mapping: "
            f"missing={missing_indexes}, unexpected={unexpected_indexes}"
        )

    invalid_statuses = [
        (match["indication_index"], match.get("status"))
        for match in matches
        if match.get("status") not in {"matched", "unresolved"}
    ]
    if invalid_statuses:
        raise ValueError(f"Claude returned invalid statuses: {invalid_statuses}")

    invalid_event_numbers = [
        (match["indication_index"], match.get("changelog_event_number"))
        for match in matches
        if (
            match["status"] == "matched"
            and not isinstance(match.get("changelog_event_number"), int)
        )
        or (
            match["status"] == "unresolved"
            and match.get("changelog_event_number") is not None
        )
    ]
    if invalid_event_numbers:
        raise ValueError(
            "Claude returned event numbers inconsistent with status: "
            f"{invalid_event_numbers}"
        )

    return sorted(matches, key=lambda match: match["indication_index"])


def materialize_verified_results(
    matches: list[dict[str, Any]],
    chunked_indications: dict[str, Any],
    changelog_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach source inputs and deterministic verification to each match."""
    indications = chunked_indications["indications"]
    source_chunks = source_chunk_text_by_index(chunked_indications)
    results = []
    for raw_selection in validate_batch_indexes(matches, len(indications)):
        selection = dict(raw_selection)
        indication_index = selection.pop("indication_index")
        indication = indications[indication_index]
        matched_event = None
        if selection["status"] == "matched":
            matched_event = event_by_number(
                changelog_events,
                selection.get("changelog_event_number"),
            )
            if matched_event is None:
                raise ValueError(
                    f"Indication {indication_index} selected nonexistent changelog "
                    f"event {selection.get('changelog_event_number')}"
                )

        materialized_match = {
            "status": selection["status"],
            "approval_date_candidate": (
                matched_event["date"] if matched_event is not None else None
            ),
            "changelog_event_number": selection.get("changelog_event_number"),
            "change_type": (
                matched_event["change_type"] if matched_event is not None else None
            ),
            "matched_after_quote": (
                matched_event["after_text"] if matched_event is not None else None
            ),
            "matched_before_quote": (
                matched_event.get("before_text") if matched_event is not None else None
            ),
            "why_this_event_is_full_match": selection["selection_reason"],
            "why_earlier_events_are_incomplete": selection.get(
                "why_earlier_events_are_incomplete"
            ),
            "missing_or_uncertain_details": selection.get(
                "missing_or_uncertain_details", []
            ),
        }
        results.append(
            {
                "indication_index": indication_index,
                "indication": indication,
                "source_chunk_text": source_chunks.get(
                    indication["source_chunk_index"]
                ),
                "llm_selection": selection,
                "materialized_match": materialized_match,
                "verification": verify_llm_changelog_match(
                    materialized_match,
                    changelog_events,
                ),
            }
        )
    return results


def main() -> int:
    """Run one full-label batch changelog-matching experiment."""
    args = parse_args()
    indication_fields_path = resolve_path(args.indication_fields_json)
    changelog_json_path = resolve_path(args.changelog_json)
    output_path = (
        resolve_path(args.output)
        if args.output
        else default_output_path(indication_fields_path)
    )
    if output_path.exists() and not args.overwrite:
        raise FileExistsError(
            f"{output_path} already exists. Use --overwrite to rewrite it."
        )

    chunked_indications = load_chunked_indication_fields(indication_fields_path)
    changelog_payload = load_changelog_payload(changelog_json_path)
    changelog_markdown = build_section1_changelog_markdown(changelog_payload)
    indications = chunked_indications["indications"]
    prompt = build_batch_changelog_match_prompt(indications, changelog_markdown)

    raw_matches, usage = call_claude_for_batch_changelog_matches(
        prompt=prompt,
        model=args.model,
        max_tokens=args.max_tokens,
    )
    results = materialize_verified_results(
        matches=raw_matches,
        chunked_indications=chunked_indications,
        changelog_events=changelog_payload["events"],
    )
    output = {
        "model": args.model,
        "usage": usage,
        "indication_count": len(indications),
        "changelog_event_count": len(changelog_payload["events"]),
        "changelog_chars": len(changelog_markdown),
        "indication_fields_sha256": file_sha256(indication_fields_path),
        "changelog_json_sha256": file_sha256(changelog_json_path),
        "results": results,
    }
    write_json_atomic(output_path, output)
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
