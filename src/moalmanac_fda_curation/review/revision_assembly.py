"""Assemble moalmanac-db records for new and changed indications in a newer FDA label."""

from __future__ import annotations

import argparse
import copy
import itertools
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from ..core.artifacts import (
    load_document_proposal,
    load_json_object,
    proposal_label_url,
    write_json_atomic,
)
from ..core.moalmanac_records import (
    ContributionLedger,
    DatedDocuments,
    indication_id,
    indication_record,
    initial_curation_description,
    load_database,
    next_indication_number,
    require_known_agents,
    require_unused_ids,
    revised_curation_description,
)
from ..core.moalmanac_schemas import validate_records
from .assembly import (
    accepted_entry,
    add_contribution_arguments,
    fda_approval_contribution,
    indexed,
    label_urls_by_date,
    load_json_list,
    reviewed_approval,
    reviewed_values,
)
from .decisions import load_decisions, verify_decision_sources


def one_by_id(items: list[dict[str, Any]], item_id: str, name: str) -> dict[str, Any]:
    """Return exactly one database record with the requested ID."""
    matches = [item for item in items if item.get("id") == item_id]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {name} with id {item_id}; found {len(matches)}")
    return matches[0]


def assemble_document_updates(
    existing_document: dict[str, Any],
    latest_proposal: dict[str, Any],
    existing_label_url: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Apply the allow-listed newer-label fields and materialize full records."""
    latest_document = latest_proposal["document"]
    if existing_document.get("identification_number") != latest_document.get(
        "identification_number"
    ):
        raise ValueError("Existing and latest documents describe different applications")
    document_updates = {
        "publication_date": latest_document.get("publication_date"),
        "description": latest_document.get("description"),
    }
    if not all(isinstance(value, str) and value for value in document_updates.values()):
        raise ValueError("Latest document is missing publication_date or description")
    latest_label_url = proposal_label_url(latest_proposal)
    revised_document = copy.deepcopy(existing_document)
    revised_document.update(document_updates)
    revised_url = copy.deepcopy(existing_label_url)
    revised_url["url"] = latest_label_url
    return (
        {"document_id": existing_document["id"], "updates": document_updates},
        revised_document,
        {"url_id": existing_label_url["id"], "updates": {"url": latest_label_url}},
        revised_url,
    )


def has_use_latest_target(targets_payload: dict[str, Any], decisions: dict[str, Any]) -> bool:
    """Report whether any revision target was screened to use the latest label."""
    for target in targets_payload.get("targets") or []:
        index = target["latest_indication_index"]
        stages = decisions.get("indications", {}).get(str(index), {})
        if (stages.get("revision") or {}).get("decision") == "use_latest":
            return True
    return False


def has_accepted_new_candidate(
    new_candidates: list[dict[str, Any]], decisions: dict[str, Any]
) -> bool:
    """Report whether any newly discovered indication was accepted or edited."""
    for candidate in new_candidates:
        index = candidate["latest_indication_index"]
        stages = decisions.get("indications", {}).get(str(index), {})
        if (stages.get("indication") or {}).get("decision") in {"accepted", "edited"}:
            return True
    return False


def assemble_new_indications(
    new_candidates: list[dict[str, Any]],
    indication_payload: dict[str, Any],
    description_payload: dict[str, Any],
    date_matches: list[dict[str, Any]],
    decisions: dict[str, Any],
    *,
    document_id: str,
    numbers: Iterator[int],
    ledger: ContributionLedger,
    dated_documents: DatedDocuments,
    curator_contribution: Callable[[], str],
) -> list[dict[str, Any]]:
    """Build finished records for indications newly discovered this session.

    Numbers come from the caller rather than from the latest label's positional
    index, which may already be taken by an existing indication ID for this
    document (indexes are per-label, not stable across label revisions).
    """
    indications = indication_payload.get("indications") or []
    descriptions = indexed(description_payload.get("indications") or [], "description")
    dates = indexed(date_matches, "date match")

    outputs = []
    for candidate in new_candidates:
        index = candidate["latest_indication_index"]
        stages = decisions.get("indications", {}).get(str(index), {})
        indication_decision = stages.get("indication")
        if not indication_decision or indication_decision.get("decision") == "excluded":
            continue
        name = f"indication {index}"
        indication_decision = accepted_entry(indication_decision, name)
        description_decision = accepted_entry(stages.get("description"), f"{name} description")
        approval_decision = accepted_entry(stages.get("approval"), f"{name} approval")
        if index >= len(indications) or index not in descriptions or index not in dates:
            raise ValueError(f"New indication {index} is missing prepared curation evidence")
        values = reviewed_values(
            indications[index],
            indication_decision.get("overrides") or {},
            descriptions[index],
            description_decision.get("overrides") or {},
        )
        approval = reviewed_approval(dates[index], values["indication"], approval_decision, name)
        outputs.append(
            indication_record(
                record_id=indication_id(document_id, next(numbers)),
                reported_in=[
                    document_id,
                    dated_documents.reference(approval["initial_approval_date"]),
                ],
                values=values,
                status=approval["status"],
                contributions=ledger.ordered(
                    [curator_contribution(), fda_approval_contribution(ledger, approval)]
                ),
            )
        )
    return outputs


def assemble_replacement_indications(
    targets_payload: dict[str, Any],
    indication_payload: dict[str, Any],
    description_payload: dict[str, Any],
    date_matches: list[dict[str, Any]],
    decisions: dict[str, Any],
    *,
    document_id: str,
    numbers: Iterator[int],
    ledger: ContributionLedger,
    dated_documents: DatedDocuments,
    curator_contribution: Callable[[], str],
) -> list[tuple[str, dict[str, Any]]]:
    """Suggest a new record for each changed indication the curator chose to replace.

    Returns (replaced indication ID, new record) pairs. The new record holds the
    reviewed latest-label values and its own FDA approval contribution; the
    existing record is not changed.
    """
    indications = indication_payload.get("indications") or []
    descriptions = indexed(description_payload.get("indications") or [], "description")
    dates = indexed(date_matches, "date match")
    replacements = []
    for target in targets_payload.get("targets") or []:
        index = target["latest_indication_index"]
        stages = decisions.get("indications", {}).get(str(index), {})
        screening_decision = (stages.get("revision") or {}).get("decision")
        if screening_decision == "keep_existing":
            continue
        if screening_decision != "use_latest":
            raise ValueError(f"Revision screening for indication {index} is unresolved")
        name = f"indication {index}"
        description_decision = accepted_entry(stages.get("description"), f"{name} description")
        approval_decision = accepted_entry(stages.get("approval"), f"{name} approval")
        if index >= len(indications) or index not in descriptions or index not in dates:
            raise ValueError(f"Revision target {index} is missing prepared curation evidence")
        values = reviewed_values(
            indications[index],
            (stages.get("revision") or {}).get("overrides") or {},
            descriptions[index],
            description_decision.get("overrides") or {},
        )
        approval = reviewed_approval(dates[index], values["indication"], approval_decision, name)
        replacement = indication_record(
            record_id=indication_id(document_id, next(numbers)),
            reported_in=[
                document_id,
                dated_documents.reference(approval["initial_approval_date"]),
            ],
            values=values,
            status=approval["status"],
            contributions=ledger.ordered(
                [curator_contribution(), fda_approval_contribution(ledger, approval)]
            ),
        )
        replacements.append((target["existing_indication_id"], replacement))
    return replacements


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
        raise FileNotFoundError(f"Expected exactly one {name}; found {len(matches)}")
    return matches[0]


def main() -> int:
    args = parse_args()
    work_dir = args.work_dir.resolve()
    database_dir = args.database_dir.resolve()
    intermediate = work_dir / "intermediate"
    reviewed_dir = work_dir / "reviewed"
    outputs = {
        "new_indications": reviewed_dir / "new-indications.json",
        "replacements": reviewed_dir / "replacements.json",
        "dated_documents": reviewed_dir / "dated-documents.json",
        "urls": reviewed_dir / "urls.json",
        "contributions": reviewed_dir / "contributions.json",
        "document_patch": reviewed_dir / "document-update.json",
        "document": reviewed_dir / "revised-document.json",
        "url_patch": reviewed_dir / "url-update.json",
        "url": reviewed_dir / "revised-url.json",
    }
    existing_outputs = [path for path in outputs.values() if path.exists()]
    if existing_outputs and not args.overwrite:
        raise FileExistsError(
            "Reviewed revision output already exists: "
            + ", ".join(str(path) for path in existing_outputs)
        )
    database = load_database(database_dir)
    targets = load_json_object(intermediate / "revision-targets.json", "Revision targets")
    decisions = load_decisions(work_dir / "review" / "decisions.json")
    verify_decision_sources(decisions)
    indication_fields = load_json_object(
        one_file(intermediate, "*-claude_chunked_indication_fields.json", "indication fields"),
        "Indication fields",
    )
    latest_proposal = load_document_proposal(intermediate / "document.proposal.json")
    document_id = targets["document_id"]
    existing_document = one_by_id(database["documents"], document_id, "document")
    ledger = ContributionLedger(database["contributions"])
    dated_documents = DatedDocuments(
        existing_document,
        database["documents"],
        label_urls_by_date(intermediate),
        args.contribution_date,
    )
    numbers = itertools.count(next_indication_number(database["indications"], document_id))

    def curator_contribution(default_description: str) -> Callable[[], str]:
        return lambda: ledger.reference(
            args.curator_agent_id,
            args.contribution_date,
            args.contribution_description or default_description,
        )

    if has_use_latest_target(targets, decisions):
        revision_descriptions = load_json_object(
            intermediate / "selected-revision-description-proposals.json",
            "Revision descriptions",
        )
        revision_dates = load_json_list(
            intermediate / "selected-revision-date-evidence.json",
            "Revision dates",
        )
    else:
        revision_descriptions = {"indications": []}
        revision_dates = []
    replacements = assemble_replacement_indications(
        targets,
        indication_fields,
        revision_descriptions,
        revision_dates,
        decisions,
        document_id=document_id,
        numbers=numbers,
        ledger=ledger,
        dated_documents=dated_documents,
        curator_contribution=curator_contribution(
            revised_curation_description(
                existing_document, latest_proposal["document"]["publication_date"]
            )
        ),
    )
    replacement_links = [
        {"indication_id": record["id"], "replaces": replaced_id}
        for replaced_id, record in replacements
    ]

    match_payload = load_json_object(
        intermediate / "indication-matches.json", "Indication reconciliation artifact"
    )
    new_candidates = match_payload.get("new_indication_candidates") or []
    if new_candidates and has_accepted_new_candidate(new_candidates, decisions):
        new_descriptions = load_json_object(
            intermediate / "selected-description-proposals.json",
            "New indication descriptions",
        )
        new_dates = load_json_list(
            intermediate / "selected-approval-evidence.json", "New indication dates"
        )
    else:
        new_descriptions = {"indications": []}
        new_dates = []
    new_indications = [record for _, record in replacements] + assemble_new_indications(
        new_candidates,
        indication_fields,
        new_descriptions,
        new_dates,
        decisions,
        document_id=document_id,
        numbers=numbers,
        ledger=ledger,
        dated_documents=dated_documents,
        curator_contribution=curator_contribution(
            initial_curation_description(existing_document)
        ),
    )
    label_url_id = next(
        (item for item in existing_document.get("urls") or [] if str(item).endswith(":label")),
        None,
    )
    if not label_url_id:
        raise ValueError(f"{existing_document['id']} does not reference a label URL")
    document_patch, revised_document, url_patch, revised_url = assemble_document_updates(
        existing_document,
        latest_proposal,
        one_by_id(database["urls"], label_url_id, "URL"),
    )
    require_unused_ids(new_indications, database["indications"], "indications")
    require_unused_ids(dated_documents.new_urls, database["urls"], "urls")
    if ledger.new_records:
        require_known_agents(
            [record["agent_id"] for record in ledger.new_records], database["agents"]
        )
    validate_records(
        database_dir,
        {
            "documents": [revised_document, *dated_documents.new_documents],
            "urls": [revised_url, *dated_documents.new_urls],
            "indications": new_indications,
            "contributions": ledger.new_records,
        },
    )
    for key, payload in (
        ("new_indications", new_indications),
        ("replacements", replacement_links),
        ("dated_documents", dated_documents.new_documents),
        ("urls", dated_documents.new_urls),
        ("contributions", ledger.new_records),
        ("document_patch", document_patch),
        ("document", revised_document),
        ("url_patch", url_patch),
        ("url", revised_url),
    ):
        write_json_atomic(outputs[key], payload)
        print(f"Wrote {outputs[key]}")
    print(
        f"Assembled {len(new_indications)} new indications "
        f"({len(replacement_links)} replace existing indications)"
    )
    for link in replacement_links:
        print(f"{link['indication_id']} replaces {link['replaces']}")
    print(f"Assembled {len(dated_documents.new_documents)} new dated documents")
    print(f"Assembled {len(ledger.new_records)} new contributions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
