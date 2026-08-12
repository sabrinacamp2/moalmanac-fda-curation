"""Unified command line for the MOAlmanac FDA-label curation workflow."""

from __future__ import annotations

import sys
from collections.abc import Callable

from . import (
    assemble_reviewed,
    build_section1_changelogs,
    curate_doc_from_drugsfda_endpoint,
    doctor,
    extract_indication_descriptions,
    extract_indications_from_fda_label,
    match_indication_approval_dates_from_changelog,
    prepare_approval_evidence,
    prepare_selected_review,
    review_packet,
    review_state,
)


COMMANDS: dict[str, tuple[str, Callable[[], int]]] = {
    "doctor": (
        "Check installation, API-key presence, FDA access, and output permissions",
        doctor.main,
    ),
    "prepare-document": (
        "Create a document proposal from Drugs@FDA metadata",
        curate_doc_from_drugsfda_endpoint.main,
    ),
    "extract-indications": (
        "Extract indication proposals and source evidence from the selected label",
        extract_indications_from_fda_label.main,
    ),
    "generate-descriptions": (
        "Draft descriptions with selected Clinical Studies evidence",
        extract_indication_descriptions.main,
    ),
    "build-history": (
        "Build the historical Indications and Usage changelog (diagnostic)",
        build_section1_changelogs.main,
    ),
    "match-dates": (
        "Match indications to initial approval events",
        match_indication_approval_dates_from_changelog.main,
    ),
    "prepare-approval-evidence": (
        "Build/reuse label history and prepare approval evidence in one step",
        prepare_approval_evidence.main,
    ),
    "prepare-selected-review": (
        "Prepare descriptions, approval evidence, and review files for selected indications",
        prepare_selected_review.main,
    ),
    "review-packet": (
        "Create a compact evidence packet for one indication",
        review_packet.main,
    ),
    "record-decision": (
        "Record an explicit curator decision without editing generated artifacts",
        review_state.main,
    ),
    "assemble-reviewed": (
        "Apply explicit decisions and write reviewed document.json and indication.json",
        assemble_reviewed.main,
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
