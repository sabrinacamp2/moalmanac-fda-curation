"""Record and assemble explicit curator decisions for revised indications."""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.artifacts import file_sha256, load_json_object, write_json_atomic
from .decisions import parse_override

VALID_DECISIONS = {"accepted", "edited", "no-change", "unresolved"}
EDITABLE_FIELDS = {
    "indication",
    "description",
    "raw_biomarkers",
    "raw_cancer_type",
    "raw_therapeutics",
    "initial_approval_date",
    "initial_approval_url",
}


def empty_decisions() -> dict[str, Any]:
    return {"schema_version": 1, "revisions": {}}


def load_revision_decisions(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_decisions()
    payload = load_json_object(path, "Revision decisions")
    if payload.get("schema_version") != 1 or not isinstance(
        payload.get("revisions"), dict
    ):
        raise ValueError("Unsupported revision decisions artifact")
    return payload


def record_revision_decision(
    payload: dict[str, Any],
    indication_id: str,
    decision: str,
    overrides: dict[str, Any],
    note: str | None,
    sources: dict[str, str],
) -> dict[str, Any]:
    if decision not in VALID_DECISIONS:
        raise ValueError(f"Unknown revision decision: {decision}")
    if decision == "edited" and not overrides:
        raise ValueError("An edited revision requires at least one field override")
    if decision != "edited" and overrides:
        raise ValueError("Only an edited revision can contain field overrides")
    unexpected = set(overrides) - EDITABLE_FIELDS
    if unexpected:
        raise ValueError(f"Unsupported revision field(s): {sorted(unexpected)}")
    payload["revisions"][indication_id] = {
        "decision": decision,
        "overrides": overrides,
        "note": note,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": sources,
    }
    return payload


def verify_sources(entry: dict[str, Any]) -> None:
    for path_text, expected_hash in (entry.get("source_sha256") or {}).items():
        path = Path(path_text)
        if not path.is_file() or file_sha256(path) != expected_hash:
            raise ValueError(f"Revision decision is stale because its source changed: {path}")


def assemble_revised_indications(
    assessment: dict[str, Any],
    proposals: dict[str, Any],
    decisions: dict[str, Any],
) -> list[dict[str, Any]]:
    revised = [
        item
        for item in assessment.get("assessments") or []
        if item.get("status") == "revised"
    ]
    proposal_by_id = {
        item.get("existing_indication_id"): item
        for item in proposals.get("proposals") or []
    }
    outputs = []
    for item in revised:
        indication_id = item["existing_indication_id"]
        entry = decisions.get("revisions", {}).get(indication_id)
        if entry is None or entry.get("decision") == "unresolved":
            raise ValueError(f"Revision decision is incomplete for {indication_id}")
        verify_sources(entry)
        if entry.get("decision") == "no-change":
            continue
        proposal = proposal_by_id.get(indication_id)
        if not isinstance(proposal, dict) or not isinstance(
            proposal.get("proposed_indication"), dict
        ):
            raise ValueError(f"Revision proposal is missing for {indication_id}")
        overrides = entry.get("overrides") or {}
        record = copy.deepcopy(proposal["proposed_indication"])
        record.update(overrides)
        outputs.append(record)
    return outputs


def decision_sources(work_dir: Path) -> dict[str, str]:
    paths = [
        work_dir / "intermediate" / "revision-assessment.json",
        work_dir / "intermediate" / "indication-reconciliation.json",
        work_dir / "intermediate" / "revision-proposals.json",
    ]
    return {str(path.resolve()): file_sha256(path.resolve()) for path in paths}


def append_log(
    path: Path,
    indication_id: str,
    decision: str,
    overrides: dict[str, Any],
    note: str | None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("# Revision decisions\n\n", encoding="utf-8")
    lines = [f"## `{indication_id}`", "", f"- Decision: {decision}"]
    if overrides:
        lines.extend(["- Approved field replacements:", ""])
        lines.extend(f"  - `{field}`: {value!r}" for field, value in overrides.items())
    if note:
        lines.append(f"- Curator note: {note}")
    with path.open("a", encoding="utf-8") as file:
        file.write("\n".join([*lines, "", ""]))


def parse_record_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record a revised-indication decision.")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--indication-id", required=True)
    parser.add_argument("--decision", choices=sorted(VALID_DECISIONS), required=True)
    parser.add_argument("--override", action="append", type=parse_override, default=[])
    parser.add_argument("--note")
    return parser.parse_args()


def record_main() -> int:
    args = parse_record_args()
    work_dir = args.work_dir.resolve()
    assessment = load_json_object(
        work_dir / "intermediate" / "revision-assessment.json", "Revision assessment"
    )
    revised_ids = {
        item.get("existing_indication_id")
        for item in assessment.get("assessments") or []
        if item.get("status") == "revised"
    }
    if args.indication_id not in revised_ids:
        raise ValueError(f"No flagged revision exists for {args.indication_id}")
    path = work_dir / "review" / "revision-decisions.json"
    payload = load_revision_decisions(path)
    overrides = dict(args.override)
    record_revision_decision(
        payload,
        args.indication_id,
        args.decision,
        overrides,
        args.note,
        decision_sources(work_dir),
    )
    write_json_atomic(path, payload)
    append_log(
        work_dir / "review" / "revision-review.md",
        args.indication_id,
        args.decision,
        overrides,
        args.note,
    )
    print(f"Recorded {args.decision} revision decision for {args.indication_id}")
    print(f"Decisions: {path}")
    return 0


def parse_assemble_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assemble reviewed revised indications.")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def assemble_main() -> int:
    args = parse_assemble_args()
    work_dir = args.work_dir.resolve()
    output = work_dir / "reviewed" / "revised-indications.json"
    if output.exists() and not args.overwrite:
        raise FileExistsError(f"Reviewed revision output already exists: {output}")
    revised = assemble_revised_indications(
        load_json_object(
            work_dir / "intermediate" / "revision-assessment.json",
            "Revision assessment",
        ),
        load_json_object(
            work_dir / "intermediate" / "revision-proposals.json",
            "Revision proposals",
        ),
        load_revision_decisions(work_dir / "review" / "revision-decisions.json"),
    )
    write_json_atomic(output, revised)
    print(f"Wrote {output} ({len(revised)} revised indications)")
    return 0
