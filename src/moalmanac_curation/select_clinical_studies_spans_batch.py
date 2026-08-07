#!/usr/bin/env python3
"""Select Clinical Studies spans for all FDA indications in one Claude call.

This is an experimental, standalone alternative to the per-indication selector
in ``extract_indication_descriptions.py``. It sends label Section 14 once and
asks Claude to return one relevant contiguous line span, or no span, for every
indication in the upstream indication-fields artifact.

Example:
    python select_clinical_studies_spans_batch.py \
      --document-json outputs/Yervoy-bla125377/document.json \
      --indication-fields-json outputs/Yervoy-bla125377/intermediate/Yervoy-BLA125377-claude_chunked_indication_fields.json \
      --label-markdown outputs/Yervoy-bla125377/labels/Yervoy-BLA125377.md
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .extract_indication_descriptions import (
    extract_numbered_label_section,
    load_chunked_indication_fields,
    numbered_lines,
    pydantic_to_dict,
)
from .workflow_artifacts import (
    file_sha256,
    load_document_artifact,
    write_json_atomic,
)

DEFAULT_MODEL = "claude-sonnet-4-5"
DEFAULT_MAX_TOKENS = 8000


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for one batch-selection run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--document-json",
        type=Path,
        required=True,
        help="Generated MOAlmanac document JSON.",
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
        help="Optional output path. Defaults beside the indication-fields JSON.",
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
        help=f"Maximum Claude output tokens. Defaults to {DEFAULT_MAX_TOKENS}.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Rewrite the output when it already exists.",
    )
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    """Resolve a CLI path relative to the current working directory."""
    return path if path.is_absolute() else Path.cwd() / path


def default_output_path(indication_fields_path: Path) -> Path:
    """Build the standard batch-selection artifact path."""
    suffix = "-claude_chunked_indication_fields.json"
    if indication_fields_path.name.endswith(suffix):
        stem = indication_fields_path.name[: -len(suffix)]
    else:
        stem = indication_fields_path.stem
    return indication_fields_path.with_name(
        f"{stem}-claude_clinical_studies_batch_selections.json"
    )


def indication_selector_inputs(
    indications: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return compact, stably indexed indication inputs for the selector."""
    return [
        {
            "indication_index": index,
            "indication": indication["indication"],
            "raw_biomarkers": indication.get("raw_biomarkers"),
            "raw_cancer_type": indication.get("raw_cancer_type"),
            "raw_therapeutics": indication.get("raw_therapeutics"),
        }
        for index, indication in enumerate(indications)
    ]


def build_batch_selector_prompt(
    indications: list[dict[str, Any]],
    clinical_studies: str,
    document_id: str,
    brand_name: str,
    generic_name: str,
) -> str:
    """Build one prompt that maps every indication to a Section 14 span."""
    selector_input = {
        "document_id": document_id,
        "brand_name": brand_name,
        "generic_name": generic_name,
        "indications": indication_selector_inputs(indications),
    }
    clinical_studies_with_lines = "\n".join(numbered_lines(clinical_studies))

    return f"""
For every indication in the input, identify at most one contiguous inclusive
line-number span from the `clinical_studies` label text that is relevant to
that indication.

Use the clinical-studies text only to find the trial basis, disease subgroup,
regimen, biomarker, or therapeutic details that clarify an indication. Do not
select a section centered on a different indication. Prefer the smallest
single span that preserves necessary headings plus the lines needed to
understand the indication, but include adjacent heading lines when they
identify the disease, indication, trial, or cohort.

Return exactly one selection for every supplied indication_index, in the same
order as the input. Set start_line and end_line to null when there is no
clearly relevant span. Never reuse an indication_index or invent one.

Indication inputs:
{json.dumps(selector_input, indent=2)}

`clinical_studies` with one-based line numbers:
{clinical_studies_with_lines}
""".strip()


def call_claude_for_batch_selection(
    prompt: str,
    model: str,
    max_tokens: int,
) -> list[dict[str, Any]]:
    """Ask Claude for all indication-to-Clinical-Studies mappings at once."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Export it before running this script."
        )

    try:
        from anthropic import Anthropic
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise ImportError(
            "Install required packages, e.g. `pip install anthropic pydantic`"
        ) from exc

    class IndicationSelection(BaseModel):
        indication_index: int
        start_line: int | None = None
        end_line: int | None = None
        relevance_reason: str = Field(
            description=(
                "Brief relevance explanation, or why no relevant span was found"
            )
        )

    class BatchSelectionResponse(BaseModel):
        selections: list[IndicationSelection]

    if hasattr(BatchSelectionResponse, "model_rebuild"):
        BatchSelectionResponse.model_rebuild()
    else:
        BatchSelectionResponse.update_forward_refs(
            IndicationSelection=IndicationSelection
        )

    client = Anthropic()
    response = client.messages.parse(
        model=model,
        max_tokens=max_tokens,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
        output_format=BatchSelectionResponse,
    )
    return [
        pydantic_to_dict(selection)
        for selection in response.parsed_output.selections
    ]


def validate_and_materialize_selections(
    selections: list[dict[str, Any]],
    indications: list[dict[str, Any]],
    clinical_studies: str,
) -> list[dict[str, Any]]:
    """Validate one complete mapping and attach selected source text."""
    expected_indexes = set(range(len(indications)))
    returned_indexes = [selection["indication_index"] for selection in selections]
    duplicate_indexes = sorted(
        {index for index in returned_indexes if returned_indexes.count(index) > 1}
    )
    if duplicate_indexes:
        raise ValueError(f"Claude returned duplicate indication indexes: {duplicate_indexes}")

    returned_index_set = set(returned_indexes)
    missing_indexes = sorted(expected_indexes - returned_index_set)
    unexpected_indexes = sorted(returned_index_set - expected_indexes)
    if missing_indexes or unexpected_indexes:
        raise ValueError(
            "Claude returned an incomplete indication mapping: "
            f"missing={missing_indexes}, unexpected={unexpected_indexes}"
        )

    lines = clinical_studies.splitlines()
    materialized = []
    for selection in sorted(selections, key=lambda item: item["indication_index"]):
        indication_index = selection["indication_index"]
        start_line = selection.get("start_line")
        end_line = selection.get("end_line")

        if (start_line is None) != (end_line is None):
            raise ValueError(
                f"Indication {indication_index} must have both span bounds or neither"
            )

        selected_span = None
        if start_line is not None and end_line is not None:
            if not (1 <= start_line <= end_line <= len(lines)):
                raise ValueError(
                    f"Indication {indication_index} returned invalid span "
                    f"{start_line}-{end_line}; Section 14 has {len(lines)} lines"
                )
            selected_span = {
                "start_line": start_line,
                "end_line": end_line,
                "text": "\n".join(lines[start_line - 1 : end_line]).strip(),
            }

        materialized.append(
            {
                "indication_index": indication_index,
                "source_chunk_index": indications[indication_index].get(
                    "source_chunk_index"
                ),
                "indication": indications[indication_index]["indication"],
                "selected_span": selected_span,
                "relevance_reason": selection["relevance_reason"],
            }
        )

    return materialized


def main() -> int:
    """Run one full-label batch span-selection experiment."""
    args = parse_args()
    document_path = resolve_path(args.document_json)
    indication_fields_path = resolve_path(args.indication_fields_json)
    label_markdown_path = resolve_path(args.label_markdown)
    output_path = (
        resolve_path(args.output)
        if args.output
        else default_output_path(indication_fields_path)
    )

    if output_path.exists() and not args.overwrite:
        raise FileExistsError(
            f"{output_path} already exists. Use --overwrite to rewrite it."
        )

    document = load_document_artifact(document_path)
    indication_payload = load_chunked_indication_fields(indication_fields_path)
    indications = indication_payload["indications"]
    label_markdown = label_markdown_path.read_text(encoding="utf-8")
    clinical_studies = extract_numbered_label_section(label_markdown, 14)
    if not clinical_studies:
        raise ValueError(f"Could not find Clinical Studies Section 14 in {label_markdown_path}")

    prompt = build_batch_selector_prompt(
        indications=indications,
        clinical_studies=clinical_studies,
        document_id=document["id"],
        brand_name=document["drug_name_brand"],
        generic_name=document["drug_name_generic"],
    )
    raw_selections = call_claude_for_batch_selection(
        prompt=prompt,
        model=args.model,
        max_tokens=args.max_tokens,
    )
    selections = validate_and_materialize_selections(
        selections=raw_selections,
        indications=indications,
        clinical_studies=clinical_studies,
    )

    output = {
        "document_id": document["id"],
        "brand_name": document["drug_name_brand"],
        "generic_name": document["drug_name_generic"],
        "model": args.model,
        "indication_count": len(indications),
        "clinical_studies_chars": len(clinical_studies),
        "clinical_studies_lines": len(clinical_studies.splitlines()),
        "indication_fields_sha256": file_sha256(indication_fields_path),
        "label_markdown_sha256": file_sha256(label_markdown_path),
        "selections": selections,
    }
    write_json_atomic(output_path, output)
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
