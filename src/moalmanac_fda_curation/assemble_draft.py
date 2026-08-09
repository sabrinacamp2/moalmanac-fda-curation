"""Assemble reviewed workflow artifacts into a MOAlmanac indication draft."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .workflow_artifacts import load_document_artifact, load_json_object, write_json_atomic


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document-json", type=Path, required=True)
    parser.add_argument("--indication-fields-json", type=Path, required=True)
    parser.add_argument("--descriptions-json", type=Path, required=True)
    parser.add_argument("--date-matches-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--include-all-indications",
        action="store_true",
        help="Include indications with null/empty raw_biomarkers. Defaults to biomarker candidates only.",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


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


def assemble(
    document: dict[str, Any],
    indication_payload: dict[str, Any],
    description_payload: dict[str, Any],
    date_matches: list[dict[str, Any]],
    include_all_indications: bool,
) -> list[dict[str, Any]]:
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
        if not include_all_indications and not item.get("raw_biomarkers"):
            continue
        if index not in description_by_index:
            raise ValueError(f"Missing description for retained indication {index}")
        if index not in date_by_index:
            raise ValueError(f"Missing approval-date result for retained indication {index}")
        date_result = date_by_index[index]
        verification = date_result.get("verification") or {}
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
        raise ValueError("No indications passed the assembly filter")
    return output


def main() -> int:
    args = parse_args()
    output_path = args.output.resolve()
    if output_path.exists() and not args.overwrite:
        raise FileExistsError(f"Output already exists: {output_path}. Use --overwrite to replace it.")
    document = load_document_artifact(args.document_json.resolve())
    indication_payload = load_json_object(args.indication_fields_json.resolve(), "Indication fields")
    description_payload = load_json_object(args.descriptions_json.resolve(), "Descriptions")
    date_matches = load_json_list(args.date_matches_json.resolve(), "Date matches")
    draft = assemble(
        document,
        indication_payload,
        description_payload,
        date_matches,
        args.include_all_indications,
    )
    write_json_atomic(output_path, draft)
    print(f"Wrote {output_path} ({len(draft)} indications)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
