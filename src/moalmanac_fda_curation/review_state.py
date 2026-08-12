"""Record an explicit curator decision and refresh its deterministic review."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .workflow_artifacts import file_sha256, load_json_object, write_json_atomic

VALID_STAGES = {"document", "indication", "description", "approval"}
VALID_DECISIONS = {"accepted", "edited", "excluded", "unresolved"}
ALLOWED_OVERRIDES = {
    "document": {"company", "name", "description", "aliases", "status"},
    "indication": {
        "indication",
        "raw_biomarkers",
        "raw_cancer_type",
        "raw_therapeutics",
    },
    "description": {"description"},
    "approval": {"initial_approval_date", "initial_approval_url"},
}


def empty_decisions() -> dict[str, Any]:
    return {"schema_version": 1, "document": {}, "indications": {}}


def parse_override(value: str) -> tuple[str, Any]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("override must use FIELD=JSON_VALUE")
    field, raw_value = value.split("=", 1)
    if not field:
        raise argparse.ArgumentTypeError("override field cannot be empty")
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        parsed = raw_value
    return field, parsed


def load_decisions(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_decisions()
    payload = load_json_object(path, "Review decisions")
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported review decisions schema_version")
    if not isinstance(payload.get("document"), dict) or not isinstance(
        payload.get("indications"), dict
    ):
        raise ValueError("Review decisions must contain document and indications objects")
    return payload


def decision_sources(paths: list[Path]) -> dict[str, str]:
    return {str(path.resolve()): file_sha256(path.resolve()) for path in paths}


def record_decision(
    payload: dict[str, Any],
    stage: str,
    decision: str,
    indication_index: int | None,
    overrides: dict[str, Any],
    note: str | None,
    sources: dict[str, str],
    display_name: str | None = None,
) -> dict[str, Any]:
    if stage not in VALID_STAGES:
        raise ValueError(f"Unknown stage: {stage}")
    if decision not in VALID_DECISIONS:
        raise ValueError(f"Unknown decision: {decision}")
    if stage == "document" and indication_index is not None:
        raise ValueError("Document decisions must not include an indication index")
    if stage != "document" and indication_index is None:
        raise ValueError(f"{stage} decisions require an indication index")
    if decision == "excluded" and stage != "indication":
        raise ValueError("Only an indication can be excluded")
    if decision == "edited" and not overrides:
        raise ValueError("An edited decision requires at least one override")
    if decision != "edited" and overrides:
        raise ValueError("Overrides are only valid for an edited decision")
    unexpected_overrides = set(overrides) - ALLOWED_OVERRIDES[stage]
    if unexpected_overrides:
        raise ValueError(
            f"Unsupported {stage} override field(s): {sorted(unexpected_overrides)}"
        )

    entry = {
        "decision": decision,
        "overrides": overrides,
        "note": note,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": sources,
    }
    if display_name:
        entry["display_name"] = display_name
    if stage == "document":
        payload["document"] = entry
    else:
        indication = payload["indications"].setdefault(str(indication_index), {})
        indication[stage] = entry
        if stage == "indication" and (
            decision == "excluded" or "indication" in overrides
        ):
            indication.pop("description", None)
            indication.pop("approval", None)
    return payload


def append_review_log(
    path: Path,
    stage: str,
    decision: str,
    indication_index: int | None,
    overrides: dict[str, Any],
    note: str | None,
    display_name: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("# Curation review decisions\n\n", encoding="utf-8")
    title = "Document" if stage == "document" else f"{display_name or f'Indication {indication_index}'} — {stage}"
    lines = [f"## {title}", "", f"- Decision: {decision}"]
    if overrides:
        lines.append(f"- Approved overrides: `{json.dumps(overrides, sort_keys=True)}`")
    if note:
        lines.append(f"- Curator note: {note}")
    lines.extend(["", ""])
    with path.open("a", encoding="utf-8") as file:
        file.write("\n".join(lines))


def verify_decision_sources(payload: dict[str, Any]) -> None:
    entries = [payload.get("document", {})]
    entries.extend(
        stage
        for indication in payload.get("indications", {}).values()
        for stage in indication.values()
        if isinstance(stage, dict)
    )
    for entry in entries:
        for path_text, expected_hash in (entry.get("source_sha256") or {}).items():
            path = Path(path_text)
            if not path.exists() or file_sha256(path) != expected_hash:
                raise ValueError(f"Review decision is stale because its source changed: {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--stage", choices=sorted(VALID_STAGES), required=True)
    parser.add_argument("--decision", choices=sorted(VALID_DECISIONS), required=True)
    parser.add_argument("--indication-index", type=int)
    parser.add_argument("--override", action="append", type=parse_override, default=[])
    parser.add_argument("--note")
    parser.add_argument("--display-name", help="Curator-facing indication title for the review log.")
    return parser.parse_args()


def one_file(directory: Path, pattern: str, name: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if len(matches) != 1:
        raise FileNotFoundError(
            f"Expected exactly one {name} matching {directory / pattern}; found {len(matches)}"
        )
    return matches[0]


def review_inputs(work_dir: Path, stage: str) -> tuple[list[Path], list[str]]:
    document = work_dir / "intermediate" / "document.proposal.json"
    if stage == "document":
        return [document], ["--document-json", str(document)]

    indications = one_file(
        work_dir / "intermediate",
        "*-claude_chunked_indication_fields.json",
        "indication-fields artifact",
    )
    label_pdf = one_file(work_dir / "labels", "*.pdf", "current label PDF")
    label_markdown = one_file(work_dir / "labels", "*.md", "current label Markdown")
    sources = [indications]
    command = [
        "--document-json",
        str(document),
        "--indication-fields-json",
        str(indications),
        "--label-pdf",
        str(label_pdf),
        "--label-markdown",
        str(label_markdown),
    ]
    if stage == "description":
        descriptions = work_dir / "intermediate" / "selected-description-proposals.json"
        sources.append(descriptions)
        command.extend(("--descriptions-json", str(descriptions)))
    if stage == "approval":
        approvals = work_dir / "intermediate" / "selected-approval-evidence.json"
        changelog = one_file(
            work_dir / "intermediate" / "section1-changelogs",
            "*-section1-changelog.md",
            "Indications and Usage changelog",
        )
        sources.append(approvals)
        command.extend(
            (
                "--date-matches-json",
                str(approvals),
                "--changelog-markdown",
                str(changelog),
            )
        )
    return sources, command


def main() -> int:
    args = parse_args()
    work_dir = args.work_dir.resolve()
    decisions_path = work_dir / "review" / "decisions.json"
    review_log = work_dir / "review" / "review.md"
    sources, review_command = review_inputs(work_dir, args.stage)
    payload = load_decisions(decisions_path)
    overrides = dict(args.override)
    record_decision(
        payload=payload,
        stage=args.stage,
        decision=args.decision,
        indication_index=args.indication_index,
        overrides=overrides,
        note=args.note,
        sources=decision_sources(sources),
        display_name=args.display_name,
    )
    write_json_atomic(decisions_path, payload)
    append_review_log(
        review_log,
        args.stage,
        args.decision,
        args.indication_index,
        overrides,
        args.note,
        args.display_name,
    )
    rebuild = [
        sys.executable,
        "-m",
        "moalmanac_fda_curation.review_packet",
        "--stage",
        args.stage,
        *review_command,
        "--decisions-json",
        str(decisions_path),
        "--output-dir",
        str(work_dir / "review"),
    ]
    if args.stage != "document":
        rebuild.extend(("--indication-index", str(args.indication_index)))
    subprocess.run(rebuild, check=True)
    print(f"Recorded {args.decision} decision for {args.stage}")
    print(f"Decisions: {decisions_path}")
    print(f"Review log: {review_log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
