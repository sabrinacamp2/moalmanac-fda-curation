"""Check whether an FDA application was curated and whether a newer label exists."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..core.artifacts import write_json_atomic
from ..core.check_curation_preflight import check_curation_preflight


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application-number", required=True)
    parser.add_argument("--documents-json", type=Path, required=True)
    parser.add_argument("--urls-json", type=Path)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    documents_path = args.documents_json.resolve()
    urls_path = (
        args.urls_json.resolve()
        if args.urls_json is not None
        else documents_path.parent / "urls.json"
    )
    result = check_curation_preflight(
        args.application_number, documents_path, urls_path
    )
    if args.output_json is None:
        print(json.dumps(result, indent=2))
        return 0
    output_path = args.output_json.resolve()
    if output_path.exists() and not args.overwrite:
        raise FileExistsError(f"Curation status already exists: {output_path}")
    write_json_atomic(output_path, result)
    print(f"Curation status: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
