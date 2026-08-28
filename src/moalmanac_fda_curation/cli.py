"""Unified command line for the MOAlmanac FDA-label curation workflow."""

from __future__ import annotations

import sys
from collections.abc import Callable

from dotenv import load_dotenv

from . import doctor
from .review import assembly, decisions
from .workflows import (
    assess_revisions,
    check_preflight,
    extract_candidates,
    prepare_document,
    prepare_label_history,
    prepare_revision_review,
    prepare_selected,
    prepare_update_indications,
    propose_revisions,
    reconcile_indications,
)


COMMANDS: dict[str, tuple[str, Callable[[], int]]] = {
    "doctor": (
        "Check installation, API-key presence, FDA access, and output permissions",
        doctor.main,
    ),
    "check-curation-preflight": (
        "Check whether an FDA application is curated and has a newer label",
        check_preflight.main,
    ),
    "prepare-document-review": (
        "Prepare FDA document metadata and its curator review",
        prepare_document.main,
    ),
    "extract-indication-candidates": (
        "Extract indication candidates and create their screening review",
        extract_candidates.main,
    ),
    "reconcile-indications": (
        "Map existing indications to the latest-label indication candidates",
        reconcile_indications.main,
    ),
    "prepare-update-indication-review": (
        "Prepare latest-label reconciliation and unresolved exception review",
        prepare_update_indications.main,
    ),
    "prepare-label-history": (
        "Build historical Indications and Usage changelog and cache artifacts",
        prepare_label_history.main,
    ),
    "assess-revised-indications": (
        "Identify existing indications revised between two FDA labels",
        assess_revisions.main,
    ),
    "prepare-revision-review": (
        "Assess revisions and create reviews only for flagged indications",
        prepare_revision_review.main,
    ),
    "propose-revised-indications": (
        "Propose minimal patches for verified revised indications",
        propose_revisions.main,
    ),
    "prepare-selected-review": (
        "Prepare descriptions, approval evidence, and review files for selected indications",
        prepare_selected.main,
    ),
    "record-decision": (
        "Record a curator decision and refresh its review file",
        decisions.main,
    ),
    "assemble-reviewed": (
        "Apply explicit decisions and write reviewed document.json and indication.json",
        assembly.main,
    ),
}


def usage() -> str:
    lines = ["usage: moalmanac-fda-curation <command> [options]", "", "commands:"]
    width = max(len(command) for command in COMMANDS)
    lines.extend(
        f"  {command:<{width}}  {description}"
        for command, (description, _) in COMMANDS.items()
    )
    lines.extend(["", "Run 'moalmanac-fda-curation <command> --help' for command options."])
    return "\n".join(lines)


def main() -> int:
    load_dotenv()
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help"}:
        print(usage())
        return 0
    command = sys.argv[1]
    selected = COMMANDS.get(command)
    if selected is None:
        print(f"Unknown command: {command}\n", file=sys.stderr)
        print(usage(), file=sys.stderr)
        return 2
    sys.argv = [f"moalmanac-fda-curation {command}", *sys.argv[2:]]
    return selected[1]()


if __name__ == "__main__":
    raise SystemExit(main())
