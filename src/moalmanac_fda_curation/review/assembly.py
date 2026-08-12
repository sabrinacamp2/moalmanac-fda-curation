"""Assemble curator-reviewed document.json and indication.json outputs."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from .decisions import load_decisions, verify_decision_sources
from ..core.artifacts import load_document_artifact, load_json_object, write_json_atomic


def load_json_list(path: Path, name: str) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"{name} must be a JSON list of objects: {path}")
    return payload


def indexed(items: list[dict[str, Any]], name: str) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for item in items:
        index = item.get("indication_index")
        if not isinstance(index, int):
            raise ValueError(f"Every {name} item must have an integer indication_index")
        if index in result:
            raise ValueError(f"Duplicate {name} indication_index: {index}")
        result[index] = item
    return result


def compile_indications(
    document: dict[str, Any],
    indication_payload: dict[str, Any],
    description_payload: dict[str, Any],
    date_matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compile biomarker indications after all curator decisions are applied."""
    indications = indication_payload.get("indications")
    if not isinstance(indications, list) or not all(isinstance(item, dict) for item in indications):
        raise ValueError("Indication fields artifact must contain an indications list")
    descriptions = description_payload.get("indications")
    if not isinstance(descriptions, list):
        raise ValueError("Description artifact must contain an indications list")

    description_by_index = indexed(descriptions, "description")
    date_by_index = indexed(date_matches, "date match")
    document_id = document.get("id")
    if not isinstance(document_id, str) or not document_id.startswith("doc:"):
        raise ValueError("Document id must be a doc:* string")
    indication_prefix = document_id.replace("doc:", "ind:", 1)

    output = []
    for index, item in enumerate(indications):
        if not item.get("raw_biomarkers"):
            continue
        if index not in description_by_index:
            raise ValueError(f"Missing description for retained indication {index}")
        if index not in date_by_index:
            raise ValueError(f"Missing approval-date result for retained indication {index}")
        verification = date_by_index[index].get("verification") or {}
        matched_event = verification.get("matched_event") or {}
        if not verification.get("verified") or not matched_event:
            raise ValueError(f"Approval-date match for indication {index} is not verified")
        output.append(
            {
                "id": f"{indication_prefix}:{index}",
                "document_id": document_id,
                "indication": item.get("indication"),
                "initial_approval_date": matched_event.get("date"),
                "initial_approval_url": matched_event.get("label_url"),
                "description": description_by_index[index].get("description"),
                "raw_biomarkers": item.get("raw_biomarkers"),
                "raw_cancer_type": item.get("raw_cancer_type"),
                "raw_therapeutics": item.get("raw_therapeutics"),
            }
        )
    if not output:
        raise ValueError("No indications passed reviewed assembly")
    return output

def accepted_entry(entry: dict[str, Any] | None, name: str) -> dict[str, Any]:
    if not entry or entry.get("decision") not in {"accepted", "edited"}:
        raise ValueError(f"Missing explicit accepted/edited decision for {name}")
    return entry


def assemble_reviewed(
    document: dict[str, Any],
    indication_payload: dict[str, Any],
    description_payload: dict[str, Any],
    date_matches: list[dict[str, Any]],
    decisions: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    verify_decision_sources(decisions)
    reviewed_document = copy.deepcopy(document)
    document_decision = accepted_entry(decisions.get("document"), "document")
    reviewed_document.update(document_decision.get("overrides") or {})

    reviewed_indications = copy.deepcopy(indication_payload)
    reviewed_descriptions = copy.deepcopy(description_payload)
    reviewed_dates = copy.deepcopy(date_matches)
    retained_indexes: list[int] = []

    for index, indication in enumerate(reviewed_indications.get("indications") or []):
        stage_decisions = decisions.get("indications", {}).get(str(index), {})
        indication_decision = stage_decisions.get("indication")
        if indication_decision and indication_decision.get("decision") == "excluded":
            indication["raw_biomarkers"] = None
            continue
        if not indication.get("raw_biomarkers") and not indication_decision:
            continue
        indication_decision = accepted_entry(indication_decision, f"indication {index}")
        description_decision = accepted_entry(
            stage_decisions.get("description"), f"indication {index} description"
        )
        approval_decision = accepted_entry(
            stage_decisions.get("approval"), f"indication {index} approval"
        )
        indication.update(indication_decision.get("overrides") or {})
        retained_indexes.append(index)

        description_item = next(
            (
                item
                for item in reviewed_descriptions.get("indications") or []
                if item.get("indication_index") == index
            ),
            None,
        )
        if description_item is None:
            raise ValueError(f"Missing generated description for indication {index}")
        description_item.update(description_decision.get("overrides") or {})

        date_item = next(
            (item for item in reviewed_dates if item.get("indication_index") == index),
            None,
        )
        if date_item is None:
            raise ValueError(f"Missing generated approval match for indication {index}")
        approval_overrides = approval_decision.get("overrides") or {}
        if approval_overrides:
            verification = date_item.setdefault("verification", {})
            matched_event = verification.setdefault("matched_event", {})
            if "initial_approval_date" in approval_overrides:
                matched_event["date"] = approval_overrides["initial_approval_date"]
            if "initial_approval_url" in approval_overrides:
                matched_event["label_url"] = approval_overrides["initial_approval_url"]
            verification["curator_overridden"] = True
            verification["verified"] = True

    if not retained_indexes:
        raise ValueError("No indications have completed curator review")
    compiled = compile_indications(
        reviewed_document,
        reviewed_indications,
        reviewed_descriptions,
        reviewed_dates,
    )
    return reviewed_document, compiled


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


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
    intermediate = work_dir / "intermediate"
    output_dir = work_dir / "reviewed"
    document_output = output_dir / "document.json"
    indication_output = output_dir / "indication.json"
    existing = [path for path in (document_output, indication_output) if path.exists()]
    if existing and not args.overwrite:
        raise FileExistsError(
            "Reviewed output already exists. Use --overwrite only after curator approval: "
            + ", ".join(str(path) for path in existing)
        )
    reviewed_document, reviewed_indications = assemble_reviewed(
        document=load_document_artifact(intermediate / "document.proposal.json"),
        indication_payload=load_json_object(
            one_file(
                intermediate,
                "*-claude_chunked_indication_fields.json",
                "indication-fields artifact",
            ),
            "Indication fields",
        ),
        description_payload=load_json_object(
            intermediate / "selected-description-proposals.json", "Descriptions"
        ),
        date_matches=load_json_list(
            intermediate / "selected-approval-evidence.json", "Date matches"
        ),
        decisions=load_decisions(work_dir / "review" / "decisions.json"),
    )
    write_json_atomic(document_output, reviewed_document)
    write_json_atomic(indication_output, reviewed_indications)
    print(f"Wrote {document_output}")
    print(f"Wrote {indication_output} ({len(reviewed_indications)} indications)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
