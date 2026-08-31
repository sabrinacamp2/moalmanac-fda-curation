"""Propose minimal indication patches from current-label evidence."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any, Callable, Literal

from pydantic import BaseModel

DEFAULT_MODEL = "claude-sonnet-4-5"
EDITABLE_FIELDS = (
    "indication",
    "description",
    "raw_biomarkers",
    "raw_cancer_type",
    "raw_therapeutics",
)


class RevisionFieldUpdate(BaseModel):
    """One replacement value proposed from current-label evidence."""

    field: Literal[
        "indication",
        "description",
        "raw_biomarkers",
        "raw_cancer_type",
        "raw_therapeutics",
    ]
    new_value: str | None


class RevisionProposal(BaseModel):
    """Minimal structured output from the proposal LLM."""

    updates: list[RevisionFieldUpdate]


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


def build_label_diff_revision_prompt(
    existing_indication: dict[str, Any],
    revision_assessment: dict[str, Any],
    relevant_hunks: list[dict[str, Any]],
) -> str:
    """Build a minimal proposal prompt from assessed source-label changes."""
    existing_content = {
        field: existing_indication.get(field)
        for field in EDITABLE_FIELDS
    }
    guidance = {
        "changes": revision_assessment.get("changes", []),
        "reason": revision_assessment.get("reason"),
        "relevant_hunk_ids": revision_assessment.get("relevant_hunk_ids", []),
    }
    return f"""# Task

Apply the assessed FDA label changes to this existing MOAlmanac indication.

# Existing editable fields

```json
{_json(existing_content)}
```

# Assessed changes for this indication

```json
{_json(guidance)}
```

# Source label changes

```json
{_json(relevant_hunks)}
```

# Instructions

The assessed changes are authoritative. Apply every assessed change to the
appropriate editable fields using the latest label wording. Do not decide whether
a change is important or omit it because it appears minor.

Preserve all unrelated content, including existing drug-class wording. If the
indication and description express the same affected information, update both.
If an applicable label statement containing an assessed change is missing from
the existing record, add the complete current statement to `indication` and add
corresponding language to `description`.
Return complete replacement values only for fields that change. Use only the
supplied inputs."""


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
        output_format=RevisionProposal,
    )
    parsed = response.parsed_output
    return parsed.model_dump() if hasattr(parsed, "model_dump") else parsed.dict()


def propose_revised_indication(
    existing_indication: dict[str, Any],
    revision_assessment: dict[str, Any],
    diff_hunks: list[dict[str, Any]],
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 3000,
    llm: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Propose an allow-listed patch from a verified label-diff assessment."""
    if revision_assessment.get("status") != "revised":
        raise ValueError("A label-diff proposal requires a 'revised' assessment")
    indication_id = revision_assessment.get("existing_indication_id")
    if indication_id != existing_indication.get("id"):
        raise ValueError("Revision assessment does not target the existing indication")
    hunk_ids = revision_assessment.get("relevant_hunk_ids") or []
    changes_guidance = revision_assessment.get("changes") or []
    if not hunk_ids or not changes_guidance:
        raise ValueError("A revised assessment requires label-change IDs and changes")
    hunks_by_id = {hunk.get("hunk_id"): hunk for hunk in diff_hunks}
    if None in hunks_by_id or len(hunks_by_id) != len(diff_hunks):
        raise ValueError("Label changes must have unique non-null IDs")
    unknown_hunks = [hunk_id for hunk_id in hunk_ids if hunk_id not in hunks_by_id]
    if unknown_hunks:
        raise ValueError(f"Assessment cites unknown label changes: {unknown_hunks}")
    relevant_hunks = [hunks_by_id[hunk_id] for hunk_id in hunk_ids]

    prompt = build_label_diff_revision_prompt(
        existing_indication,
        revision_assessment,
        relevant_hunks,
    )
    raw = llm(prompt) if llm else _call_claude(prompt, model, max_tokens)
    proposal = RevisionProposal.model_validate(raw)
    changes: dict[str, str | None] = {}
    for update in proposal.updates:
        if update.field in changes:
            raise ValueError(f"Duplicate proposed field: {update.field}")
        if update.new_value == existing_indication.get(update.field):
            continue
        changes[update.field] = update.new_value
    proposed = deepcopy(existing_indication)
    proposed.update(changes)
    return {
        "existing_indication_id": indication_id,
        "supporting_hunk_ids": hunk_ids,
        "changes": changes,
        "proposed_indication": proposed,
    }
