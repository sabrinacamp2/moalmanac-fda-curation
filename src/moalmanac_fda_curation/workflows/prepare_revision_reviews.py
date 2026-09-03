"""Prepare detailed curation reviews for curator-selected revisions."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from ..core.artifacts import load_json_object
from ..core.extract_indication_descriptions import DEFAULT_MAX_TOKENS, DEFAULT_MODEL
from ..review.decisions import load_decisions, verify_decision_sources


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def selected_revision_indexes(targets: dict, decisions: dict) -> list[int]:
    selected = []
    unresolved = []
    for target in targets.get("targets") or []:
        index = target["latest_indication_index"]
        decision = (
            decisions.get("indications", {}).get(str(index), {}).get("revision") or {}
        ).get("decision")
        if decision == "use_latest":
            selected.append(index)
        elif decision != "keep_existing":
            unresolved.append(index)
    if unresolved:
        raise ValueError(f"Revision screening decisions remain unresolved: {unresolved}")
    return selected


def main() -> int:
    args = parse_args()
    work_dir = args.work_dir.resolve()
    targets = load_json_object(
        work_dir / "intermediate" / "revision-targets.json", "Revision targets"
    )
    decisions = load_decisions(work_dir / "review" / "decisions.json")
    verify_decision_sources(decisions)
    indexes = selected_revision_indexes(targets, decisions)
    if not indexes:
        print("No indications were selected for recuration.")
        return 0
    command = [
        sys.executable,
        "-m",
        "moalmanac_fda_curation.workflows.prepare_selected",
        "--work-dir",
        str(work_dir),
        "--model",
        args.model,
        "--max-tokens",
        str(args.max_tokens),
        "--revision-baseline-date",
        targets["baseline_label_date"],
        "--skip-indication-review",
    ]
    for index in indexes:
        command.extend(("--indication-index", str(index)))
    if args.overwrite:
        command.append("--overwrite")
    subprocess.run(command, check=True)
    print("Prepared detailed revision reviews for indication indexes: " + ", ".join(map(str, indexes)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
