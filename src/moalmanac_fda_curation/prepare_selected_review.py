"""Prepare descriptions, approval evidence, and review files for selected indications."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .extract_indication_descriptions import DEFAULT_MAX_TOKENS, DEFAULT_MODEL
from .build_section1_changelogs import output_stem
from .workflow_artifacts import load_document_artifact, resolve_document_application_number


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document-json", type=Path, required=True)
    parser.add_argument("--indication-fields-json", type=Path, required=True)
    parser.add_argument("--label-markdown", type=Path, required=True)
    parser.add_argument("--label-pdf", type=Path)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--indication-index", type=int, action="append", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Regenerate existing model outputs; requires explicit curator approval.",
    )
    return parser.parse_args()


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main() -> int:
    args = parse_args()
    document = args.document_json.resolve()
    document_payload = load_document_artifact(document)
    indication_fields = args.indication_fields_json.resolve()
    label_markdown = args.label_markdown.resolve()
    work_dir = args.work_dir.resolve()
    intermediate = work_dir / "intermediate"
    descriptions = intermediate / "selected-description-proposals.json"
    approvals = intermediate / "selected-approval-evidence.json"
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
    review_dir = work_dir / "review"

    indexes = list(dict.fromkeys(args.indication_index))
    common_indexes = [part for index in indexes for part in ("--indication-index", str(index))]

    if descriptions.exists() and not args.overwrite:
        print(f"Reusing {descriptions}")
    else:
        command = [
            sys.executable,
            "-m",
            "moalmanac_fda_curation.extract_indication_descriptions",
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
        "moalmanac_fda_curation.prepare_approval_evidence",
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
    run(approval_command)

    for index in indexes:
        for stage in ("indication", "description", "approval"):
            command = [
                sys.executable,
                "-m",
                "moalmanac_fda_curation.review_packet",
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
            if decisions.exists():
                command.extend(("--decisions-json", str(decisions)))
            if args.label_pdf:
                command.extend(("--label-pdf", str(args.label_pdf.resolve())))
            command.extend(("--label-markdown", str(label_markdown)))
            run(command)

    print(f"Prepared review files for indication indexes: {indexes}")
    print(f"Review directory: {review_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
