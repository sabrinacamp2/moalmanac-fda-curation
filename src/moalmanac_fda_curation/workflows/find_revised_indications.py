"""Find curated indications that changed in a newer FDA label."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..core.artifacts import load_json_object
from ..core.identify_revised_indications import DEFAULT_MODEL as ASSESSMENT_MODEL
from ..core.match_indication_approval_dates_from_changelog import (
    DEFAULT_MAX_TOKENS as DATE_MAX_TOKENS,
    DEFAULT_MODEL as DATE_MODEL,
)
from ..core.propose_revised_indication import DEFAULT_MODEL as PROPOSAL_MODEL
from .prepare_label_history import prepare_label_history
from .prepare_revision_review import run as run_revision_review


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--context-blocks", type=int, default=1)
    parser.add_argument("--assessment-model", default=ASSESSMENT_MODEL)
    parser.add_argument("--proposal-model", default=PROPOSAL_MODEL)
    parser.add_argument("--date-model", default=DATE_MODEL)
    parser.add_argument("--assessment-max-tokens", type=int, default=8000)
    parser.add_argument("--proposal-max-tokens", type=int, default=3000)
    parser.add_argument("--date-max-tokens", type=int, default=DATE_MAX_TOKENS)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    work_dir = args.work_dir.resolve()
    status_path = work_dir / "intermediate" / "curation-status.json"
    status = load_json_object(status_path, "Curation status")
    if not status.get("previously_curated"):
        raise ValueError("Revision review requires a previously curated application")
    if not status.get("newer_label_available"):
        raise ValueError("Revision review requires a newer approved FDA label")

    indications_path = args.database_dir.resolve() / "referenced" / "indications.json"
    if not indications_path.is_file():
        raise FileNotFoundError(
            f"The supplied moalmanac-db path is missing: {indications_path}"
        )

    history = prepare_label_history(work_dir, overwrite=args.overwrite)
    review_args = argparse.Namespace(
        existing_indications_json=indications_path,
        document_id=status["document_id"],
        section_cache_json=history.cache_json,
        changelog_json=history.changelog_json,
        baseline_label_url=status["curated_label_url"],
        latest_label_url=status["latest_label_url"],
        baseline_label_date=status["curated_label_date"],
        latest_label_date=status["latest_label_date"],
        work_dir=work_dir,
        context_blocks=args.context_blocks,
        assessment_model=args.assessment_model,
        proposal_model=args.proposal_model,
        date_model=args.date_model,
        assessment_max_tokens=args.assessment_max_tokens,
        proposal_max_tokens=args.proposal_max_tokens,
        date_max_tokens=args.date_max_tokens,
        overwrite=args.overwrite,
    )
    return run_revision_review(review_args)


if __name__ == "__main__":
    raise SystemExit(main())
