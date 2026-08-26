"""Identify latest-label indications with no existing MOAlmanac counterpart."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel


DEFAULT_MODEL = "claude-sonnet-4-5"


class IndicationMapping(BaseModel):
    """One indication identity mapping."""

    existing_indication_id: str | None
    latest_indication_index: int | None
    classification: Literal["matched", "new", "not_found", "uncertain"]
    reason: str


class IndicationMappingResponse(BaseModel):
    mappings: list[IndicationMapping]


def load_existing_indications(
    path: Path | str, document_id: str
) -> list[dict[str, Any]]:
    """Load indications linked to one document."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(
        isinstance(item, dict) for item in payload
    ):
        raise ValueError(f"{path} must contain a JSON list of indication objects")
    indications = [item for item in payload if item.get("document_id") == document_id]
    if not indications:
        raise ValueError(f"No indications found for {document_id} in {path}")
    return indications


def indexed_latest_indications(
    indication_payload: dict[str, Any], *, biomarker_only: bool = True
) -> list[dict[str, Any]]:
    """Return latest candidates with stable extraction indexes."""
    indications = indication_payload.get("indications")
    if not isinstance(indications, list):
        raise ValueError(
            "Latest indication artifact must contain an 'indications' list"
        )
    output = []
    for index, indication in enumerate(indications):
        if not isinstance(indication, dict) or not isinstance(
            indication.get("indication"), str
        ):
            raise ValueError(f"Latest indication {index} must have indication text")
        if biomarker_only and not indication.get("raw_biomarkers"):
            continue
        output.append({"latest_indication_index": index, **indication})
    return output


def build_indication_mapping_prompt(
    existing_indications: list[dict[str, Any]],
    latest_indications: list[dict[str, Any]],
) -> str:
    """Build the indication identity-mapping prompt."""
    existing_items = [
        {"id": item["id"], "indication": item["indication"]}
        for item in existing_indications
    ]
    latest_items = [
        {
            "latest_indication_index": item["latest_indication_index"],
            "indication": item["indication"],
        }
        for item in latest_indications
    ]
    return f"""# Task

Map existing curated MOAlmanac FDA indications to indications extracted from a
newer FDA label, and classify every resulting relationship.

Determine whether each existing and newer-label record represents the same
underlying FDA indication. This task is only about identity across label versions.
Do not compare or report wording differences, and do not decide whether a matched
indication is the same or revised.

# Existing MOAlmanac indications

```json
{json.dumps(existing_items, indent=2, ensure_ascii=False)}
```

# Newer-label indications

```json
{json.dumps(latest_items, indent=2, ensure_ascii=False)}
```

# Classifications

- `matched`: the records represent the same underlying FDA indication.
- `new`: a newer-label indication has no existing counterpart.
- `not_found`: an existing indication has no newer-label counterpart.
- `uncertain`: identity cannot be determined confidently, including possible splits
  or merges.

# Mapping rules

- Account for every existing and every newer-label indication exactly once.
- Match identity based on the indication as a whole; wording differences do not by
  themselves make a newer-label indication `new`.
- Use only the supplied indication strings; do not add outside clinical knowledge."""


def _call_claude(prompt: str, model: str, max_tokens: int) -> dict[str, Any]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise ImportError(
            "Install the project dependencies before calling the LLM"
        ) from exc
    response = Anthropic().messages.parse(
        model=model,
        max_tokens=max_tokens,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
        output_format=IndicationMappingResponse,
    )
    parsed = response.parsed_output
    return parsed.model_dump() if hasattr(parsed, "model_dump") else parsed.dict()


def map_existing_to_latest_indications(
    existing_indications: list[dict[str, Any]],
    latest_indications: list[dict[str, Any]],
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 8000,
    llm: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Map, classify, hydrate, and verify complete one-to-one coverage."""
    existing_by_id = {item.get("id"): item for item in existing_indications}
    if None in existing_by_id or len(existing_by_id) != len(existing_indications):
        raise ValueError("Existing indications must have unique non-null IDs")
    latest_by_index = {
        item.get("latest_indication_index"): item for item in latest_indications
    }
    if None in latest_by_index or len(latest_by_index) != len(latest_indications):
        raise ValueError("Latest indications must have unique indexes")

    prompt = build_indication_mapping_prompt(existing_indications, latest_indications)
    raw = llm(prompt) if llm else _call_claude(prompt, model, max_tokens)
    mappings = IndicationMappingResponse.model_validate(raw).model_dump()["mappings"]
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
                errors.append(
                    f"Mapping {index} cites unknown existing ID: {existing_id}"
                )
            seen_existing.append(existing_id)
        if latest_index is not None:
            if latest_index not in latest_by_index:
                errors.append(
                    f"Mapping {index} cites unknown latest index: {latest_index}"
                )
            seen_latest.append(latest_index)
        if classification == "matched" and (
            existing_id is None or latest_index is None
        ):
            errors.append(
                f"Mapping {index} classification matched requires both sides"
            )
        if classification == "new" and (
            existing_id is not None or latest_index is None
        ):
            errors.append(
                f"Mapping {index} classification new requires only a latest indication"
            )
        if classification == "not_found" and (
            existing_id is None or latest_index is not None
        ):
            errors.append(
                f"Mapping {index} classification not_found requires only an existing indication"
            )
        if (
            classification == "uncertain"
            and existing_id is None
            and latest_index is None
        ):
            errors.append(
                f"Mapping {index} classification uncertain must reference an indication"
            )
        hydrated.append(
            {
                **mapping,
                "existing_indication": existing_by_id.get(existing_id),
                "latest_indication": latest_by_index.get(latest_index),
            }
        )

    for value in sorted(
        {item for item in seen_existing if seen_existing.count(item) > 1}
    ):
        errors.append(f"Existing indication mapped more than once: {value}")
    for value in sorted({item for item in seen_latest if seen_latest.count(item) > 1}):
        errors.append(f"Latest indication mapped more than once: {value}")
    for value in sorted(set(existing_by_id) - set(seen_existing)):
        errors.append(f"Existing indication not accounted for: {value}")
    for value in sorted(set(latest_by_index) - set(seen_latest)):
        errors.append(f"Latest indication not accounted for: {value}")

    return {"mappings": hydrated, "verified": not errors, "verification_errors": errors}


def select_new_indication_candidates(
    mapping_result: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return hydrated latest-label records classified as new."""
    if not mapping_result.get("verified"):
        raise ValueError("Cannot select new candidates from an unverified mapping")
    mappings = mapping_result.get("mappings")
    if not isinstance(mappings, list):
        raise ValueError("Mapping result must contain a mappings list")
    candidates = []
    for index, mapping in enumerate(mappings):
        if not isinstance(mapping, dict):
            raise ValueError(f"Mapping {index} must be an object")
        if mapping.get("classification") != "new":
            continue
        latest = mapping.get("latest_indication")
        if not isinstance(latest, dict):
            raise ValueError(f"New mapping {index} is missing its latest indication")
        candidates.append(
            {
                **latest,
                "new_candidate_reason": mapping.get("reason"),
            }
        )
    return candidates
