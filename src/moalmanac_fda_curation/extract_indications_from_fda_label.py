#!/usr/bin/env python3
"""Extract FDA label indications from a label PDF URL.

This script workflow:
1. Download the label PDF from a provided FDA label URL.
2. Convert the PDF to Markdown with MarkItDown.
3. Extract the full-prescribing ``1 INDICATIONS AND USAGE`` section.
4. Extract the Highlights ``INDICATIONS AND USAGE`` section when available,
   because it often contains a shared drug-class intro omitted from full
   prescribing Section 1.
5. Split the raw indication section into broad deterministic source chunks.
6. Ask Claude to extract indication entries and rough curator-aid fields from
   one source chunk at a time.

Outputs use the stem ``brandname-appnumber``. Provide the brand
name and application number from the source document metadata.

- ``labels/brandname-appnumber.pdf``
- ``labels/brandname-appnumber.md``
- ``extracted-indications/brandname-appnumber.raw_ind.md``
- ``extracted-indications/brandname-appnumber-claude_chunked_indication_fields.json``

Example:
    python extract_indications_from_fda_label.py \
      --document-json outputs/Verzenio-nda208716/document.json \
      --output-dir outputs/Verzenio-nda208716
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import warnings
from pathlib import Path
from typing import Any, Callable

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL*")

import requests

DEFAULT_MODEL = "claude-sonnet-4-5"
DEFAULT_MAX_TOKENS = 4096

from .workflow_artifacts import (
    document_label_url,
    load_document_artifact,
    load_json_object,
    partial_output_path,
    resolve_document_application_number,
    write_json_atomic,
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for one FDA label extraction run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--document-json",
        type=Path,
        required=True,
        help=(
            "Generated MOAlmanac document JSON. "
            "Derives the label URL, brand name, and FDA application number."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help=(
            "Workflow output root. Writes labels under labels/ and "
            "extraction artifacts under intermediate/."
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
        help=f"Maximum Claude output tokens. Defaults to {DEFAULT_MAX_TOKENS}.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Rewrite output files when they already exist.",
    )
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    """Resolve a CLI path relative to the current working directory."""
    return path if path.is_absolute() else Path.cwd() / path


def download_pdf_bytes(url: str) -> bytes:
    """Download a PDF URL and return its bytes."""
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/pdf,*/*",
        "Referer": "https://www.accessdata.fda.gov/scripts/cder/daf/",
    }
    response = requests.get(url, headers=headers, timeout=60)
    response.raise_for_status()

    if not response.content.startswith(b"%PDF"):
        raise ValueError(f"Downloaded file from {url} does not look like a PDF")

    return response.content


def convert_pdf_to_markdown_text(pdf_path: Path) -> str:
    """Convert a PDF file to Markdown text with MarkItDown."""
    try:
        from markitdown import MarkItDown
    except ImportError as exc:
        raise ImportError(
            "Install MarkItDown in this environment, e.g. `pip install markitdown`"
        ) from exc

    result = MarkItDown().convert(str(pdf_path))
    return result.text_content


def output_stem(brand: str, application_number: str) -> str:
    """Build the filename stem used by all output artifacts."""
    brand_part = re.sub(r"[^A-Za-z0-9]+", "-", brand).strip("-")
    application_part = re.sub(r"[^A-Za-z0-9]+", "-", application_number).strip("-")
    if not brand_part or not application_part:
        raise ValueError(
            "Brand name and application number must both contain filename-safe text"
        )
    return f"{brand_part}-{application_part}"


def write_text(path: Path, text: str, overwrite: bool = False) -> Path:
    """Write UTF-8 text unless the file exists and overwrite is false."""
    if path.exists() and not overwrite:
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_bytes(path: Path, content: bytes, overwrite: bool = False) -> Path:
    """Write bytes unless the file exists and overwrite is false."""
    if path.exists() and not overwrite:
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def heading_pattern(heading: str) -> str:
    """Build a heading regex that tolerates converted-PDF spacing differences."""
    escaped_words = [re.escape(word) for word in heading.split()]
    return r"[ \t]+".join(escaped_words)


def extract_section(text: str, start_heading: str, end_heading: str) -> str:
    """Extract text between two headings in converted label Markdown."""
    start = re.search(rf"(?m)^{heading_pattern(start_heading)}\s*$", text)
    if not start:
        raise ValueError(f"Could not find start heading: {start_heading}")

    remaining = text[start.end() :]
    end = re.search(rf"(?m)^{heading_pattern(end_heading)}\s*$", remaining)
    if not end:
        raise ValueError(f"Could not find end heading: {end_heading}")

    return remaining[: end.start()].strip()


def extract_indications_section(label_markdown: str) -> str:
    """Extract the full-prescribing Section 1 text from a converted FDA label."""
    full_prescribing_heading = re.search(
        r"(?m)^FULL PRESCRIBING INFORMATION\s*$",
        label_markdown,
    )
    if not full_prescribing_heading:
        raise ValueError("Could not find FULL PRESCRIBING INFORMATION")

    full_prescribing_text = label_markdown[full_prescribing_heading.end() :]
    return extract_section(
        full_prescribing_text,
        "1 INDICATIONS AND USAGE",
        "2 DOSAGE AND ADMINISTRATION",
    )


def extract_highlights_section(label_markdown: str) -> str | None:
    """Extract Highlights INDICATIONS AND USAGE text when present.

    The first page of FDA labels is commonly two-column text. Markdown
    conversion often interleaves the adjacent column, but the Highlights
    indications block is still useful source context because it may contain a
    shared class phrase such as "is a kinase inhibitor indicated...".
    """
    highlights = re.search(
        r"(?m)^HIGHLIGHTS OF PRESCRIBING INFORMATION\b.*$",
        label_markdown,
    )
    if not highlights:
        return None

    highlights_text = label_markdown[highlights.end() :]
    start = re.search(
        r"(?m)^(?:[-\u2500-\u257f\uf8e7]+)\s*INDICATIONS AND USAGE\s*(?:[-\u2500-\u257f\uf8e7]+).*$",
        highlights_text,
    )
    if not start:
        return None

    remaining = highlights_text[start.end() :]
    end = re.search(
        r"(?m)^(?:[-\u2500-\u257f\uf8e7]+)\s*[A-Z][A-Z /-]+\s*(?:[-\u2500-\u257f\uf8e7]+).*$",
        remaining,
    )
    if not end:
        return remaining.strip()

    return remaining[: end.start()].strip()


def extract_highlights_drug_class(highlights: str | None) -> str | None:
    """Extract a likely shared drug-class phrase from Highlights text."""
    if not highlights:
        return None

    intro_parts: list[str] = []
    for raw_line in highlights.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith(("•", "")):
            break

        # In two-column conversions, the adjacent column is often appended
        # after a bullet separator on the same line.
        line = line.split(" • ", 1)[0].split("  ", 1)[0].strip()
        if not line:
            continue

        if not intro_parts and not re.search(r"\bis\s+an?\b", line, re.IGNORECASE):
            continue

        if intro_parts and not re.search(r"\bindicated\b", line, re.IGNORECASE):
            if re.search(r"\(\d+(?:\.\d+)?(?:,\s*\d+(?:\.\d+)?)*\)", line):
                continue

        intro_parts.append(line)
        intro = " ".join(intro_parts)

        indicated = re.search(r"\bindicated\b", intro, flags=re.IGNORECASE)
        if indicated:
            return intro[: indicated.start()].strip(" ,;:")

    return None


def chunk_indications_section(raw: str) -> list[dict[str, Any]]:
    """Split FDA Section 1 into broad deterministic source chunks.

    These chunks are provenance anchors for downstream dating. They are
    intentionally broader than final indication entries so bullets, qualifiers,
    and patient-selection text stay with the surrounding indication context.
    """
    raw = raw.strip()

    numbered_chunks = re.split(r"(?=(?:^|\n)1\.\d+\s+)", raw)
    numbered_chunks = [chunk.strip() for chunk in numbered_chunks if chunk.strip()]
    chunks = numbered_chunks if len(numbered_chunks) > 1 else [raw]

    return [
        {
            "source_chunk_index": index,
            "source_chunk_text": chunk,
        }
        for index, chunk in enumerate(chunks)
    ]


def build_chunk_indication_prompt(
    source_chunk: dict[str, Any],
    brand_name: str,
    generic_name: str,
    highlights: str | None,
) -> str:
    """Create the Claude prompt used for one deterministic source chunk."""
    highlights_context = ""
    if highlights:
        highlights_context = f"""

FDA label Highlights drug-class phrase:
{highlights}
""".rstrip()

    return f"""
You are extracting FDA label indications for MOAlmanac curation.

Extract indication entries from the FDA full-prescribing source chunk below.
Use only the provided text.

For each indication, return:
- indication: a complete, standalone indication sentence.
- review_label: a concise display label of at most 8 words that distinguishes this
  indication during curator review. Prefer disease, biomarker, treatment setting, and
  a meaningful prior-treatment qualifier; do not include the drug name.
- raw_biomarkers: biomarker, molecular feature, expression status, mutation, genomic exclusion, or test-defined status directly used to select patients. Use null if none is present.
- raw_cancer_type: the disease or cancer type phrase from the indication.
- raw_therapeutics: the therapy or therapy combination phrase from the indication.
  In this field only, write the label drug as "{brand_name} ({generic_name})".
- highlights_drug_class_used: true only if the indication sentence uses the supplied
  Highlights drug-class phrase; otherwise false.

Rules:
- Preserve label wording as closely as possible.
- Preserve raw wording for the helper fields where possible.
- Repeat shared indication stems when the text contains multiple standalone indications.
- Keep directly related patient-selection, companion diagnostic, limitation-of-use, accelerated approval, continued approval, and other regulatory qualifier text with the indication it modifies.
- Do not split bullets that are alternatives, criteria, limitations, or patient-selection
  details under the same indication; fold them into the parent indication.
- If a Highlights drug-class phrase is provided, combine that phrase with each
  applicable full-prescribing indication so the indication begins in the
  MOAlmanac style, e.g. "BRAND is a [drug class] indicated...".
- Remove inline bracketed cross references, such as `[see Clinical Studies (14.1)]`.
- Do not add information that is not present in the provided text.
- If there is no biomarker or molecular selection criterion, set raw_biomarkers to null.

Drug brand name: {brand_name}
Drug generic name: {generic_name}
{highlights_context}

FDA full-prescribing source chunk:
{source_chunk["source_chunk_text"]}
""".strip()


def call_claude_for_indication_fields(
    source_chunks: list[dict[str, Any]],
    brand_name: str,
    generic_name: str,
    highlights: str | None,
    model: str,
    max_tokens: int,
    initial_indications: list[dict[str, Any]] | None = None,
    completed_source_chunk_indexes: set[int] | None = None,
    checkpoint: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Call Claude one source chunk at a time and attach chunk provenance."""
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

    class ChunkIndication(BaseModel):
        indication: str
        review_label: str
        raw_biomarkers: str | None = None
        raw_cancer_type: str | None = None
        raw_therapeutics: str | None = None
        highlights_drug_class_used: bool = False

    class ChunkIndicationResponse(BaseModel):
        indications: list[ChunkIndication]

    client = Anthropic()
    extracted_indications = list(initial_indications or [])
    completed_indexes = set(completed_source_chunk_indexes or set())

    for source_chunk in source_chunks:
        source_chunk_index = source_chunk["source_chunk_index"]
        if source_chunk_index in completed_indexes:
            print(f"Reusing source chunk {source_chunk_index}")
            continue

        print(f"Extracting source chunk {source_chunk_index}")
        response = client.messages.parse(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": build_chunk_indication_prompt(
                        source_chunk,
                        brand_name,
                        generic_name,
                        highlights,
                    ),
                }
            ],
            output_format=ChunkIndicationResponse,
        )

        for indication in response.parsed_output.indications:
            extracted_indications.append(
                {
                    **indication.model_dump(),
                    "source_chunk_index": source_chunk_index,
                }
            )
        completed_indexes.add(source_chunk_index)
        if checkpoint:
            checkpoint(
                {
                    "source_chunks": source_chunks,
                    "indications": extracted_indications,
                    "completed_source_chunk_indexes": sorted(completed_indexes),
                }
            )

    return {
        "source_chunks": source_chunks,
        "indications": extracted_indications,
    }


def convert_downloaded_pdf_to_markdown(pdf_content: bytes) -> str:
    """Convert downloaded PDF bytes to Markdown using a temporary local PDF."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_pdf = Path(temp_dir) / "label.pdf"
        temp_pdf.write_bytes(pdf_content)
        return convert_pdf_to_markdown_text(temp_pdf)


def extract_indications_from_label_url(
    label_url: str,
    brand_name: str,
    generic_name: str,
    application_number: str,
    labels_dir: Path,
    indications_dir: Path,
    model: str,
    max_tokens: int,
    overwrite: bool = False,
) -> dict[str, Path]:
    """Run the notebook-derived workflow for one FDA label URL."""
    pdf_content = download_pdf_bytes(label_url)
    label_markdown = convert_downloaded_pdf_to_markdown(pdf_content)

    stem = output_stem(brand_name, application_number)

    pdf_path = labels_dir / f"{stem}.pdf"
    md_path = labels_dir / f"{stem}.md"
    raw_indications_path = indications_dir / f"{stem}.raw_ind.md"
    claude_path = indications_dir / f"{stem}-claude_chunked_indication_fields.json"

    write_bytes(pdf_path, pdf_content, overwrite=overwrite)
    write_text(md_path, label_markdown, overwrite=overwrite)

    raw_indications = extract_indications_section(label_markdown)
    highlights_section = extract_highlights_section(label_markdown)
    highlights = extract_highlights_drug_class(highlights_section)
    write_text(
        raw_indications_path, raw_indications.rstrip() + "\n", overwrite=overwrite
    )

    source_chunks = chunk_indications_section(raw_indications)
    checkpoint_path = partial_output_path(claude_path)
    if overwrite:
        checkpoint_path.unlink(missing_ok=True)
    elif claude_path.exists():
        print(f"Reusing completed {claude_path}")
        return {
            "label_pdf": pdf_path,
            "label_markdown": md_path,
            "raw_indications": raw_indications_path,
            "claude_chunked_indication_fields": claude_path,
        }

    initial_indications: list[dict[str, Any]] = []
    completed_source_chunk_indexes: set[int] = set()
    if checkpoint_path.exists():
        checkpoint_payload = load_json_object(
            checkpoint_path,
            "Indication extraction checkpoint",
        )
        if checkpoint_payload.get("source_chunks") != source_chunks:
            raise ValueError(
                f"{checkpoint_path} does not match the current label chunks. "
                "Use --overwrite to start a fresh extraction."
            )
        initial_indications = checkpoint_payload.get("indications", [])
        completed_source_chunk_indexes = set(
            checkpoint_payload.get("completed_source_chunk_indexes", [])
        )
        print(
            f"Resuming {checkpoint_path}: "
            f"{len(completed_source_chunk_indexes)}/{len(source_chunks)} chunks complete"
        )

    claude_indications = call_claude_for_indication_fields(
        source_chunks=source_chunks,
        brand_name=brand_name,
        generic_name=generic_name,
        highlights=highlights,
        model=model,
        max_tokens=max_tokens,
        initial_indications=initial_indications,
        completed_source_chunk_indexes=completed_source_chunk_indexes,
        checkpoint=lambda payload: write_json_atomic(checkpoint_path, payload),
    )
    claude_indications["provenance"] = {
        "indications_and_usage_section": "Full Prescribing Information — Indications and Usage",
        "highlights_indications_and_usage_text": highlights_section,
        "highlights_drug_class_phrase": highlights,
    }
    write_json_atomic(claude_path, claude_indications)
    checkpoint_path.unlink(missing_ok=True)

    return {
        "label_pdf": pdf_path,
        "label_markdown": md_path,
        "raw_indications": raw_indications_path,
        "claude_chunked_indication_fields": claude_path,
    }


def main() -> int:
    """Run the CLI and print the written output paths."""
    args = parse_args()
    document = load_document_artifact(resolve_path(args.document_json))
    label_url = document_label_url(document)
    brand_name = document["drug_name_brand"]
    generic_name = document["drug_name_generic"]
    application_number = resolve_document_application_number(document)
    output_dir = resolve_path(args.output_dir)
    labels_dir = output_dir / "labels"
    indications_dir = output_dir / "intermediate"

    output_paths = extract_indications_from_label_url(
        label_url=label_url,
        brand_name=brand_name,
        generic_name=generic_name,
        application_number=application_number,
        labels_dir=labels_dir,
        indications_dir=indications_dir,
        model=args.model,
        max_tokens=args.max_tokens,
        overwrite=args.overwrite,
    )

    for label, path in output_paths.items():
        print(f"{label}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
