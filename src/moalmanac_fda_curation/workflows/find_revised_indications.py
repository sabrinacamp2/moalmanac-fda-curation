"""Find changed matched indications and prepare them for current-form review."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

from ..core.artifacts import load_json_object, write_json_atomic
from ..core.extract_indication_descriptions import DEFAULT_MODEL as CURATION_MODEL
from ..core.identify_new_indications import load_existing_indications
from ..core.identify_revised_indications import DEFAULT_MODEL as ASSESSMENT_MODEL
from ..core.identify_revised_indications import (
    build_section_diff_hunks,
    identify_revised_indications,
    load_section_pair_from_cache,
)
from .prepare_label_history import prepare_label_history


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--context-blocks", type=int, default=1)
    parser.add_argument("--assessment-model", default=ASSESSMENT_MODEL)
    parser.add_argument("--curation-model", default=CURATION_MODEL)
    parser.add_argument("--assessment-max-tokens", type=int, default=8000)
    parser.add_argument("--curation-max-tokens", type=int, default=4096)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def revision_targets(
    assessment: dict[str, Any], matches: dict[str, Any]
) -> list[dict[str, Any]]:
    """Pair every changed existing indication with its matched latest index."""
    latest_by_existing = {
        mapping.get("existing_indication_id"): mapping
        for mapping in matches.get("mappings") or []
        if mapping.get("classification") == "matched"
    }
    targets = []
    for item in assessment.get("assessments") or []:
        if item.get("status") != "revised":
            continue
        indication_id = item["existing_indication_id"]
        mapping = latest_by_existing.get(indication_id)
        if not mapping or not isinstance(mapping.get("latest_indication_index"), int):
            raise ValueError(
                f"Changed indication requires a matched latest indication: {indication_id}"
            )
        targets.append(
            {
                "existing_indication_id": indication_id,
                "latest_indication_index": mapping["latest_indication_index"],
                "existing_indication": item["existing_indication"],
                "review_label": (
                    (mapping.get("latest_indication") or {}).get("review_label")
                    or (mapping.get("latest_indication") or {}).get("raw_cancer_type")
                    or f"Indication {mapping['latest_indication_index']}"
                ),
                "label_change_ids": item.get("relevant_hunk_ids") or [],
                "reason": item.get("reason"),
            }
        )
    return targets


def main() -> int:
    args = parse_args()
    work_dir = args.work_dir.resolve()
    intermediate = work_dir / "intermediate"
    status_path = intermediate / "curation-status.json"
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

    history = prepare_label_history(
        work_dir,
        overwrite=args.overwrite,
        baseline_label_url=status["curated_label_url"],
    )
    assessment_path = intermediate / "revision-assessment.json"
    if assessment_path.exists() and not args.overwrite:
        assessment = load_json_object(assessment_path, "Revision assessment")
    else:
        existing = load_existing_indications(indications_path, status["document_id"])
        pair = load_section_pair_from_cache(
            history.cache_json,
            baseline_label_url=status["curated_label_url"],
            latest_label_url=status["latest_label_url"],
        )
        hunks = build_section_diff_hunks(
            pair["baseline_section"],
            pair["latest_section"],
            context_blocks=args.context_blocks,
        )
        assessment = identify_revised_indications(
            existing,
            hunks,
            model=args.assessment_model,
            max_tokens=args.assessment_max_tokens,
        )
        assessment.update(
            {
                "document_id": status["document_id"],
                "baseline_label_url": pair["baseline_label_url"],
                "latest_label_url": pair["latest_label_url"],
                "diff_hunks": hunks,
            }
        )
        write_json_atomic(assessment_path, assessment)
    if not assessment.get("verified"):
        raise ValueError("Revision assessment must be verified before preparing reviews")

    targets = revision_targets(
        assessment,
        load_json_object(intermediate / "indication-matches.json", "Indication matches"),
    )
    targets_path = intermediate / "revision-targets.json"
    write_json_atomic(
        targets_path,
        {
            "document_id": status["document_id"],
            "baseline_label_date": status["curated_label_date"],
            "latest_label_date": status["latest_label_date"],
            "targets": targets,
        },
    )
    if not targets:
        print("No changed matched indications were found.")
        return 0

    command = [
        sys.executable,
        "-m",
        "moalmanac_fda_curation.workflows.prepare_selected",
        "--work-dir",
        str(work_dir),
        "--model",
        args.curation_model,
        "--max-tokens",
        str(args.curation_max_tokens),
        "--revision-baseline-date",
        status["curated_label_date"],
    ]
    for target in targets:
        command.extend(("--indication-index", str(target["latest_indication_index"])))
    if args.overwrite:
        command.append("--overwrite")
    subprocess.run(command, check=True)
    print(f"Changed indication targets: {targets_path}")
    print(
        "Changed indication indexes prepared for review: "
        + ", ".join(str(target["latest_indication_index"]) for target in targets)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
