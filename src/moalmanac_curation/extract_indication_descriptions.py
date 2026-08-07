#!/usr/bin/env python3
"""Draft MOAlmanac indication descriptions from extracted FDA indications.

This is a downstream FDA-indication curation step. It starts from the
``*-claude_chunked_indication_fields.json`` output created by
``extract_indications_from_fda_label.py`` and drafts the ``description`` field
for each extracted indication.

1. Load indication strings and raw curator-aid fields from the chunked
   indication extraction JSON.
2. Load the converted FDA label markdown for the same drug.
3. Extract broad supporting label sections:
   - Section 12, CLINICAL PHARMACOLOGY
   - Section 14, CLINICAL STUDIES
4. In one call, ask Claude to select the ``clinical_studies`` lines most
   relevant to every indication.
5. Drop any remaining supporting sections that are too large for focused
   description drafting.
6. Ask Claude for one structured ``description`` per indication.

Example:
    python extract_indication_descriptions.py \
      --document-json outputs/Yervoy-bla125377/document.json \
      --indication-fields-json outputs/Yervoy-bla125377/intermediate/Yervoy-BLA125377-claude_chunked_indication_fields.json \
      --label-markdown outputs/Yervoy-bla125377/labels/Yervoy-BLA125377.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Callable

DEFAULT_MODEL = "claude-sonnet-4-5"
DEFAULT_MAX_TOKENS = 4000
DEFAULT_CLINICAL_STUDIES_SELECTOR_MAX_TOKENS = 2000
DEFAULT_MAX_SUPPORTING_SECTION_CHARS = 60000
DEFAULT_AGENCY_NAME = "The U.S. Food and Drug Administration"

from .workflow_artifacts import (
    file_sha256,
    load_document_artifact,
    load_json_object,
    partial_output_path,
    write_json_atomic,
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for one description extraction run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--document-json",
        type=Path,
        required=True,
        help=(
            "Generated MOAlmanac document JSON. "
            "Derives document ID, brand name, and generic name."
        ),
    )
    parser.add_argument(
        "--agency-name",
        default=DEFAULT_AGENCY_NAME,
        help=f"Approval agency name. Defaults to {DEFAULT_AGENCY_NAME!r}.",
    )
    parser.add_argument(
        "--indication-fields-json",
        type=Path,
        required=True,
        help="Upstream *-claude_chunked_indication_fields.json artifact.",
    )
    parser.add_argument(
        "--label-markdown",
        type=Path,
        required=True,
        help="Converted FDA label Markdown artifact.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Optional explicit output path. If omitted, writes "
            "{brand}-{application}-claude_description_candidates.json in "
            "extracted-indications."
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
        help=f"Maximum Claude output tokens per indication. Defaults to {DEFAULT_MAX_TOKENS}.",
    )
    parser.add_argument(
        "--max-supporting-section-chars",
        type=int,
        default=DEFAULT_MAX_SUPPORTING_SECTION_CHARS,
        help=(
            "Maximum characters allowed for each supporting label section before "
            f"it is omitted from the prompt. Defaults to {DEFAULT_MAX_SUPPORTING_SECTION_CHARS}."
        ),
    )
    parser.add_argument(
        "--indication-index",
        type=int,
        action="append",
        help=(
            "Only draft descriptions for selected indication indexes. Repeat this "
            "flag to select multiple indexes. Defaults to all indications."
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


def output_path_for_args(
    args: argparse.Namespace,
    indication_fields_path: Path,
) -> Path:
    """Choose the output path from either --output or the standard filename."""
    if args.output:
        return resolve_path(args.output)
    suffix = "-claude_chunked_indication_fields.json"
    if indication_fields_path.name.endswith(suffix):
        stem = indication_fields_path.name[: -len(suffix)]
        return indication_fields_path.with_name(
            f"{stem}-claude_description_candidates.json"
        )
    return indication_fields_path.with_name(
        f"{indication_fields_path.stem}-claude_description_candidates.json"
    )


def load_chunked_indication_fields(path: Path) -> dict[str, Any]:
    """Load and validate upstream chunked indication fields JSON."""
    with path.open(encoding="utf-8") as file:
        payload = json.load(file)

    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")

    indications = payload.get("indications")
    if not isinstance(indications, list) or not indications:
        raise ValueError(f"{path} must contain a non-empty 'indications' list")

    for index, indication in enumerate(indications):
        if not isinstance(indication, dict):
            raise ValueError(f"indications[{index}] in {path} must be an object")
        if not isinstance(indication.get("indication"), str):
            raise ValueError(
                f"indications[{index}] in {path} must have indication text"
            )

    return payload


def extract_numbered_label_section(
    label_markdown: str,
    section_number: int,
) -> str | None:
    """Extract one top-level numbered section from converted label markdown.

    FDA label markdown is not perfectly uniform, so this finds a line beginning
    with the requested section number and then stops at the next larger
    top-level numbered heading. It intentionally does not select subsections:
    any narrowing happens later by omission when the section is too large.
    """
    full_prescribing = re.search(
        r"(?m)^FULL PRESCRIBING INFORMATION\s*$",
        label_markdown,
    )
    search_text = (
        label_markdown[full_prescribing.end() :] if full_prescribing else label_markdown
    )

    top_level_heading_pattern = r"(?m)^(\d+)[ \t]+[A-Z][A-Z0-9 /,;:()&'’.-]+$"
    start = None
    for match in re.finditer(top_level_heading_pattern, search_text):
        if int(match.group(1)) == section_number:
            start = match
            break
    if not start:
        return None

    remaining = search_text[start.start() :]
    after_start = remaining[start.end() - start.start() :]

    for match in re.finditer(top_level_heading_pattern, after_start):
        if int(match.group(1)) > section_number:
            end = start.end() - start.start() + match.start()
            return remaining[:end].strip()

    return remaining.strip()


def load_supporting_label_sections(label_markdown_path: Path) -> dict[str, str | None]:
    """Load broad supporting label sections used by the description prompt."""
    label_markdown = label_markdown_path.read_text(encoding="utf-8")
    return {
        "clinical_pharmacology": extract_numbered_label_section(label_markdown, 12),
        "clinical_studies": extract_numbered_label_section(label_markdown, 14),
    }


def build_description_input(
    indication: dict[str, Any],
    document_id: str,
    agency_name: str,
    brand_name: str,
    generic_name: str,
    supporting_label_sections: dict[str, str | None],
) -> dict[str, Any]:
    """Build the structured input object for one indication description."""
    return {
        "document_id": document_id,
        "agency_name": agency_name,
        "brand_name": brand_name,
        "generic_name": generic_name,
        "indication": indication["indication"],
        "raw_biomarkers": indication.get("raw_biomarkers"),
        "raw_cancer_type": indication.get("raw_cancer_type"),
        "raw_therapeutics": indication.get("raw_therapeutics"),
        "supporting_label_sections": supporting_label_sections,
    }


def numbered_lines(text: str) -> list[str]:
    """Return text lines prefixed with one-based line numbers."""
    return [
        f"{line_number}: {line}"
        for line_number, line in enumerate(text.splitlines(), start=1)
    ]


def build_clinical_studies_selector_prompt(
    description_input: dict[str, Any],
) -> str | None:
    """Format the prompt for selecting one relevant clinical_studies span."""
    clinical_studies = description_input["supporting_label_sections"].get(
        "clinical_studies"
    )
    if not clinical_studies:
        return None

    selector_input = {
        "document_id": description_input["document_id"],
        "brand_name": description_input["brand_name"],
        "generic_name": description_input["generic_name"],
        "indication": description_input["indication"],
        "raw_biomarkers": description_input.get("raw_biomarkers"),
        "raw_cancer_type": description_input.get("raw_cancer_type"),
        "raw_therapeutics": description_input.get("raw_therapeutics"),
    }
    clinical_studies_with_lines = "\n".join(numbered_lines(clinical_studies))

    return f"""
Identify one contiguous inclusive line-number span from the `clinical_studies` label text that is relevant to the selected indication.

Use the clinical-studies text only to find the trial basis, disease subgroup, regimen, biomarker, or therapeutic details that clarify this indication. Do not select a section centered on a different indication. Prefer the smallest single section that preserves necessary headings plus the lines needed to understand the selected indication, but it is okay to include extra lines when needed to keep the section coherent or avoid splitting a relevant subsection. Include adjacent heading lines when they identify the disease, indication, trial, or cohort.

Return span as null if `clinical_studies` does not contain a clearly relevant part for this indication.

Selected indication input:
{json.dumps(selector_input, indent=2)}

`clinical_studies` with one-based line numbers:
{clinical_studies_with_lines}
""".strip()


def call_claude_for_clinical_studies_selection(
    prompt: str,
    model: str,
    max_tokens: int,
) -> dict[str, Any]:
    """Call Claude for one relevant clinical_studies line span."""
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

    class ClinicalStudiesSpan(BaseModel):
        start_line: int = Field(
            description="First relevant one-based line number, inclusive"
        )
        end_line: int = Field(
            description="Last relevant one-based line number, inclusive"
        )
        relevance_reason: str = Field(
            description="Brief reason this span is relevant to the indication"
        )

    class ClinicalStudiesSelection(BaseModel):
        span: ClinicalStudiesSpan | None = Field(
            default=None,
            description="One contiguous clinical_studies span relevant to the indication",
        )
        no_relevant_span_reason: str | None = Field(
            default=None,
            description="Reason no span was selected, if span is null",
        )

    if hasattr(ClinicalStudiesSelection, "model_rebuild"):
        ClinicalStudiesSelection.model_rebuild()
    else:
        ClinicalStudiesSelection.update_forward_refs(
            ClinicalStudiesSpan=ClinicalStudiesSpan
        )

    client = Anthropic()
    response = client.messages.parse(
        model=model,
        max_tokens=max_tokens,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
        output_format=ClinicalStudiesSelection,
    )

    return pydantic_to_dict(response.parsed_output)


def extract_clinical_studies_span_text(
    clinical_studies: str,
    span: dict[str, Any],
) -> tuple[str | None, dict[str, Any] | None]:
    """Extract a selected clinical_studies span and return curator provenance."""
    lines = clinical_studies.splitlines()
    start_line = max(1, int(span["start_line"]))
    end_line = min(len(lines), int(span["end_line"]))
    if start_line > end_line:
        return None, None

    selected_text = "\n".join(lines[start_line - 1 : end_line]).strip()
    if not selected_text:
        return None, None

    selection = {
        "section": "clinical_studies",
        "start_line": start_line,
        "end_line": end_line,
        "relevance_reason": span.get("relevance_reason"),
        "text": selected_text,
    }
    return selected_text, selection


def input_with_selected_clinical_studies(
    description_input: dict[str, Any],
    model: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Replace clinical_studies with one selected relevant excerpt."""
    clinical_studies = description_input["supporting_label_sections"].get(
        "clinical_studies"
    )
    if not clinical_studies:
        return description_input, None

    prompt = build_clinical_studies_selector_prompt(description_input)
    if prompt is None:
        return description_input, None

    selection_response = call_claude_for_clinical_studies_selection(
        prompt=prompt,
        model=model,
        max_tokens=DEFAULT_CLINICAL_STUDIES_SELECTOR_MAX_TOKENS,
    )
    span = selection_response.get("span")

    filtered_input = dict(description_input)
    filtered_sections = dict(description_input["supporting_label_sections"])

    if span is None:
        filtered_sections.pop("clinical_studies", None)
        filtered_input["supporting_label_sections"] = filtered_sections
        return filtered_input, {
            "section": "clinical_studies",
            "selected_span": None,
            "no_relevant_span_reason": selection_response.get(
                "no_relevant_span_reason"
            ),
            "original_section_chars": len(clinical_studies),
        }

    selected_text, selected_span = extract_clinical_studies_span_text(
        clinical_studies=clinical_studies,
        span=span,
    )
    if selected_text is None or selected_span is None:
        filtered_sections.pop("clinical_studies", None)
        filtered_input["supporting_label_sections"] = filtered_sections
        return filtered_input, {
            "section": "clinical_studies",
            "selected_span": None,
            "no_relevant_span_reason": "selected line span was empty or invalid",
            "selector_response": selection_response,
            "original_section_chars": len(clinical_studies),
        }

    filtered_sections["clinical_studies"] = selected_text
    filtered_input["supporting_label_sections"] = filtered_sections
    return filtered_input, {
        "section": "clinical_studies",
        "selected_span": selected_span,
        "original_section_chars": len(clinical_studies),
        "selected_section_chars": len(selected_text),
    }


def select_all_clinical_studies_spans(
    indications: list[dict[str, Any]],
    indication_indexes: list[int],
    supporting_label_sections: dict[str, str | None],
    document_id: str,
    brand_name: str,
    generic_name: str,
    model: str,
) -> list[dict[str, Any]]:
    """Select relevant Section 14 spans for every indication in one call."""
    clinical_studies = supporting_label_sections.get("clinical_studies")
    if not clinical_studies:
        return []

    # Imported at runtime to avoid a module cycle: the standalone experiment
    # reuses parsing helpers from this production workflow.
    from .select_clinical_studies_spans_batch import (
        build_batch_selector_prompt,
        call_claude_for_batch_selection,
        validate_and_materialize_selections,
    )

    selected_indications = [indications[index] for index in indication_indexes]
    prompt = build_batch_selector_prompt(
        indications=selected_indications,
        clinical_studies=clinical_studies,
        document_id=document_id,
        brand_name=brand_name,
        generic_name=generic_name,
    )
    raw_selections = call_claude_for_batch_selection(
        prompt=prompt,
        model=model,
        max_tokens=max(
            DEFAULT_CLINICAL_STUDIES_SELECTOR_MAX_TOKENS,
            len(selected_indications) * 160,
        ),
    )
    local_selections = validate_and_materialize_selections(
        selections=raw_selections,
        indications=selected_indications,
        clinical_studies=clinical_studies,
    )
    return [
        {
            **selection,
            "indication_index": indication_indexes[selection["indication_index"]],
        }
        for selection in local_selections
    ]


def input_with_batch_clinical_studies_selection(
    description_input: dict[str, Any],
    selection: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Apply one precomputed batch selection to a description input."""
    clinical_studies = description_input["supporting_label_sections"].get(
        "clinical_studies"
    )
    if not clinical_studies:
        return description_input, None

    filtered_input = dict(description_input)
    filtered_sections = dict(description_input["supporting_label_sections"])
    selected_span = selection.get("selected_span") if selection else None
    if selected_span is None:
        filtered_sections.pop("clinical_studies", None)
    else:
        filtered_sections["clinical_studies"] = selected_span["text"]
    filtered_input["supporting_label_sections"] = filtered_sections

    return filtered_input, {
        "section": "clinical_studies",
        "selected_span": selected_span,
        "relevance_reason": selection.get("relevance_reason") if selection else None,
        "original_section_chars": len(clinical_studies),
        "selected_section_chars": (
            len(selected_span["text"]) if selected_span is not None else 0
        ),
    }


def prompt_sized_description_input(
    description_input: dict[str, Any],
    max_supporting_section_chars: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Drop oversized supporting sections before formatting the prompt.

    This is a final prompt-size guard after optional clinical_studies span
    selection.
    """
    prompt_input = dict(description_input)
    included_sections = {}
    omitted_sections = []

    for section_name, section_text in description_input.get(
        "supporting_label_sections", {}
    ).items():
        if section_text is None:
            continue

        if len(section_text) > max_supporting_section_chars:
            omitted_sections.append(
                {
                    "section": section_name,
                    "chars": len(section_text),
                    "reason": "omitted because section is too large for description drafting",
                }
            )
            continue

        included_sections[section_name] = section_text

    prompt_input["supporting_label_sections"] = included_sections
    return prompt_input, omitted_sections


def build_description_prompt(
    description_input: dict[str, Any],
    max_supporting_section_chars: int,
) -> tuple[str, list[dict[str, Any]], list[str]]:
    """Format the Claude prompt for one indication description."""
    prompt_input, omitted_sections = prompt_sized_description_input(
        description_input,
        max_supporting_section_chars=max_supporting_section_chars,
    )
    included_sections = list(prompt_input["supporting_label_sections"].keys())

    prompt = f"""
Draft a MOAlmanac indication description from the structured input below.

Requirements for the description field:
- Begin with: "{description_input['agency_name']} granted approval to ..." unless the indication says it was approved under accelerated approval.
- If the indication says it was approved under accelerated approval, begin with: "{description_input['agency_name']} granted accelerated approval to ...".
- Make the description self-contained and readable in isolation.
- Use respectful, person-first language consistent with ASCO Language of Respect guidance.
- Standardize terminology across agencies and time when doing so does not change the meaning.
- Use the generic drug name, not the brand name.
- If a drug combination is present, state the primary drug first, then "in combination with" the partner therapy.
- Write approvals as therapies for patients with a disease, not as therapies for the disease alone.
- Preserve limitation-of-use, accelerated approval, and continued approval language when it appears in the indication text.
- Preserve companion diagnostic or patient-selection language when it appears in the indication text.
- Expand abbreviations when the expansion is clear from the indication or supporting label text, including disease, biomarker, and receptor-status abbreviations.
- Prefer "variant" over "mutation" in the description when referring to genomic alterations, unless preserving quoted regulatory warning text.
- Use HGVS-style prefixes for variant names only when the correct prefix is clear from the input.
- Use American English and include the Oxford comma.
- Supporting label sections may be included as `clinical_pharmacology` and `clinical_studies`, but may be omitted when too large.
- Use `clinical_pharmacology` only to clarify ambiguous biomarker definitions directly relevant to the indication.
- If the indication depends on a susceptible biomarker, variant class, or treatment-selection criterion that is defined in `clinical_pharmacology`, include that concise definition when it is needed to make the description self-contained.
- Treat included `clinical_studies` text as a likely relevant clinical-studies excerpt for this indication, selected from the broader label before this prompt was built.
- Use the selected `clinical_studies` excerpt to clarify the trial basis, regimen, disease subgroup, biomarker context, or therapeutic details for the indication.
- If the indication contains a broad treatment class or regimen term, use the selected `clinical_studies` excerpt to identify the specific drugs or regimen components when the mapping is clear.
- When `clinical_studies` maps a broad treatment class or regimen term to specific drugs, include those specific drugs in the supporting sentence; do not stop at naming the trial alone.
- When `clinical_studies` defines the specific drugs or regimen components included under a broad regimen term in the indication, include those components even if they appear as trial treatment details, unless doing so would conflict with the approved indication.
- When the specific drugs differ by patient subgroup, disease histology, or disease subtype, include that mapping if it is directly relevant to the indication.
- When the selected `clinical_studies` excerpt clearly identifies the supporting trial by name or NCT number, include that trial identifier in the concise supporting sentence.
- When the selected `clinical_studies` excerpt clearly identifies the supporting trial phase or study design, such as phase 1/2, phase 2, phase 3, randomized, open-label, double-blind, single-arm, multicohort, or placebo-controlled, include those details in the concise supporting sentence.
- Preserve clinically meaningful qualifiers that determine which specific regimen applies to which patient subgroup. Omit dose amounts and schedules when possible.
- When using `clinical_studies`, add at most one concise sentence and avoid eligibility criteria, endpoints, and efficacy results.
- If the selected `clinical_studies` excerpt still does not clearly support or clarify this indication, draft from the indication only.
- Do not invent trial names, biomarkers, dates, or regulatory details.
- Do not mention source line numbers or provenance metadata in the description.

Structured input:
{json.dumps(prompt_input, indent=2)}
""".strip()

    return prompt, omitted_sections, included_sections


def pydantic_to_dict(model_output: Any) -> dict[str, Any]:
    """Convert a Pydantic model to a plain dict across Pydantic versions."""
    if hasattr(model_output, "model_dump"):
        return model_output.model_dump()
    return model_output.dict()


def call_claude_for_description(
    prompt: str,
    model: str,
    max_tokens: int,
) -> str:
    """Call Claude for one structured description draft."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Export it in your shell before running this script."
        )

    try:
        from anthropic import Anthropic
        from pydantic import BaseModel
    except ImportError as exc:
        raise ImportError(
            "Install required packages, e.g. `pip install anthropic pydantic`"
        ) from exc

    class DescriptionDraft(BaseModel):
        description: str

    client = Anthropic()
    response = client.messages.parse(
        model=model,
        max_tokens=max_tokens,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
        output_format=DescriptionDraft,
    )

    parsed = pydantic_to_dict(response.parsed_output)
    return parsed["description"]


def selected_indication_indexes(
    indications: list[dict[str, Any]],
    requested_indexes: list[int] | None,
) -> list[int]:
    """Return the indication indexes this run should draft."""
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


def build_description_candidates(
    chunked_indication_fields: dict[str, Any],
    supporting_label_sections: dict[str, str | None],
    args: argparse.Namespace,
    initial_outputs: list[dict[str, Any]] | None = None,
    initial_batch_selections: list[dict[str, Any]] | None = None,
    checkpoint: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Draft descriptions for selected indications and assemble output JSON."""
    indications = chunked_indication_fields["indications"]
    indexes = selected_indication_indexes(indications, args.indication_index)
    batch_selections = [
        selection
        for selection in (initial_batch_selections or [])
        if selection.get("indication_index") in indexes
    ]
    selected_batch_indexes = {
        selection.get("indication_index") for selection in batch_selections
    }
    if selected_batch_indexes != set(indexes):
        print(f"Selecting Clinical Studies spans for {len(indexes)} indications")
        batch_selections = select_all_clinical_studies_spans(
            indications=indications,
            indication_indexes=indexes,
            supporting_label_sections=supporting_label_sections,
            document_id=args.document_id,
            brand_name=args.brand_name,
            generic_name=args.generic_name,
            model=args.model,
        )
    batch_selection_by_index = {
        selection["indication_index"]: selection for selection in batch_selections
    }

    outputs = list(initial_outputs or [])
    completed_indexes = {
        item["indication_index"]
        for item in outputs
        if isinstance(item.get("indication_index"), int)
    }
    for indication_index in indexes:
        if indication_index in completed_indexes:
            print(f"Reusing description for indication {indication_index}")
            continue

        print(f"Drafting description for indication {indication_index}")
        indication = indications[indication_index]
        description_input = build_description_input(
            indication=indication,
            document_id=args.document_id,
            agency_name=args.agency_name,
            brand_name=args.brand_name,
            generic_name=args.generic_name,
            supporting_label_sections=supporting_label_sections,
        )
        description_input, clinical_studies_selection = (
            input_with_batch_clinical_studies_selection(
                description_input=description_input,
                selection=batch_selection_by_index.get(indication_index),
            )
        )
        prompt, omitted_sections, included_sections = build_description_prompt(
            description_input,
            max_supporting_section_chars=args.max_supporting_section_chars,
        )
        description = call_claude_for_description(
            prompt=prompt,
            model=args.model,
            max_tokens=args.max_tokens,
        )

        outputs.append(
            {
                "indication_index": indication_index,
                "source_chunk_index": indication.get("source_chunk_index"),
                "indication": indication["indication"],
                "description": description,
                "supporting_sections_included": included_sections,
                "supporting_sections_omitted": omitted_sections,
                "supporting_label_section_selections": (
                    [clinical_studies_selection]
                    if clinical_studies_selection is not None
                    else []
                ),
            }
        )
        outputs.sort(key=lambda item: item["indication_index"])
        completed_indexes.add(indication_index)
        if checkpoint:
            checkpoint(
                description_output_payload(
                    args=args,
                    outputs=outputs,
                    requested_indexes=indexes,
                    batch_selections=batch_selections,
                    include_checkpoint_metadata=True,
                )
            )

    return description_output_payload(
        args=args,
        outputs=outputs,
        requested_indexes=indexes,
        batch_selections=batch_selections,
        include_checkpoint_metadata=False,
    )


def description_output_payload(
    args: argparse.Namespace,
    outputs: list[dict[str, Any]],
    requested_indexes: list[int],
    batch_selections: list[dict[str, Any]],
    include_checkpoint_metadata: bool,
) -> dict[str, Any]:
    """Assemble the stable output schema plus optional resume metadata."""
    payload = {
        "document_id": args.document_id,
        "brand_name": args.brand_name,
        "generic_name": args.generic_name,
        "agency_name": args.agency_name,
        "model": args.model,
        "max_supporting_section_chars": args.max_supporting_section_chars,
        "requested_indication_indexes": requested_indexes,
        "clinical_studies_batch_selections": batch_selections,
        "indications": outputs,
    }
    return payload


def main() -> int:
    """Run the description drafting workflow and write JSON output."""
    args = parse_args()

    document = load_document_artifact(resolve_path(args.document_json))
    args.brand_name = document["drug_name_brand"]
    args.document_id = document["id"]
    args.generic_name = document["drug_name_generic"]
    indication_fields_path = resolve_path(args.indication_fields_json)
    label_markdown_path = resolve_path(args.label_markdown)

    output_path = output_path_for_args(args, indication_fields_path)
    checkpoint_path = partial_output_path(output_path)

    if output_path.exists() and not args.overwrite:
        raise FileExistsError(
            f"{output_path} already exists. Use --overwrite to rewrite it."
        )
    if args.overwrite:
        checkpoint_path.unlink(missing_ok=True)

    chunked_indication_fields = load_chunked_indication_fields(indication_fields_path)
    supporting_label_sections = load_supporting_label_sections(label_markdown_path)
    requested_indexes = selected_indication_indexes(
        chunked_indication_fields["indications"],
        args.indication_index,
    )
    checkpoint_metadata = {
        "document_id": args.document_id,
        "model": args.model,
        "max_tokens": args.max_tokens,
        "max_supporting_section_chars": args.max_supporting_section_chars,
        "requested_indication_indexes": requested_indexes,
        "indication_fields_sha256": file_sha256(indication_fields_path),
        "label_markdown_sha256": file_sha256(label_markdown_path),
    }
    initial_outputs: list[dict[str, Any]] = []
    initial_batch_selections: list[dict[str, Any]] = []
    if checkpoint_path.exists():
        checkpoint_payload = load_json_object(
            checkpoint_path,
            "Description checkpoint",
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
        initial_outputs = checkpoint_payload.get("indications", [])
        initial_batch_selections = checkpoint_payload.get(
            "clinical_studies_batch_selections", []
        )
        print(
            f"Resuming {checkpoint_path}: "
            f"{len(initial_outputs)}/{len(requested_indexes)} descriptions complete"
        )

    output = build_description_candidates(
        chunked_indication_fields=chunked_indication_fields,
        supporting_label_sections=supporting_label_sections,
        args=args,
        initial_outputs=initial_outputs,
        initial_batch_selections=initial_batch_selections,
        checkpoint=lambda payload: write_json_atomic(
            checkpoint_path,
            {**payload, **checkpoint_metadata},
        ),
    )

    write_json_atomic(output_path, output)
    checkpoint_path.unlink(missing_ok=True)

    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
