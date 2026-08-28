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

Propose the minimal updates needed for one existing curated MOAlmanac indication
based on its assessed changes between the baseline and current FDA labels.

# Existing editable fields

```json
{_json(existing_content)}
```

# Assessed changes for this indication

```json
{_json(guidance)}
```

# Cited deterministic source-label wording changes

```json
{_json(relevant_hunks)}
```

# Rules

- The assessed `changes` define the complete scope of this proposal. Update only
  content needed to apply those changes to the target indication.
- Use `latest_text` in the cited hunks as the source for current wording.
- Preserve existing drug-class wording; it may come from FDA Highlights and need not be
  repeated in the cited `latest_text` hunk.
- A hunk may contain other indications. Treat their wording as context only and do
  not add it to this indication.
- Update `description` only as needed to reflect the assessed changes; preserve
  unrelated study, approval, and explanatory details already present.
- Update raw fields only when an assessed change affects their content.
- Omit every unchanged field from `updates`.
- If the evidence is insufficient to propose a target-specific replacement, return
  no updates.
- Do not add information from outside the supplied inputs.
- Do not propose identifiers, dates, URLs, document fields, or provenance fields.
- Return complete replacement values, not instructions or partial text fragments."""


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
        raise ValueError("A revised assessment requires hunk IDs and changes")
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
