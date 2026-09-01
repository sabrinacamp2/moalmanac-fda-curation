"""Propose one revised indication for curator review."""

from __future__ import annotations

import json
import os
from typing import Any, Callable

from pydantic import BaseModel

DEFAULT_MODEL = "claude-sonnet-4-5"


class RevisedFields(BaseModel):
    indication: str
    description: str
    raw_biomarkers: str
    raw_cancer_type: str
    raw_therapeutics: str


class RevisionProposalResponse(BaseModel):
    rationale: str
    proposed_fields: RevisedFields
    revision_event_number: int


def build_revision_review_prompt(
    existing_indication: dict[str, Any],
    latest_indication: dict[str, Any],
    revision_assessment: dict[str, Any],
    relevant_label_changes: list[dict[str, Any]],
    bounded_changelog: str,
) -> str:
    """Build a target-specific revised-record proposal prompt."""
    return f"""Review this existing MOAlmanac indication against its matched indication
extracted from the latest FDA label and the supplied label history.

Produce the complete current values for the five editable MOAlmanac fields. Apply newer
label revisions and add applicable current-label information omitted from the existing
record. Preserve unrelated existing description detail and existing drug-class wording.

Select the changelog event where the complete proposed record is first supported. Write
a concise rationale of at most six plain bullets. Distinguish newer label revisions from
older omissions, address corresponding description changes, and avoid priority or
importance judgments.

## Current MOAlmanac indication

{json.dumps(existing_indication, indent=2, ensure_ascii=False)}

## Matched indication extracted from the latest FDA label

{json.dumps(latest_indication, indent=2, ensure_ascii=False)}

## Changes already associated with this indication

{json.dumps(revision_assessment.get("changes") or [], indent=2, ensure_ascii=False)}

## Baseline-to-latest label changes

{json.dumps(relevant_label_changes, indent=2, ensure_ascii=False)}

## Indications and Usage changelog between the curated and latest labels

{bounded_changelog}"""


def _call_claude(prompt: str, model: str, max_tokens: int) -> dict[str, Any]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise ImportError("Install the project dependencies before calling the LLM") from exc
    response = Anthropic().messages.parse(
        model=model,
        max_tokens=max_tokens,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
        output_format=RevisionProposalResponse,
    )
    parsed = response.parsed_output
    return parsed.model_dump() if hasattr(parsed, "model_dump") else parsed.dict()


def review_revised_indication(
    existing_indication: dict[str, Any],
    latest_indication: dict[str, Any],
    revision_assessment: dict[str, Any],
    diff_hunks: list[dict[str, Any]],
    bounded_changelog: str,
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 3000,
    llm: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a complete structured proposal grounded in revision evidence."""
    if revision_assessment.get("status") != "revised":
        raise ValueError("A revision review requires a 'revised' assessment")
    if revision_assessment.get("existing_indication_id") != existing_indication.get("id"):
        raise ValueError("Revision assessment does not target the existing indication")
    hunk_ids = revision_assessment.get("relevant_hunk_ids") or []
    hunks_by_id = {hunk.get("hunk_id"): hunk for hunk in diff_hunks}
    relevant = [hunks_by_id[hunk_id] for hunk_id in hunk_ids if hunk_id in hunks_by_id]
    if len(relevant) != len(hunk_ids):
        raise ValueError("Revision assessment cites an unknown label change")
    prompt = build_revision_review_prompt(
        existing_indication,
        latest_indication,
        revision_assessment,
        relevant,
        bounded_changelog,
    )
    raw = llm(prompt) if llm else _call_claude(prompt, model, max_tokens)
    return RevisionProposalResponse.model_validate(raw).model_dump()
