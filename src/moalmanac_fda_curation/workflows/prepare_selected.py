"""Prepare descriptions, approval evidence, and review files for selected indications."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from ..core.extract_indication_descriptions import DEFAULT_MAX_TOKENS, DEFAULT_MODEL
from ..core.build_section1_changelogs import output_stem
from ..core.artifacts import load_document_artifact, resolve_document_application_number


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--indication-index", type=int, action="append", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument(
        "--revision-baseline-date",
        help="Limit date matching to labels after this previously curated label date.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Regenerate existing extraction outputs; requires explicit curator approval.",
    )
    parser.add_argument(
        "--skip-indication-review",
        action="store_true",
        help="Prepare only description and approval reviews for pre-approved indications.",
    )
    return parser.parse_args()


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def one_file(directory: Path, pattern: str, name: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if len(matches) != 1:
        raise FileNotFoundError(
            f"Expected exactly one {name} matching {directory / pattern}; found {len(matches)}"
        )
    return matches[0]


def main() -> int:
    args = parse_args()
    work_dir = args.work_dir.resolve()
    document = work_dir / "intermediate" / "document.proposal.json"
    document_payload = load_document_artifact(document)
    indication_fields = one_file(
        work_dir / "intermediate",
        "*-claude_chunked_indication_fields.json",
        "indication-fields artifact",
    )
    label_markdown = one_file(work_dir / "labels", "*.md", "current label Markdown")
    label_pdf = one_file(work_dir / "labels", "*.pdf", "current label PDF")
    intermediate = work_dir / "intermediate"
    descriptions = intermediate / (
        "selected-revision-description-proposals.json"
        if args.revision_baseline_date
        else "selected-description-proposals.json"
    )
    approvals = intermediate / (
        "selected-revision-date-evidence.json"
        if args.revision_baseline_date
        else "selected-approval-evidence.json"
    )
    changelog_stem = output_stem(
        document_payload["drug_name_brand"],
        resolve_document_application_number(document_payload),
    )
    changelog_markdown = (
        intermediate
        / "section1-changelogs"
        / f"{changelog_stem}-section1-changelog.md"
    )
    decisions = work_dir / "review" / "decisions.json"
    revision_targets = intermediate / "revision-targets.json"
    review_dir = work_dir / "review"

    indexes = list(dict.fromkeys(args.indication_index))
    common_indexes = [part for index in indexes for part in ("--indication-index", str(index))]

    if descriptions.exists() and not args.overwrite:
        print(f"Reusing {descriptions}")
    else:
        command = [
            sys.executable,
            "-m",
            "moalmanac_fda_curation.core.extract_indication_descriptions",
            "--document-json",
            str(document),
            "--indication-fields-json",
            str(indication_fields),
            "--label-markdown",
            str(label_markdown),
            "--output",
            str(descriptions),
            "--model",
            args.model,
            "--max-tokens",
            str(args.max_tokens),
            *common_indexes,
        ]
        if args.overwrite:
            command.append("--overwrite")
        run(command)

    approval_command = [
        sys.executable,
        "-m",
        "moalmanac_fda_curation.workflows.prepare_approval",
        "--document-json",
        str(document),
        "--indication-fields-json",
        str(indication_fields),
        "--work-dir",
        str(work_dir),
        "--output",
        str(approvals),
        "--model",
        args.model,
        "--max-tokens",
        str(args.max_tokens),
        *common_indexes,
    ]
    if args.overwrite:
        approval_command.append("--overwrite")
    if args.revision_baseline_date:
        approval_command.extend(
            ("--revision-baseline-date", args.revision_baseline_date)
        )
    run(approval_command)

    for index in indexes:
        stages = ("description", "approval") if args.skip_indication_review else (
            "indication", "description", "approval"
        )
        for stage in stages:
            command = [
                sys.executable,
                "-m",
                "moalmanac_fda_curation.review.packets",
                "--stage",
                stage,
                "--document-json",
                str(document),
                "--indication-fields-json",
                str(indication_fields),
                "--indication-index",
                str(index),
                "--output-dir",
                str(review_dir),
            ]
            if stage == "description":
                command.extend(("--descriptions-json", str(descriptions)))
            if stage == "approval":
                command.extend(("--date-matches-json", str(approvals)))
                command.extend(("--changelog-markdown", str(changelog_markdown)))
                if args.revision_baseline_date:
                    command.extend(
                        ("--revision-baseline-date", args.revision_baseline_date)
                    )
            if decisions.exists():
                command.extend(("--decisions-json", str(decisions)))
            if args.revision_baseline_date:
                command.extend(("--revision-targets-json", str(revision_targets)))
            command.extend(("--label-pdf", str(label_pdf)))
            command.extend(("--label-markdown", str(label_markdown)))
            run(command)

    print(f"Prepared review files for indication indexes: {indexes}")
    print(f"Review directory: {review_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
