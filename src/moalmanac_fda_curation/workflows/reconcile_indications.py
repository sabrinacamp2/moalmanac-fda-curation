"""Reconcile existing MOAlmanac indications with latest-label candidates."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..core.artifacts import load_json_object, write_json_atomic
from ..core.identify_new_indications import (
    DEFAULT_MODEL,
    indexed_latest_indications,
    load_existing_indications,
    map_existing_to_latest_indications,
    select_new_indication_candidates,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--existing-indications-json", type=Path, required=True)
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--latest-indications-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--include-non-biomarker", action="store_true")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-tokens", type=int, default=8000)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_path = args.output_json.resolve()
    if output_path.exists() and not args.overwrite:
        raise FileExistsError(f"Reconciliation artifact already exists: {output_path}")
    existing = load_existing_indications(
        args.existing_indications_json.resolve(), args.document_id
    )
    latest_payload = load_json_object(
        args.latest_indications_json.resolve(), "Latest indication artifact"
    )
    latest = indexed_latest_indications(
        latest_payload, biomarker_only=not args.include_non_biomarker
    )
    result = map_existing_to_latest_indications(
        existing, latest, model=args.model, max_tokens=args.max_tokens
    )
    result["new_indication_candidates"] = (
        select_new_indication_candidates(result) if result["verified"] else []
    )
    result["document_id"] = args.document_id
    result["biomarker_only"] = not args.include_non_biomarker
    write_json_atomic(output_path, result)
    print(f"Indication reconciliation: {output_path}")
    print(f"Verified: {result['verified']}")
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
