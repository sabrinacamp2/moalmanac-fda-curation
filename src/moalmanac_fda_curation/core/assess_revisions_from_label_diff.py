"""Assess existing indications against a deterministic two-label Section 1 diff."""

from __future__ import annotations

import difflib
import json
import os
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from .artifacts import load_json_object, same_url_path
from .build_section1_changelogs import line_key, logical_blocks

DEFAULT_MODEL = "claude-sonnet-4-5"


class ExistingIndicationRevision(BaseModel):
    """One existing indication's relationship to the source-label changes."""

    existing_indication_id: str
    status: Literal["revised", "not_revised", "uncertain"]
    relevant_hunk_ids: list[str] = Field(default_factory=list)
    changes: list[str] = Field(default_factory=list)
    reason: str


class LabelDiffRevisionResponse(BaseModel):
    assessments: list[ExistingIndicationRevision]


def _section_for_url(cache: dict[str, Any], label_url: str) -> tuple[str, str]:
    matches = [
        (url, section)
        for url, section in cache.items()
        if isinstance(url, str)
        and isinstance(section, str)
        and same_url_path(url, label_url)
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one cached Section 1 for {label_url}; found {len(matches)}"
        )
    return matches[0]


def load_section_pair_from_cache(
    cache_path: Path | str,
    *,
    baseline_label_url: str,
    latest_label_url: str,
) -> dict[str, str]:
    """Load baseline and latest Section 1 text from an existing URL cache."""
    cache = load_json_object(Path(cache_path), "Section 1 cache")
    resolved_baseline_url, baseline_section = _section_for_url(cache, baseline_label_url)
    resolved_latest_url, latest_section = _section_for_url(cache, latest_label_url)
    return {
        "baseline_label_url": resolved_baseline_url,
        "baseline_section": baseline_section,
        "latest_label_url": resolved_latest_url,
        "latest_section": latest_section,
    }


def build_section_diff_hunks(
    baseline_section: str,
    latest_section: str,
    *,
    context_blocks: int = 1,
) -> list[dict[str, Any]]:
    """Diff normalized Section 1 blocks and retain neighboring source context."""
    if context_blocks < 0:
        raise ValueError("context_blocks must be non-negative")
    baseline_blocks = logical_blocks(baseline_section)
    latest_blocks = logical_blocks(latest_section)
    matcher = difflib.SequenceMatcher(
        a=[line_key(block) for block in baseline_blocks],
        b=[line_key(block) for block in latest_blocks],
        autojunk=False,
    )
    hunks = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        hunks.append(
            {
                "hunk_id": f"hunk-{len(hunks) + 1}",
                "change_type": tag,
                "baseline_text": "\n".join(baseline_blocks[i1:i2]) or None,
                "latest_text": "\n".join(latest_blocks[j1:j2]) or None,
                "baseline_context_before": baseline_blocks[max(0, i1 - context_blocks):i1],
                "baseline_context_after": baseline_blocks[i2:i2 + context_blocks],
                "latest_context_before": latest_blocks[max(0, j1 - context_blocks):j1],
                "latest_context_after": latest_blocks[j2:j2 + context_blocks],
            }
        )
    return hunks


def build_revision_assessment_prompt(
    existing_indications: list[dict[str, Any]],
    diff_hunks: list[dict[str, Any]],
) -> str:
    """Build the source-diff attribution prompt for all existing indications."""
    targets = [
        {"id": indication["id"], "indication": indication["indication"]}
        for indication in existing_indications
    ]
    return f"""# Task

Determine which existing curated MOAlmanac FDA indications were revised between
two versions of the label's Indications and Usage section.

The diff hunks below were generated deterministically from the source label text.
Use them as the only evidence of label changes. Associate changes with an existing
indication only when the hunk applies to that indication. A new indication or a
change concerning a different indication is not evidence that the target changed.

# Existing indications

```json
{json.dumps(targets, indent=2, ensure_ascii=False)}
```

# Source-label diff hunks

```json
{json.dumps(diff_hunks, indent=2, ensure_ascii=False)}
```

# Statuses

- `revised`: one or more diff hunks change or further specify the target indication.
- `not_revised`: none of the diff hunks change or further specify the target.
- `uncertain`: the supplied evidence does not support a confident determination.

# Output rules

- Return exactly one assessment for every existing indication.
- For `revised`, cite every relevant hunk ID and tersely describe each change.
- For `not_revised`, return empty `relevant_hunk_ids` and `changes` lists.
- Do not treat punctuation, capitalization, PDF line wrapping, abbreviation or
  acronym expansion, harmless clause ordering, or semantically equivalent wording
  as a revision.
- Compare only what the source text explicitly states. Do not infer that an omitted
  qualification was already present merely because it may have been implied.
- Do not use outside clinical knowledge."""


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
        output_format=LabelDiffRevisionResponse,
    )
    parsed = response.parsed_output
    return parsed.model_dump() if hasattr(parsed, "model_dump") else parsed.dict()


def assess_revisions_from_label_diff(
    existing_indications: list[dict[str, Any]],
    diff_hunks: list[dict[str, Any]],
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 8000,
    llm: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assess, hydrate, and verify source-diff attribution for each indication."""
    existing_by_id = {item.get("id"): item for item in existing_indications}
    if None in existing_by_id or len(existing_by_id) != len(existing_indications):
        raise ValueError("Existing indications must have unique non-null IDs")
    hunks_by_id = {hunk.get("hunk_id"): hunk for hunk in diff_hunks}
    if None in hunks_by_id or len(hunks_by_id) != len(diff_hunks):
        raise ValueError("Diff hunks must have unique non-null hunk IDs")

    prompt = build_revision_assessment_prompt(existing_indications, diff_hunks)
    raw = llm(prompt) if llm else _call_claude(prompt, model, max_tokens)
    assessments = LabelDiffRevisionResponse.model_validate(raw).model_dump()["assessments"]
    errors: list[str] = []
    seen_ids: list[str] = []
    hydrated = []
    for index, assessment in enumerate(assessments):
        indication_id = assessment["existing_indication_id"]
        status = assessment["status"]
        hunk_ids = assessment["relevant_hunk_ids"]
        changes = assessment["changes"]
        if indication_id not in existing_by_id:
            errors.append(f"Assessment {index} cites unknown indication ID: {indication_id}")
        seen_ids.append(indication_id)
        unknown_hunks = [hunk_id for hunk_id in hunk_ids if hunk_id not in hunks_by_id]
        for hunk_id in unknown_hunks:
            errors.append(f"Assessment {index} cites unknown diff hunk: {hunk_id}")
        if status == "revised" and (not hunk_ids or not changes):
            errors.append(
                f"Assessment {index} revised status requires hunk IDs and changes"
            )
        if status == "not_revised" and (hunk_ids or changes):
            errors.append(
                f"Assessment {index} not_revised status must not report changes"
            )
        hydrated.append(
            {
                **assessment,
                "existing_indication": existing_by_id.get(indication_id),
                "relevant_hunks": [
                    hunks_by_id[hunk_id]
                    for hunk_id in hunk_ids
                    if hunk_id in hunks_by_id
                ],
            }
        )

    for indication_id in sorted({item for item in seen_ids if seen_ids.count(item) > 1}):
        errors.append(f"Existing indication assessed more than once: {indication_id}")
    for indication_id in sorted(set(existing_by_id) - set(seen_ids)):
        errors.append(f"Existing indication not assessed: {indication_id}")

    return {
        "assessments": hydrated,
        "verified": not errors,
        "verification_errors": errors,
    }
