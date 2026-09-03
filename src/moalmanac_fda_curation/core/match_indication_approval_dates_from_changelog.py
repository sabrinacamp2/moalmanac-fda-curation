#!/usr/bin/env python3
"""Match extracted FDA indications to Section 1 changelog approval events.

This is a downstream FDA-indication curation step. It starts from:

1. ``*-claude_chunked_indication_fields.json`` extracted indication candidates.
2. ``section1-changelogs/*-section1-changelog.md`` for LLM-readable evidence.
3. ``section1-changelogs/*-section1-changelog.json`` for deterministic
   verification.

In one call, this script asks Claude to identify the earliest changelog event
whose After text fully supports each current indication. The LLM returns only
an event number and reasoning. Dates, change types, URLs, and exact source text
are then populated deterministically from the changelog JSON.

Example:
    python match_indication_approval_dates_from_changelog.py \
      --indication-fields-json extracted-indications/Yervoy-bla125377-claude_chunked_indication_fields.json \
      --changelog-json extracted-indications/section1-changelogs/Yervoy-bla125377-section1-changelog.json
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Callable

DEFAULT_MODEL = "claude-sonnet-4-5"
DEFAULT_MAX_TOKENS = 8000

from .build_section1_changelogs import build_section1_changelog_markdown
from .artifacts import (
    file_sha256,
    load_json_object as load_workflow_json_object,
    partial_output_path,
    write_json_atomic,
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for one changelog matching run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--indication-fields-json",
        type=Path,
        required=True,
        help="Path to the upstream *-claude_chunked_indication_fields.json file.",
    )
    parser.add_argument(
        "--changelog-json",
        type=Path,
        required=True,
        help="Path to the Section 1 changelog JSON file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Optional explicit output path. If omitted, writes "
            "*-llm_changelog_approval_date_matches.json beside "
            "--indication-fields-json."
        ),
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
        help=(
            "Base maximum Claude output tokens for the batch response; the "
            "workflow raises it for very large indication sets. "
            f"Defaults to {DEFAULT_MAX_TOKENS}."
        ),
    )
    parser.add_argument(
        "--indication-index",
        type=int,
        action="append",
        help=(
            "Only match selected indication indexes. Repeat this flag to select "
            "multiple indexes. Defaults to all indications."
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


def default_output_path(indication_fields_json: Path) -> Path:
    """Infer output path beside the explicit upstream indication JSON path."""
    suffix = "-claude_chunked_indication_fields.json"
    name = indication_fields_json.name
    if name.endswith(suffix):
        stem = name[: -len(suffix)]
    else:
        stem = indication_fields_json.stem
    return indication_fields_json.with_name(
        f"{stem}-llm_changelog_approval_date_matches.json"
    )


def load_json_object(path: Path) -> dict[str, Any]:
    """Load a JSON object with a clear validation error."""
    with path.open(encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def load_chunked_indication_fields(path: Path) -> dict[str, Any]:
    """Load and validate extracted indication candidates."""
    payload = load_json_object(path)
    indications = payload.get("indications")
    source_chunks = payload.get("source_chunks")
    if not isinstance(indications, list) or not indications:
        raise ValueError(f"{path} must contain a non-empty 'indications' list")
    if not isinstance(source_chunks, list):
        raise ValueError(f"{path} must contain a 'source_chunks' list")

    for index, indication in enumerate(indications):
        if not isinstance(indication, dict):
            raise ValueError(f"indications[{index}] in {path} must be an object")
        if not isinstance(indication.get("indication"), str):
            raise ValueError(
                f"indications[{index}] in {path} must have indication text"
            )
        if not isinstance(indication.get("source_chunk_index"), int):
            raise ValueError(
                f"indications[{index}] in {path} must have source_chunk_index"
            )

    return payload


def load_changelog_payload(path: Path) -> dict[str, Any]:
    """Load and validate the compact changelog JSON payload."""
    payload = load_json_object(path)
    events = payload.get("events")
    if not isinstance(events, list):
        raise ValueError(f"{path} must contain an 'events' list")

    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError(f"events[{index}] in {path} must be an object")
        required = {"event_number", "date", "change_type", "label_url", "after_text"}
        missing = sorted(required - set(event))
        if missing:
            raise ValueError(f"events[{index}] in {path} is missing {missing}")

    return payload


def source_chunk_text_by_index(chunked_indications: dict[str, Any]) -> dict[int, str]:
    """Return source chunk text keyed by source_chunk_index for audit output."""
    chunks: dict[int, str] = {}
    for chunk in chunked_indications["source_chunks"]:
        if not isinstance(chunk, dict):
            continue
        index = chunk.get("source_chunk_index")
        text = chunk.get("source_chunk_text")
        if isinstance(index, int) and isinstance(text, str):
            chunks[index] = text
    return chunks


def selected_indication_indexes(
    indications: list[dict[str, Any]],
    requested_indexes: list[int] | None,
) -> list[int]:
    """Return the indication indexes this run should match."""
    if requested_indexes is None:
        return list(range(len(indications)))

    invalid = [
        index for index in requested_indexes if index < 0 or index >= len(indications)
    ]
    if invalid:
        raise ValueError(
            f"Invalid --indication-index value(s): {invalid}. "
            f"Valid range is 0 to {len(indications) - 1}."
        )
    return requested_indexes


def target_fields_block(indication: dict[str, Any]) -> str:
    """Render structured target fields for the LLM prompt."""
    fields = [
        ("Therapeutic(s)", indication.get("raw_therapeutics")),
        ("Cancer type", indication.get("raw_cancer_type")),
        ("Patient population", indication.get("raw_patient_population")),
        ("Biomarker(s)", indication.get("raw_biomarkers")),
    ]
    return "\n".join(f"- {label}: {value or 'not specified'}" for label, value in fields)


def build_changelog_match_prompt(
    indication: dict[str, Any],
    changelog_markdown: str,
) -> str:
    """Build the strict one-indication changelog matching prompt."""
    return f"""
You are matching one current FDA indication to a Section 1 changelog.

Task:
Identify the earliest changelog event where the target indication is fully supported.

Target indication:
{indication["indication"]}

Target structured fields:
{target_fields_block(indication)}

Strict matching rules:
- Use only the target indication, target structured fields, and changelog text below.
- A match requires the event After text to contain or unambiguously preserve every clinically meaningful qualifier in the target indication.
- Clinically meaningful qualifiers include adult/pediatric population, age group, disease stage, resectability, line of therapy, biomarker status, companion diagnostic language, therapeutic regimen, combination partners, prior-treatment requirements, limitations of use, and accelerated/full approval conditions when relevant.
- If an earlier event introduces the disease or regimen but a later event adds a qualifier from the current target indication, choose the later event.
- If the target indication says "adult patients" and an earlier event says only "patients", do not choose the earlier event unless that event itself establishes the adult population.
- If the target indication includes a biomarker, disease-stage, line-of-therapy, prior-treatment, or population qualifier that is absent from an earlier event, do not choose that earlier event.
- For replace events, compare Before and After. Choose the event only if the After text is the first full match.
- Prefer exact wording matches, but allow minor formatting differences such as line breaks, bullets, cross-references, or abbreviation expansion when all qualifiers are preserved.
- If the changelog does not contain enough evidence for a full match, return status "unresolved".
- Do not infer from outside knowledge.
- matched_after_quote and matched_before_quote must be copied exactly from the changelog when provided.

Return a structured response with these fields:
- status: "matched" or "unresolved"
- approval_date_candidate
- changelog_event_number
- change_type
- matched_after_quote
- matched_before_quote
- why_this_event_is_full_match
- why_earlier_events_are_incomplete
- missing_or_uncertain_details

Changelog Markdown:
{changelog_markdown}
""".strip()


def pydantic_to_dict(model_output: Any) -> dict[str, Any]:
    """Convert a Pydantic model to a plain dict across Pydantic versions."""
    if hasattr(model_output, "model_dump"):
        return model_output.model_dump()
    return model_output.dict()


def call_claude_for_changelog_match(
    prompt: str,
    model: str,
    max_tokens: int,
) -> dict[str, Any]:
    """Call Claude for one structured changelog event match."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Export it in your shell before running this script."
        )

    try:
        from anthropic import Anthropic
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise ImportError(
            "Install required packages, e.g. `pip install anthropic pydantic`"
        ) from exc

    class ChangelogEventMatch(BaseModel):
        status: str = Field(description="matched or unresolved")
        approval_date_candidate: str | None = Field(
            default=None,
            description="YYYY-MM-DD date from the matched changelog event",
        )
        changelog_event_number: int | None = Field(
            default=None,
            description="Matched event number from the changelog",
        )
        change_type: str | None = Field(
            default=None,
            description="initial, insert, or replace, copied from the changelog event",
        )
        matched_after_quote: str | None = Field(
            default=None,
            description="Exact quote from the matched event after/current text",
        )
        matched_before_quote: str | None = Field(
            default=None,
            description="Exact quote from the matched event before text for replace events, if relevant",
        )
        why_this_event_is_full_match: str = Field(
            description="Brief reason this event fully supports all target indication qualifiers"
        )
        why_earlier_events_are_incomplete: str | None = Field(
            default=None,
            description="Brief reason earlier similar events were not full matches",
        )
        missing_or_uncertain_details: list[str] = Field(default_factory=list)

    client = Anthropic()
    response = client.messages.parse(
        model=model,
        max_tokens=max_tokens,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
        output_format=ChangelogEventMatch,
    )
    return pydantic_to_dict(response.parsed_output)


def event_by_number(
    changelog_events: list[dict[str, Any]],
    event_number: int | None,
) -> dict[str, Any] | None:
    """Return the changelog event with the requested persistent event number."""
    if event_number is None:
        return None
    return next(
        (
            event
            for event in changelog_events
            if event.get("event_number") == event_number
        ),
        None,
    )


def quote_in_text(quote: str | None, text: str | None) -> bool:
    """Return whether an optional quote is present in optional event text."""
    if quote is None:
        return True
    return quote in (text or "")


def verify_llm_changelog_match(
    match: dict[str, Any],
    changelog_events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Verify that the LLM returned a real changelog event and exact quotes."""
    verification: dict[str, Any] = {
        "status": match.get("status"),
        "event_exists": False,
        "date_matches_event": False,
        "change_type_matches_event": False,
        "after_quote_exact_match": False,
        "before_quote_exact_match": False,
        "verified": False,
    }
    if match.get("status") != "matched":
        verification["verified"] = match.get("status") == "unresolved"
        return verification

    event = event_by_number(changelog_events, match.get("changelog_event_number"))
    if event is None:
        return verification

    verification["event_exists"] = True
    verification["date_matches_event"] = (
        match.get("approval_date_candidate") == event["date"]
    )
    verification["change_type_matches_event"] = (
        match.get("change_type") == event["change_type"]
    )
    verification["after_quote_exact_match"] = quote_in_text(
        match.get("matched_after_quote"),
        event["after_text"],
    )
    verification["before_quote_exact_match"] = quote_in_text(
        match.get("matched_before_quote"),
        event.get("before_text"),
    )
    verification["matched_event"] = event
    verification["verified"] = all(
        [
            verification["event_exists"],
            verification["date_matches_event"],
            verification["change_type_matches_event"],
            verification["after_quote_exact_match"],
            verification["before_quote_exact_match"],
        ]
    )
    return verification


def match_one_indication(
    indication_index: int,
    indication: dict[str, Any],
    source_chunks: dict[int, str],
    changelog_markdown: str,
    changelog_events: list[dict[str, Any]],
    model: str,
    max_tokens: int,
) -> dict[str, Any]:
    """Match one extracted indication to one changelog event."""
    prompt = build_changelog_match_prompt(
        indication=indication,
        changelog_markdown=changelog_markdown,
    )
    llm_match = call_claude_for_changelog_match(
        prompt=prompt,
        model=model,
        max_tokens=max_tokens,
    )
    verification = verify_llm_changelog_match(llm_match, changelog_events)
    source_chunk_index = indication["source_chunk_index"]
    return {
        "indication_index": indication_index,
        "indication": indication,
        "source_chunk_text": source_chunks.get(source_chunk_index),
        "llm_match": llm_match,
        "verification": verification,
    }


def build_changelog_approval_date_matches(
    chunked_indications: dict[str, Any],
    changelog_markdown: str,
    changelog_payload: dict[str, Any],
    model: str,
    max_tokens: int,
    requested_indexes: list[int] | None,
    initial_results: list[dict[str, Any]] | None = None,
    checkpoint: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Match all indications in one LLM call and return selected results."""
    indications = chunked_indications["indications"]
    indexes = selected_indication_indexes(indications, requested_indexes)
    results = list(initial_results or [])
    completed_indexes = {
        item["indication_index"]
        for item in results
        if isinstance(item.get("indication_index"), int)
    }
    if completed_indexes.issuperset(indexes):
        print(f"reusing {len(indexes)} completed approval-date matches")
        return [item for item in results if item["indication_index"] in indexes]

    # Imported at runtime to avoid a module cycle: the standalone experiment
    # reuses deterministic validation helpers from this production workflow.
    from .match_indication_approval_dates_batch import (
        build_batch_changelog_match_prompt,
        call_claude_for_batch_changelog_matches,
        materialize_verified_results,
    )

    selected_indications = [indications[index] for index in indexes]
    changelog_events = changelog_payload["events"]

    if len(changelog_events) == 1:
        # A single changelog event means this drug has only ever had one
        # approved label (e.g. a first-cycle NDA/BLA). That event is
        # definitionally the earliest and only candidate, and every
        # indication was extracted from that same label text, so there is
        # nothing for an LLM to adjudicate between. Skip the Claude call and
        # deterministically match every selected indication to it, reusing
        # the same hydration/verification path as the LLM branch below.
        only_event = changelog_events[0]
        print(
            f"changelog has a single event (event {only_event['event_number']}, "
            f"{only_event['change_type']}); auto-matching "
            f"{len(selected_indications)} indication(s) without a Claude call"
        )
        auto_matches = [
            {
                "indication_index": local_index,
                "status": "matched",
                "changelog_event_number": only_event["event_number"],
                "selection_reason": (
                    "Only one Section 1 changelog event exists for this drug "
                    "(the initial approved label). It is definitionally the "
                    "earliest and only event, and this indication was "
                    "extracted from that same label text."
                ),
                "why_earlier_events_are_incomplete": None,
                "missing_or_uncertain_details": [],
            }
            for local_index in range(len(selected_indications))
        ]
        selected_chunked_indications = {
            **chunked_indications,
            "indications": selected_indications,
        }
        local_results = materialize_verified_results(
            matches=auto_matches,
            chunked_indications=selected_chunked_indications,
            changelog_events=changelog_events,
        )
        auto_results = [
            {
                "indication_index": indexes[item["indication_index"]],
                "indication": item["indication"],
                "source_chunk_text": item["source_chunk_text"],
                "llm_selection": item["llm_selection"],
                "llm_match": item["materialized_match"],
                "verification": {
                    **item["verification"],
                    "auto_matched_single_event": True,
                },
            }
            for item in local_results
        ]
        if checkpoint:
            checkpoint(
                {
                    "model": None,
                    "requested_indication_indexes": indexes,
                    "results": auto_results,
                    "auto_matched_single_event": True,
                }
            )
        return auto_results

    print(f"matching {len(selected_indications)} indications in one changelog call")
    prompt = build_batch_changelog_match_prompt(
        selected_indications,
        changelog_markdown,
    )
    raw_matches, usage = call_claude_for_batch_changelog_matches(
        prompt=prompt,
        model=model,
        max_tokens=max(max_tokens, len(selected_indications) * 160),
    )
    selected_chunked_indications = {
        **chunked_indications,
        "indications": selected_indications,
    }
    local_results = materialize_verified_results(
        matches=raw_matches,
        chunked_indications=selected_chunked_indications,
        changelog_events=changelog_payload["events"],
    )
    batch_results = [
        {
            **item,
            "indication_index": indexes[item["indication_index"]],
        }
        for item in local_results
    ]
    results = [
        {
            "indication_index": item["indication_index"],
            "indication": item["indication"],
            "source_chunk_text": item["source_chunk_text"],
            "llm_selection": item["llm_selection"],
            "llm_match": item["materialized_match"],
            "verification": item["verification"],
        }
        for item in batch_results
    ]
    print(
        "batch changelog usage: "
        f"{usage['input_tokens']} input tokens, "
        f"{usage['output_tokens']} output tokens"
    )
    if checkpoint:
        checkpoint(
            {
                "model": model,
                "requested_indication_indexes": indexes,
                "results": results,
                "batch_usage": usage,
            }
        )
    return results


def main() -> int:
    """Run the CLI and write changelog approval-date matches."""
    args = parse_args()
    indication_fields_path = resolve_path(args.indication_fields_json)
    changelog_json_path = resolve_path(args.changelog_json)
    output_path = (
        resolve_path(args.output)
        if args.output
        else default_output_path(indication_fields_path)
    )
    checkpoint_path = partial_output_path(output_path)

    if output_path.exists() and not args.overwrite:
        raise FileExistsError(f"{output_path} already exists. Use --overwrite to rewrite it.")
    if args.overwrite:
        checkpoint_path.unlink(missing_ok=True)

    chunked_indications = load_chunked_indication_fields(indication_fields_path)
    changelog_payload = load_changelog_payload(changelog_json_path)
    changelog_markdown = build_section1_changelog_markdown(changelog_payload)
    requested_indexes = selected_indication_indexes(
        chunked_indications["indications"],
        args.indication_index,
    )
    checkpoint_metadata = {
        "model": args.model,
        "max_tokens": args.max_tokens,
        "requested_indication_indexes": requested_indexes,
        "indication_fields_sha256": file_sha256(indication_fields_path),
        "changelog_json_sha256": file_sha256(changelog_json_path),
    }
    initial_results: list[dict[str, Any]] = []
    if checkpoint_path.exists():
        checkpoint_payload = load_workflow_json_object(
            checkpoint_path,
            "Approval-date checkpoint",
        )
        mismatches = [
            field
            for field, expected in checkpoint_metadata.items()
            if checkpoint_payload.get(field) != expected
        ]
        if mismatches:
            raise ValueError(
                f"{checkpoint_path} does not match the current run for "
                f"{', '.join(mismatches)}. Use --overwrite to start fresh."
            )
        initial_results = checkpoint_payload.get("results", [])
        print(
            f"resuming {checkpoint_path}: "
            f"{len(initial_results)}/{len(requested_indexes)} matches complete"
        )

    matches = build_changelog_approval_date_matches(
        chunked_indications=chunked_indications,
        changelog_markdown=changelog_markdown,
        changelog_payload=changelog_payload,
        model=args.model,
        max_tokens=args.max_tokens,
        requested_indexes=args.indication_index,
        initial_results=initial_results,
        checkpoint=lambda payload: write_json_atomic(
            checkpoint_path,
            {**payload, **checkpoint_metadata},
        ),
    )

    write_json_atomic(output_path, matches)
    checkpoint_path.unlink(missing_ok=True)
    print(f"wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
