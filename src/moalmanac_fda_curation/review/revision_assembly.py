"""Assemble curator-approved updates to existing MOAlmanac indications."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from ..core.artifacts import load_json_object, write_json_atomic
from .assembly import accepted_entry, indexed, load_json_list
from .decisions import load_decisions, verify_decision_sources


def assemble_updated_indications(
    targets_payload: dict[str, Any],
    indication_payload: dict[str, Any],
    description_payload: dict[str, Any],
    date_matches: list[dict[str, Any]],
    decisions: dict[str, Any],
) -> list[dict[str, Any]]:
    """Apply standard stage decisions while preserving existing indication IDs."""
    indications = indication_payload.get("indications") or []
    descriptions = indexed(description_payload.get("indications") or [], "description")
    dates = indexed(date_matches, "date match")
    outputs = []
    for target in targets_payload.get("targets") or []:
        index = target["latest_indication_index"]
        stages = decisions.get("indications", {}).get(str(index), {})
        screening_decision = (stages.get("revision") or {}).get("decision")
        if screening_decision == "keep_existing":
            continue
        if screening_decision != "use_latest":
            raise ValueError(f"Revision screening for indication {index} is unresolved")
        description_decision = accepted_entry(
            stages.get("description"), f"indication {index} description"
        )
        approval_decision = accepted_entry(
            stages.get("approval"), f"indication {index} current-form date"
        )
        if index >= len(indications) or index not in descriptions or index not in dates:
            raise ValueError(f"Revision target {index} is missing prepared curation evidence")

        indication = copy.deepcopy(indications[index])
        indication.update((stages.get("revision") or {}).get("overrides") or {})
        description = copy.deepcopy(descriptions[index])
        description.update(description_decision.get("overrides") or {})
        date_match = copy.deepcopy(dates[index])
        event = (date_match.get("verification") or {}).get("matched_event") or {}
        if not (date_match.get("verification") or {}).get("verified") or not event:
            raise ValueError(f"Current-form date for indication {index} is not verified")
        approval = {
            "initial_approval_date": event.get("date"),
            "initial_approval_url": event.get("label_url"),
        }
        approval.update(approval_decision.get("overrides") or {})
        existing = target["existing_indication"]
        outputs.append(
            {
                "id": existing["id"],
                "document_id": existing["document_id"],
                "indication": indication.get("indication"),
                **approval,
                "description": description.get("description"),
                "raw_biomarkers": indication.get("raw_biomarkers"),
                "raw_cancer_type": indication.get("raw_cancer_type"),
                "raw_therapeutics": indication.get("raw_therapeutics"),
            }
        )
    return outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def one_file(directory: Path, pattern: str, name: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if len(matches) != 1:
        raise FileNotFoundError(f"Expected exactly one {name}; found {len(matches)}")
    return matches[0]


def main() -> int:
    args = parse_args()
    work_dir = args.work_dir.resolve()
    intermediate = work_dir / "intermediate"
    output = work_dir / "reviewed" / "revised-indications.json"
    if output.exists() and not args.overwrite:
        raise FileExistsError(f"Reviewed revision output already exists: {output}")
    targets = load_json_object(intermediate / "revision-targets.json", "Revision targets")
    decisions = load_decisions(work_dir / "review" / "decisions.json")
    verify_decision_sources(decisions)
    revised = assemble_updated_indications(
        targets,
        load_json_object(
            one_file(intermediate, "*-claude_chunked_indication_fields.json", "indication fields"),
            "Indication fields",
        ),
        load_json_object(
            intermediate / "selected-revision-description-proposals.json",
            "Revision descriptions",
        ),
        load_json_list(
            intermediate / "selected-revision-date-evidence.json",
            "Revision dates",
        ),
        decisions,
    )
    write_json_atomic(output, revised)
    print(f"Wrote {output} ({len(revised)} revised indications)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
