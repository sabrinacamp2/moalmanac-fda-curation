"""Propose a minimal indication patch from a matched latest-label indication."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any, Callable, Literal

from pydantic import BaseModel

from .revise_indication import DEFAULT_MODEL


EDITABLE_FIELDS = (
    "indication",
    "description",
    "raw_biomarkers",
    "raw_cancer_type",
    "raw_therapeutics",
)


class LatestLabelFieldUpdate(BaseModel):
    """One replacement value proposed from the latest-label indication."""

    field: Literal[
        "indication",
        "description",
        "raw_biomarkers",
        "raw_cancer_type",
        "raw_therapeutics",
    ]
    new_value: str | None


class LatestLabelRevisionProposal(BaseModel):
    """Minimal structured output from the proposal LLM."""

    updates: list[LatestLabelFieldUpdate]


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


def build_latest_label_revision_prompt(
    existing_indication: dict[str, Any],
    latest_indication: dict[str, Any],
    revision_assessment: dict[str, Any],
) -> str:
    """Build a prompt containing only editable content and revision guidance."""
    existing_content = {
        field: existing_indication.get(field)
        for field in EDITABLE_FIELDS
    }
    latest_content = {
        field: latest_indication.get(field)
        for field in EDITABLE_FIELDS
        if field != "description"
    }
    guidance = {
        "meaningful_differences": revision_assessment.get("meaningful_differences", []),
        "reason": revision_assessment.get("reason"),
    }
    return f"""# Task

Propose the minimal updates needed for an existing curated MOAlmanac indication
to reflect its matched indication extracted from the latest FDA label.

# Existing editable fields

```json
{_json(existing_content)}
```

# Latest-label fields

```json
{_json(latest_content)}
```

# Revision guidance

```json
{_json(guidance)}
```

# Rules

- Use the latest-label indication as the source for current indication content.
- Use the revision guidance to limit the proposal to the identified meaningful
  wording differences.
- Update `description` only as needed to reflect those changes; preserve unrelated
  study, approval, and explanatory details already present in the description.
- Omit every unchanged field from `updates`.
- Do not add information from outside the supplied inputs.
- Do not propose identifiers, dates, URLs, document fields, or provenance fields.
- Return replacement values, not instructions or partial text fragments."""


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
        output_format=LatestLabelRevisionProposal,
    )
    parsed = response.parsed_output
    return parsed.model_dump() if hasattr(parsed, "model_dump") else parsed.dict()


def propose_indication_revision(
    existing_indication: dict[str, Any],
    latest_indication: dict[str, Any],
    revision_assessment: dict[str, Any],
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 3000,
    llm: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Propose and apply an allow-listed patch without changing provenance."""
    if revision_assessment.get("classification") != "revised":
        raise ValueError("A proposal requires a pairwise 'revised' assessment")
    prompt = build_latest_label_revision_prompt(
        existing_indication,
        latest_indication,
        revision_assessment,
    )
    raw = llm(prompt) if llm else _call_claude(prompt, model, max_tokens)
    proposal = LatestLabelRevisionProposal.model_validate(raw)
    changes: dict[str, str | None] = {}
    for update in proposal.updates:
        if update.field in changes:
            raise ValueError(f"Duplicate proposed field: {update.field}")
        if update.new_value == existing_indication.get(update.field):
            continue
        changes[update.field] = update.new_value
    if not changes:
        raise ValueError("A revised indication proposal must contain at least one change")
    proposed = deepcopy(existing_indication)
    proposed.update(changes)
    return {
        "changes": changes,
        "proposed_indication": proposed,
    }
