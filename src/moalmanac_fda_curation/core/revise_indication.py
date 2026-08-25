"""Notebook-friendly helpers for revising one indication from label changes.

The functions in this module deliberately separate detection from proposal.  A
curator can inspect the selected changelog events before spending another LLM
call on a JSON patch, and no function writes back to moalmanac-db.
"""

from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from .artifacts import load_document_artifact, load_json_object, resolve_document_application_number
from .build_section1_changelogs import build_changelog

DEFAULT_MODEL = "claude-sonnet-4-5"
REVISION_FIELDS = frozenset(
    {"indication", "description", "raw_biomarkers", "raw_cancer_type", "raw_therapeutics"}
)


class UpdateAssessment(BaseModel):
    """Structured LLM judgment about post-curation changelog events."""

    status: Literal["updated", "not_updated", "uncertain"]
    relevant_event_numbers: list[int] = Field(default_factory=list)
    scoped_evidence: list["TargetEventSpan"] = Field(default_factory=list)
    what_changed: list[str] = Field(default_factory=list)
    reasoning: str
    uncertainties: list[str] = Field(default_factory=list)


class TargetEventSpan(BaseModel):
    """Exact event excerpts scoped to the one indication under review."""

    event_number: int
    target_before_quote: str | None = None
    target_after_quote: str
    target_change: str


class FieldUpdate(BaseModel):
    """One proposed replacement value for an indication field."""

    field: Literal[
        "indication",
        "description",
        "raw_biomarkers",
        "raw_cancer_type",
        "raw_therapeutics",
    ]
    new_value: str | None
    reason: str
    supporting_event_numbers: list[int]


class RevisionProposal(BaseModel):
    """Structured, reviewable patch proposed by the LLM."""

    updates: list[FieldUpdate] = Field(default_factory=list)
    summary: str
    uncertainties: list[str] = Field(default_factory=list)


def refresh_changelog(document_json: Path | str, work_dir: Path | str) -> dict[str, Any]:
    """Refresh a label changelog and return its paths and parsed JSON payload."""
    document_path = Path(document_json).resolve()
    work_path = Path(work_dir).resolve()
    document = load_document_artifact(document_path)
    brand = document["drug_name_brand"]
    application = resolve_document_application_number(document)
    markdown_path, json_path = build_changelog(
        brand_name=brand,
        application_number=application,
        # Revision discovery must not truncate at the label URL stored on the
        # existing document; later approved labels are exactly what we seek.
        current_label_url=None,
        output_dir=work_path / "intermediate" / "section1-changelogs",
        cache_dir=work_path / "intermediate" / "section1-cache",
        historical_labels_dir=work_path / "historical-labels",
    )
    return {
        "markdown_path": markdown_path,
        "json_path": json_path,
        "changelog": load_json_object(json_path, "Section 1 changelog"),
    }


def events_since(
    changelog: dict[str, Any], last_curation_date: str
) -> list[dict[str, Any]]:
    """Return events strictly after an ISO curation date, in changelog order."""
    cutoff = date.fromisoformat(last_curation_date)
    events = changelog.get("events")
    if not isinstance(events, list):
        raise ValueError("Changelog must contain an 'events' list")
    result = []
    for event in events:
        if not isinstance(event, dict) or not isinstance(event.get("date"), str):
            raise ValueError("Every changelog event must be an object with an ISO date")
        if date.fromisoformat(event["date"]) > cutoff:
            result.append(event)
    return result


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


def build_assessment_prompt(
    indication: dict[str, Any], candidate_events: list[dict[str, Any]]
) -> str:
    """Build the evidence-limited prompt for the update-detection pass."""
    return f"""# Task

Decide whether later versions of the label's Indications and Usage section
clinically changed this existing MOAlmanac FDA indication.

# Target indication

```json
{_json(indication)}
```

# Changelog events after the last curation

```json
{_json(candidate_events)}
```

# Clinically meaningful changes

Consider changes to:

- population or age;
- disease, stage, or resectability;
- line of therapy or prior-treatment requirements;
- biomarker status or required testing;
- regimen or combination partners;
- limitations of use; or
- approval conditions.

# Scope rules

- Ignore formatting-only changes.
- Ignore newly added or otherwise separate indications.
- Do not mention separate indications in `what_changed` or `reasoning`.
- Evaluate each event against the complete target indication before selecting it.
- A replacement event is relevant only when its before-text changes information
  represented in the target indication. Do not assign a change to the target merely
  because it shares a disease name, biomarker, or other partial wording.
- If an event changes a qualifier that the target does not contain, treat it as a
  separate indication unless the event text explicitly establishes that it concerns
  this target's population, disease setting, and regimen.
- Use only the supplied target and changelog evidence.
- If evidence is insufficient, return `uncertain` rather than guessing.

# Status requirements

- Return `updated` only for at least one clinically meaningful, target-specific
  change. `updated` requires nonempty `what_changed`, `relevant_event_numbers`, and
  `scoped_evidence`.
- Return `not_updated` when the only target-related events are formatting changes or
  when no event clinically changes the target. For `not_updated`, return empty
  `what_changed`, `relevant_event_numbers`, and `scoped_evidence`.
- Return `uncertain` when an event may concern the target but the supplied text cannot
  establish attribution confidently. Explain that ambiguity in `uncertainties`.
- Make `status`, `what_changed`, `reasoning`, and the selected evidence mutually
  consistent.

# Target-span requirements

For every relevant event, provide target-specific before and after quotes that:

- be copied verbatim from that event;
- be the smallest complete passages that concern the target indication; and
- exclude all text about new or separate indications."""


def build_proposal_prompt(
    indication: dict[str, Any], scoped_evidence: list[dict[str, Any]]
) -> str:
    """Build the evidence-limited prompt for the JSON-patch pass."""
    return f"""# Task

Propose the minimal revision needed for this existing MOAlmanac indication to
reflect the verified target-specific evidence.

# Existing indication

```json
{_json(indication)}
```

# Verified target-specific changelog evidence

```json
{_json(scoped_evidence)}
```

# Scope rules

- Never merge a newly added or separate indication into this record.
- Use only the scoped before and after quotes.
- The evidence is chronological. Synthesize the final form of the indication;
  when evidence changes the same wording more than once, the later span supersedes
  the earlier span.
- Do not add facts from general knowledge.
- Preserve the existing writing style where possible.
- Omit unchanged fields.
- Report uncertainty instead of guessing.

# Evidence requirements

Every proposed field replacement must:

- cite one or more supplied event numbers in `supporting_event_numbers`; and
- explain the target-specific reason for the change."""


def _call_claude(prompt: str, output_format: type[BaseModel], model: str, max_tokens: int) -> dict[str, Any]:
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
        output_format=output_format,
    )
    parsed = response.parsed_output
    return parsed.model_dump() if hasattr(parsed, "model_dump") else parsed.dict()


def _event_map(events: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    mapping = {}
    for event in events:
        number = event.get("event_number")
        if not isinstance(number, int) or number in mapping:
            raise ValueError("Changelog event numbers must be unique integers")
        mapping[number] = event
    return mapping


def _format_normalized(text: str) -> str:
    """Normalize PDF bullet variants and whitespace for formatting-only checks."""
    return re.sub(r"\s+", "", text.translate(str.maketrans({"": "•", "": "•"})))


def assess_update(
    indication: dict[str, Any],
    candidate_events: list[dict[str, Any]],
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 8000,
    llm: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assess an update and deterministically hydrate selected event evidence."""
    if not candidate_events:
        return {
            "assessment": UpdateAssessment(
                status="not_updated",
                reasoning="No changelog events occurred after the curation cutoff.",
            ).model_dump(),
            "scoped_evidence": [],
            "relevant_events": [],
            "verified": True,
        }
    prompt = build_assessment_prompt(indication, candidate_events)
    raw = llm(prompt) if llm else _call_claude(prompt, UpdateAssessment, model, max_tokens)
    assessment = UpdateAssessment.model_validate(raw).model_dump()
    by_number = _event_map(candidate_events)
    requested = assessment["relevant_event_numbers"]
    missing = [number for number in requested if number not in by_number]
    errors = [f"Unknown event number: {number}" for number in missing]
    scoped_evidence = []
    scoped_numbers = []
    for span in assessment["scoped_evidence"]:
        number = span["event_number"]
        scoped_numbers.append(number)
        event = by_number.get(number)
        if event is None:
            errors.append(f"Scoped evidence cites unknown event number: {number}")
            continue
        if number not in requested:
            errors.append(f"Scoped evidence event {number} is not listed as relevant")
            continue
        before_quote = span.get("target_before_quote")
        after_quote = span["target_after_quote"]
        if before_quote is not None and before_quote not in (event.get("before_text") or ""):
            errors.append(f"Event {number} target_before_quote is not verbatim")
            continue
        if after_quote not in event["after_text"]:
            errors.append(f"Event {number} target_after_quote is not verbatim")
            continue
        if (
            before_quote is not None
            and _format_normalized(before_quote) == _format_normalized(after_quote)
        ):
            errors.append(f"Event {number} target evidence is formatting-only")
            continue
        scoped_evidence.append(span)
    status = assessment["status"]
    if status == "updated":
        if not assessment["what_changed"]:
            errors.append("Updated assessment must describe what changed")
        if not requested:
            errors.append("Updated assessment must cite at least one relevant event")
        if not assessment["scoped_evidence"]:
            errors.append("Updated assessment must provide target-specific evidence")
        for number in requested:
            if number not in scoped_numbers:
                errors.append(f"Relevant event {number} has no target-specific evidence")
    elif status == "not_updated":
        if assessment["what_changed"]:
            errors.append("Not-updated assessment must not describe changes")
        if requested:
            errors.append("Not-updated assessment must not cite relevant events")
        if assessment["scoped_evidence"]:
            errors.append("Not-updated assessment must not provide revision evidence")
    scoped_evidence.sort(
        key=lambda span: (
            by_number[span["event_number"]]["date"],
            span["event_number"],
        )
    )
    return {
        "assessment": assessment,
        "scoped_evidence": scoped_evidence,
        "relevant_events": [by_number[number] for number in requested if number in by_number],
        "verified": not errors,
        "verification_errors": errors,
    }


def propose_revision(
    indication: dict[str, Any],
    assessment_result: dict[str, Any],
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 3000,
    llm: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Propose and deterministically apply an allow-listed patch for review."""
    if not assessment_result.get("verified"):
        raise ValueError("Assessment event references must verify before proposing changes")
    if assessment_result.get("assessment", {}).get("status") != "updated":
        raise ValueError("A revision can only be proposed for an 'updated' assessment")
    scoped_evidence = assessment_result.get("scoped_evidence") or []
    prompt = build_proposal_prompt(indication, scoped_evidence)
    raw = llm(prompt) if llm else _call_claude(prompt, RevisionProposal, model, max_tokens)
    proposal = RevisionProposal.model_validate(raw).model_dump()
    event_numbers = {item["event_number"] for item in scoped_evidence}
    relevant_by_number = _event_map(assessment_result.get("relevant_events") or [])
    errors = []
    patch: dict[str, Any] = {}
    for update in proposal["updates"]:
        unsupported = sorted(set(update["supporting_event_numbers"]) - event_numbers)
        if unsupported:
            errors.append(f"{update['field']} cites unavailable event(s): {unsupported}")
            continue
        patch[update["field"]] = update["new_value"]
    selected_events = [
        relevant_by_number[number]
        for number in event_numbers
        if number in relevant_by_number
    ]
    missing_events = sorted(event_numbers - set(relevant_by_number))
    if missing_events:
        errors.append(
            f"Scoped evidence is missing canonical event(s): {missing_events}"
        )
    approval_event = max(selected_events, key=lambda event: event["date"], default=None)
    deterministic_updates: dict[str, Any] = {}
    if approval_event is not None:
        deterministic_updates = {
            "initial_approval_date": approval_event["date"],
            "initial_approval_url": approval_event["label_url"],
        }
        patch.update(deterministic_updates)
    if errors:
        raise ValueError("; ".join(errors))
    proposed = deepcopy(indication)
    proposed.update(patch)
    return {
        "proposed_indication": proposed,
        "changes": patch,
        "source_events": [
            {
                "event_number": event["event_number"],
                "date": event["date"],
                "label_url": event["label_url"],
            }
            for event in sorted(selected_events, key=lambda event: event["date"])
        ],
        "notes": {
            "summary": proposal["summary"],
            "uncertainties": proposal["uncertainties"],
        },
    }
