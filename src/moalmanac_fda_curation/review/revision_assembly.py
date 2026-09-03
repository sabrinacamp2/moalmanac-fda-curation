"""Assemble targeted document, URL, and indication updates for a newer FDA label."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from ..core.artifacts import document_label_url, load_json_object, write_json_atomic
from .assembly import accepted_entry, indexed, load_json_list
from .decisions import load_decisions, verify_decision_sources


def one_by_id(items: list[dict[str, Any]], item_id: str, name: str) -> dict[str, Any]:
    """Return exactly one database record with the requested ID."""
    matches = [item for item in items if item.get("id") == item_id]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {name} with id {item_id}; found {len(matches)}")
    return matches[0]


def assemble_document_updates(
    existing_document: dict[str, Any],
    latest_document: dict[str, Any],
    existing_label_url: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Apply the allow-listed newer-label fields and materialize full records."""
    if existing_document.get("id") != latest_document.get("id"):
        raise ValueError("Existing and latest document IDs do not match")
    document_updates = {
        "publication_date": latest_document.get("publication_date"),
        "description": latest_document.get("description"),
    }
    if not all(isinstance(value, str) and value for value in document_updates.values()):
        raise ValueError("Latest document is missing publication_date or description")
    latest_label_url = document_label_url(latest_document)
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
    parser.add_argument("--database-dir", type=Path, required=True)
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
    reviewed_dir = work_dir / "reviewed"
    outputs = {
        "indications": reviewed_dir / "revised-indications.json",
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
    database_dir = args.database_dir.resolve() / "referenced"
    documents = load_json_list(database_dir / "documents.json", "Documents")
    urls = load_json_list(database_dir / "urls.json", "URLs")
    latest_document = load_json_object(
        intermediate / "document.proposal.json", "Latest document proposal"
    )
    existing_document = one_by_id(documents, targets["document_id"], "document")
    label_url_id = next(
        (item for item in existing_document.get("urls") or [] if str(item).endswith(":label")),
        None,
    )
    if not label_url_id:
        raise ValueError(f"{existing_document['id']} does not reference a label URL")
    document_patch, revised_document, url_patch, revised_url = assemble_document_updates(
        existing_document,
        latest_document,
        one_by_id(urls, label_url_id, "URL"),
    )
    for key, payload in (
        ("indications", revised),
        ("document_patch", document_patch),
        ("document", revised_document),
        ("url_patch", url_patch),
        ("url", revised_url),
    ):
        write_json_atomic(outputs[key], payload)
        print(f"Wrote {outputs[key]}")
    print(f"Assembled {len(revised)} revised indications")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
