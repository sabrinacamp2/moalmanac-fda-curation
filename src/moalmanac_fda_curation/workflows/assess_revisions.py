"""Assess existing indications against a deterministic two-label source diff."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..core.artifacts import write_json_atomic
from ..core.identify_new_indications import load_existing_indications
from ..core.identify_revised_indications import (
    DEFAULT_MODEL,
    build_section_diff_hunks,
    identify_revised_indications,
    load_section_pair_from_cache,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--existing-indications-json", type=Path, required=True)
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--section-cache-json", type=Path, required=True)
    parser.add_argument("--baseline-label-url", required=True)
    parser.add_argument("--latest-label-url", required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--context-blocks", type=int, default=1)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-tokens", type=int, default=8000)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_path = args.output_json.resolve()
    if output_path.exists() and not args.overwrite:
        raise FileExistsError(f"Revision assessment artifact already exists: {output_path}")
    existing = load_existing_indications(
        args.existing_indications_json.resolve(), args.document_id
    )
    pair = load_section_pair_from_cache(
        args.section_cache_json.resolve(),
        baseline_label_url=args.baseline_label_url,
        latest_label_url=args.latest_label_url,
    )
    hunks = build_section_diff_hunks(
        pair["baseline_section"], pair["latest_section"],
        context_blocks=args.context_blocks,
    )
    result = identify_revised_indications(
        existing, hunks, model=args.model, max_tokens=args.max_tokens
    )
    result.update({
        "document_id": args.document_id,
        "baseline_label_url": pair["baseline_label_url"],
        "latest_label_url": pair["latest_label_url"],
        "diff_hunks": hunks,
    })
    write_json_atomic(output_path, result)
    print(f"Revision assessment: {output_path}")
    print(f"Verified: {result['verified']}")
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
