"""Extract indication candidates and create their deterministic screening review."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from ..core.extract_indications_from_fda_label import DEFAULT_MAX_TOKENS, DEFAULT_MODEL, output_stem
from ..core.artifacts import load_document_artifact, resolve_document_application_number


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    work_dir = args.work_dir.resolve()
    document_path = work_dir / "intermediate" / "document.proposal.json"
    document = load_document_artifact(document_path)
    stem = output_stem(
        document["drug_name_brand"], resolve_document_application_number(document)
    )
    label_pdf = work_dir / "labels" / f"{stem}.pdf"
    label_markdown = work_dir / "labels" / f"{stem}.md"
    indications = work_dir / "intermediate" / f"{stem}-claude_chunked_indication_fields.json"

    extraction = [
        sys.executable,
        "-m",
        "moalmanac_fda_curation.core.extract_indications_from_fda_label",
        "--document-json",
        str(document_path),
        "--output-dir",
        str(work_dir),
        "--model",
        args.model,
        "--max-tokens",
        str(args.max_tokens),
    ]
    if args.overwrite:
        extraction.append("--overwrite")
    subprocess.run(extraction, check=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "moalmanac_fda_curation.review.packets",
            "--stage",
            "candidates",
            "--document-json",
            str(document_path),
            "--indication-fields-json",
            str(indications),
            "--label-pdf",
            str(label_pdf),
            "--label-markdown",
            str(label_markdown),
            "--output-dir",
            str(work_dir / "review"),
        ],
        check=True,
    )
    print(f"Candidate review: {work_dir / 'review' / 'indication-candidates.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
