"""Unified command line for the MOAlmanac FDA-label curation workflow."""

from __future__ import annotations

import sys
from collections.abc import Callable

from . import (
    assemble_draft,
    build_section1_changelogs,
    curate_doc_from_drugsfda_endpoint,
    extract_indication_descriptions,
    extract_indications_from_fda_label,
    match_indication_approval_dates_from_changelog,
)


COMMANDS: dict[str, tuple[str, Callable[[], int]]] = {
    "prepare-document": (
        "Create a document proposal from Drugs@FDA metadata",
        curate_doc_from_drugsfda_endpoint.main,
    ),
    "extract-indications": (
        "Extract indication proposals and source evidence from a pinned label",
        extract_indications_from_fda_label.main,
    ),
    "generate-descriptions": (
        "Draft descriptions with selected Clinical Studies evidence",
        extract_indication_descriptions.main,
    ),
    "build-history": (
        "Build the historical Section 1 changelog",
        build_section1_changelogs.main,
    ),
    "match-dates": (
        "Match indications to initial approval events",
        match_indication_approval_dates_from_changelog.main,
    ),
    "assemble-draft": (
        "Validate and assemble final indication JSON",
        assemble_draft.main,
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
