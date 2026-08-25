"""Reconcile existing MOAlmanac indications with latest-label candidates."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from .revise_indication import DEFAULT_MODEL


class IndicationMapping(BaseModel):
    """One relationship between an existing and/or latest indication."""

    existing_indication_id: str | None = Field(
        description="Existing MOAlmanac indication ID, or null for a new indication."
    )
    latest_indication_index: int | None = Field(
        description="Latest-label candidate index, or null when not found in the latest label."
    )
    classification: Literal["matched", "new", "not_found", "uncertain"]
    reason: str = Field(
        description="Concise clinical reason for the identity mapping and classification."
    )


class ReconciliationResponse(BaseModel):
    mappings: list[IndicationMapping]


def load_existing_indications(path: Path | str, document_id: str) -> list[dict[str, Any]]:
    """Load indications linked to one document from a referenced indications file."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"{path} must contain a JSON list of indication objects")
    indications = [item for item in payload if item.get("document_id") == document_id]
    if not indications:
        raise ValueError(f"No indications found for {document_id} in {path}")
    return indications


def indexed_latest_indications(
    indication_payload: dict[str, Any], *, biomarker_only: bool = True
) -> list[dict[str, Any]]:
    """Return latest candidates with stable indexes from an extraction artifact."""
    indications = indication_payload.get("indications")
    if not isinstance(indications, list):
        raise ValueError("Latest indication artifact must contain an 'indications' list")
    output = []
    for index, indication in enumerate(indications):
        if not isinstance(indication, dict) or not isinstance(indication.get("indication"), str):
            raise ValueError(f"Latest indication {index} must be an object with indication text")
        if biomarker_only and not indication.get("raw_biomarkers"):
            continue
        output.append({"latest_indication_index": index, **indication})
    return output


def build_reconciliation_prompt(
    existing_indications: list[dict[str, Any]],
    latest_indications: list[dict[str, Any]],
) -> str:
    """Build the prompt from only the identifiers and indication strings."""
    existing_prompt_items = [
        {
            "id": indication["id"],
            "indication": indication["indication"],
        }
        for indication in existing_indications
    ]
    latest_prompt_items = [
        {
            "latest_indication_index": indication["latest_indication_index"],
            "indication": indication["indication"],
        }
        for indication in latest_indications
    ]
    return f"""# Task

Reconcile the existing MOAlmanac indications for one drug with indications
extracted from its latest FDA label.

# Existing MOAlmanac indications

```json
{json.dumps(existing_prompt_items, indent=2, ensure_ascii=False)}
```

# Latest-label indications

```json
{json.dumps(latest_prompt_items, indent=2, ensure_ascii=False)}
```

# Classification rules

- `matched`: an existing and latest indication represent the same underlying
  approved use, even if details or wording have changed.
- `new`: a latest-label indication has no existing counterpart.
- `not_found`: an existing indication has no counterpart in the latest-label list.
- `uncertain`: identity is ambiguous, including possible splits or merges.

# Matching rules

- Account for every existing indication and every latest-label indication exactly once.
- Match clinical meaning rather than wording or sentence order.
- Do not classify an indication as new merely because its details or wording changed.
- Do not decide whether a matched indication is unchanged or revised; that is a
  separate downstream task.
- Do not force a match based only on the drug name.
- Use `uncertain` when a one-to-one relationship cannot be established confidently.
- Ignore stylistic, capitalization, abbreviation, and formatting differences.
- Use only the supplied indications; do not add outside clinical knowledge."""


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
        output_format=ReconciliationResponse,
    )
    parsed = response.parsed_output
    return parsed.model_dump() if hasattr(parsed, "model_dump") else parsed.dict()


def reconcile_indications(
    existing_indications: list[dict[str, Any]],
    latest_indications: list[dict[str, Any]],
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 8000,
    llm: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Reconcile two indication sets and verify complete, unique coverage."""
    existing_by_id = {item.get("id"): item for item in existing_indications}
    if None in existing_by_id or len(existing_by_id) != len(existing_indications):
        raise ValueError("Existing indications must have unique non-null IDs")
    latest_by_index = {item.get("latest_indication_index"): item for item in latest_indications}
    if None in latest_by_index or len(latest_by_index) != len(latest_indications):
        raise ValueError("Latest indications must have unique integer latest_indication_index values")

    prompt = build_reconciliation_prompt(existing_indications, latest_indications)
    raw = llm(prompt) if llm else _call_claude(prompt, model, max_tokens)
    mappings = ReconciliationResponse.model_validate(raw).model_dump()["mappings"]
    errors: list[str] = []
    seen_existing: list[str] = []
    seen_latest: list[int] = []
    hydrated = []
    for index, mapping in enumerate(mappings):
        existing_id = mapping["existing_indication_id"]
        latest_index = mapping["latest_indication_index"]
        classification = mapping["classification"]
        if existing_id is not None:
            if existing_id not in existing_by_id:
                errors.append(f"Mapping {index} cites unknown existing ID: {existing_id}")
            seen_existing.append(existing_id)
        if latest_index is not None:
            if latest_index not in latest_by_index:
                errors.append(f"Mapping {index} cites unknown latest index: {latest_index}")
            seen_latest.append(latest_index)
        if classification == "matched" and (
            existing_id is None or latest_index is None
        ):
            errors.append(f"Mapping {index} classification {classification} requires both sides")
        if classification == "new" and (existing_id is not None or latest_index is None):
            errors.append(f"Mapping {index} classification new requires only a latest indication")
        if classification == "not_found" and (existing_id is None or latest_index is not None):
            errors.append(f"Mapping {index} classification not_found requires only an existing indication")
        if classification == "uncertain" and existing_id is None and latest_index is None:
            errors.append(f"Mapping {index} classification uncertain must reference an indication")
        hydrated.append(
            {
                **mapping,
                "existing_indication": existing_by_id.get(existing_id),
                "latest_indication": latest_by_index.get(latest_index),
            }
        )

    for value in sorted({item for item in seen_existing if seen_existing.count(item) > 1}):
        errors.append(f"Existing indication mapped more than once: {value}")
    for value in sorted({item for item in seen_latest if seen_latest.count(item) > 1}):
        errors.append(f"Latest indication mapped more than once: {value}")
    for value in sorted(set(existing_by_id) - set(seen_existing)):
        errors.append(f"Existing indication not accounted for: {value}")
    for value in sorted(set(latest_by_index) - set(seen_latest)):
        errors.append(f"Latest indication not accounted for: {value}")

    return {"mappings": hydrated, "verified": not errors, "verification_errors": errors}
