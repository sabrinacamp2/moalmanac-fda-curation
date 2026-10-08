"""Assemble curator-reviewed moalmanac-db records for a first-time FDA curation."""

from __future__ import annotations

import argparse
import copy
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .decisions import load_decisions, verify_decision_sources
from ..core.artifacts import load_document_proposal, load_json_object, write_json_atomic
from ..core.moalmanac_records import (
    DEFAULT_CURATOR_AGENT_ID,
    FDA_AGENT_ID,
    FDA_APPROVAL_CONTRIBUTIONS,
    ContributionLedger,
    DatedDocuments,
    approval_status,
    indication_id,
    indication_record,
    initial_curation_description,
    load_database,
    require_known_agents,
    require_unused_ids,
    validate_approval,
)
from ..core.moalmanac_schemas import validate_records


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


def label_urls_by_date(intermediate: Path) -> dict[str, str]:
    """Map each label date in the run's Indications and Usage changelog to its label URL."""
    paths = sorted((intermediate / "section1-changelogs").glob("*-section1-changelog.json"))
    if len(paths) > 1:
        raise FileNotFoundError(f"Expected at most one label changelog; found {len(paths)}")
    if not paths:
        return {}
    events = load_json_object(paths[0], "Indications and Usage changelog").get("events") or []
    return {event["date"]: event["label_url"] for event in events}


def accepted_entry(entry: dict[str, Any] | None, name: str) -> dict[str, Any]:
    if not entry or entry.get("decision") not in {"accepted", "edited"}:
        raise ValueError(f"Missing explicit accepted/edited decision for {name}")
    return entry


def approval_proposal(
    date_match: dict[str, Any] | None, indication_text: str | None
) -> dict[str, Any]:
    """Return the approval date and status the pipeline proposes for review."""
    date_match = date_match or {}
    match = date_match.get("llm_match") or date_match.get("materialized_match") or {}
    event = (date_match.get("verification") or {}).get("matched_event") or {}
    return {
        "initial_approval_date": event.get("date") or match.get("approval_date_candidate"),
        "status": approval_status(indication_text or ""),
    }


def reviewed_approval(
    date_match: dict[str, Any] | None,
    indication_text: str | None,
    decision: dict[str, Any],
    name: str,
) -> dict[str, Any]:
    """Apply an approval decision; a verified event or a curator-supplied date is required."""
    overrides = decision.get("overrides") or {}
    verification = (date_match or {}).get("verification") or {}
    verified = bool(verification.get("verified") and verification.get("matched_event"))
    if not verified and "initial_approval_date" not in overrides:
        raise ValueError(f"Approval date for {name} is not verified")
    approval = {**approval_proposal(date_match, indication_text), **overrides}
    validate_approval(approval, name)
    return approval


def reviewed_values(
    indication: dict[str, Any],
    indication_overrides: dict[str, Any],
    description: dict[str, Any],
    description_overrides: dict[str, Any],
) -> dict[str, Any]:
    """Combine reviewed indication fields with the reviewed statement description."""
    reviewed_indication = {**indication, **indication_overrides}
    reviewed_description = {**description, **description_overrides}
    return {
        "indication": reviewed_indication.get("indication"),
        "raw_biomarkers": reviewed_indication.get("raw_biomarkers"),
        "raw_cancer_types": reviewed_indication.get("raw_cancer_types"),
        "raw_therapeutics": reviewed_indication.get("raw_therapeutics"),
        "statement_description": reviewed_description.get("statement_description"),
    }


def fda_approval_contribution(ledger: ContributionLedger, approval: dict[str, Any]) -> str:
    return ledger.reference(
        FDA_AGENT_ID,
        approval["initial_approval_date"],
        FDA_APPROVAL_CONTRIBUTIONS[approval["status"]],
    )


def assemble_reviewed(
    proposal: dict[str, Any],
    indication_payload: dict[str, Any],
    description_payload: dict[str, Any],
    date_matches: list[dict[str, Any]],
    decisions: dict[str, Any],
    database: dict[str, list[dict[str, Any]]],
    *,
    label_urls: dict[str, str],
    curator_agent_id: str = DEFAULT_CURATOR_AGENT_ID,
    contribution_date: str,
    contribution_description: str | None = None,
) -> dict[str, Any]:
    """Apply explicit decisions and build the records a new FDA curation adds.

    `label_urls` maps label dates from the run's label history to their URLs, so
    each indication can report a dated document for its initial approval label.
    """
    verify_decision_sources(decisions)
    document = copy.deepcopy(proposal["document"])
    document.update(accepted_entry(decisions.get("document"), "document").get("overrides") or {})
    indications = indication_payload.get("indications")
    if not isinstance(indications, list) or not all(isinstance(item, dict) for item in indications):
        raise ValueError("Indication fields artifact must contain an indications list")
    descriptions = indexed(description_payload.get("indications") or [], "description")
    dates = indexed(date_matches, "date match")

    reviewed = []
    for index, item in enumerate(indications):
        stages = decisions.get("indications", {}).get(str(index), {})
        indication_decision = stages.get("indication")
        if indication_decision and indication_decision.get("decision") == "excluded":
            continue
        if not indication_decision and not item.get("raw_biomarkers"):
            continue
        name = f"indication {index}"
        indication_decision = accepted_entry(indication_decision, name)
        description_decision = accepted_entry(stages.get("description"), f"{name} description")
        approval_decision = accepted_entry(stages.get("approval"), f"{name} approval")
        if index not in descriptions:
            raise ValueError(f"Missing description for retained indication {index}")
        if index not in dates:
            raise ValueError(f"Missing approval-date result for retained indication {index}")
        values = reviewed_values(
            item,
            indication_decision.get("overrides") or {},
            descriptions[index],
            description_decision.get("overrides") or {},
        )
        approval = reviewed_approval(dates[index], values["indication"], approval_decision, name)
        reviewed.append((values, approval))
    if not reviewed:
        raise ValueError("No indications have completed curator review")

    ledger = ContributionLedger(database["contributions"])
    curator_contribution = ledger.reference(
        curator_agent_id,
        contribution_date,
        contribution_description or initial_curation_description(document),
    )
    dated_documents = DatedDocuments(
        document, database["documents"], label_urls, contribution_date
    )
    records = [
        indication_record(
            record_id=indication_id(document["id"], number),
            reported_in=[
                document["id"],
                dated_documents.reference(approval["initial_approval_date"]),
            ],
            values=values,
            status=approval["status"],
            contributions=ledger.ordered(
                [curator_contribution, fda_approval_contribution(ledger, approval)]
            ),
        )
        for number, (values, approval) in enumerate(reviewed)
    ]
    urls = copy.deepcopy(proposal["urls"]) + dated_documents.new_urls
    require_unused_ids(
        [document, *dated_documents.new_documents], database["documents"], "documents"
    )
    require_unused_ids(urls, database["urls"], "urls")
    require_unused_ids(records, database["indications"], "indications")
    require_known_agents(
        [document["agent_id"], curator_agent_id, FDA_AGENT_ID], database["agents"]
    )
    return {
        "document": document,
        "dated_documents": dated_documents.new_documents,
        "urls": urls,
        "indications": records,
        "contributions": ledger.new_records,
    }


def add_contribution_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the options that describe this session's curator contribution."""
    parser.add_argument(
        "--curator-agent-id",
        default=DEFAULT_CURATOR_AGENT_ID,
        help="moalmanac-db agent credited with this curation.",
    )
    parser.add_argument(
        "--contribution-date",
        type=lambda value: datetime.strptime(value, "%Y-%m-%d").date().isoformat(),
        default=date.today().isoformat(),
        help="Date of the curator contribution, YYYY-MM-DD. Defaults to today.",
    )
    parser.add_argument(
        "--contribution-description",
        help=(
            "Curator-supplied contribution text. Defaults to an initial-curation summary "
            "for new indications and a revised-curation summary for replacements."
        ),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--database-dir", type=Path, required=True)
    add_contribution_arguments(parser)
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
    database_dir = args.database_dir.resolve()
    intermediate = work_dir / "intermediate"
    output_dir = work_dir / "reviewed"
    outputs = {
        "document": output_dir / "document.json",
        "dated_documents": output_dir / "dated-documents.json",
        "urls": output_dir / "urls.json",
        "indications": output_dir / "indication.json",
        "contributions": output_dir / "contributions.json",
    }
    existing = [path for path in outputs.values() if path.exists()]
    if existing and not args.overwrite:
        raise FileExistsError(
            "Reviewed output already exists. Use --overwrite only after curator approval: "
            + ", ".join(str(path) for path in existing)
        )
    assembled = assemble_reviewed(
        proposal=load_document_proposal(intermediate / "document.proposal.json"),
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
        database=load_database(database_dir),
        label_urls=label_urls_by_date(intermediate),
        curator_agent_id=args.curator_agent_id,
        contribution_date=args.contribution_date,
        contribution_description=args.contribution_description,
    )
    validate_records(
        database_dir,
        {
            "documents": [assembled["document"], *assembled["dated_documents"]],
            "urls": assembled["urls"],
            "indications": assembled["indications"],
            "contributions": assembled["contributions"],
        },
    )
    for key, path in outputs.items():
        write_json_atomic(path, assembled[key])
        count = f" ({len(assembled[key])} records)" if isinstance(assembled[key], list) else ""
        print(f"Wrote {path}{count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
