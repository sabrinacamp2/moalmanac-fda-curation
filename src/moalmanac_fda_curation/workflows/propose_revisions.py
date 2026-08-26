"""Generate minimal indication patches from a verified revision assessment."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..core.artifacts import load_json_object, write_json_atomic
from ..core.propose_revised_indication import DEFAULT_MODEL, propose_revised_indication


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assessment-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-tokens", type=int, default=3000)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_path = args.output_json.resolve()
    if output_path.exists() and not args.overwrite:
        raise FileExistsError(f"Revision proposal artifact already exists: {output_path}")
    assessment = load_json_object(
        args.assessment_json.resolve(), "Revision assessment artifact"
    )
    if not assessment.get("verified"):
        raise ValueError("Revision assessment must be verified before proposing patches")
    diff_hunks = assessment.get("diff_hunks")
    assessments = assessment.get("assessments")
    if not isinstance(diff_hunks, list) or not isinstance(assessments, list):
        raise ValueError("Revision assessment must contain diff_hunks and assessments lists")
    revised = [item for item in assessments if item.get("status") == "revised"]
    proposals = [
        propose_revised_indication(
            item["existing_indication"], item, diff_hunks,
            model=args.model, max_tokens=args.max_tokens,
        )
        for item in revised
    ]
    result = {
        "document_id": assessment.get("document_id"),
        "assessment_artifact": str(args.assessment_json.resolve()),
        "proposals": proposals,
    }
    write_json_atomic(output_path, result)
    print(f"Revision proposals: {output_path}")
    print(f"Proposals generated: {len(proposals)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
