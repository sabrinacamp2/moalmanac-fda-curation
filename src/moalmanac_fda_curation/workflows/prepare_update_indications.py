"""Compare a newer FDA label with curated indications and identify new ones."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

from ..core.artifacts import load_json_object, write_json_atomic
from ..core.check_curation_preflight import check_curation_preflight
from ..core.curate_doc_from_drugsfda_endpoint import curate_document
from ..core.extract_indications_from_fda_label import (
    DEFAULT_MAX_TOKENS as EXTRACTION_MAX_TOKENS,
    DEFAULT_MODEL as EXTRACTION_MODEL,
    output_stem,
)
from ..core.identify_new_indications import (
    DEFAULT_MODEL as RECONCILIATION_MODEL,
    indexed_latest_indications,
    load_existing_indications,
    map_existing_to_latest_indications,
    select_new_indication_candidates,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application-number", required=True)
    parser.add_argument("--database-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--extraction-model", default=EXTRACTION_MODEL)
    parser.add_argument("--reconciliation-model", default=RECONCILIATION_MODEL)
    parser.add_argument("--max-tokens", type=int, default=EXTRACTION_MAX_TOKENS)
    parser.add_argument("--include-non-biomarker", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def required_database_paths(database_dir: Path) -> tuple[Path, Path]:
    root = database_dir.resolve()
    documents = root / "referenced" / "documents.json"
    indications = root / "referenced" / "indications.json"
    missing = [str(path) for path in (documents, indications) if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "The supplied moalmanac-db path is missing required file(s): "
            + ", ".join(missing)
        )
    return documents, indications


def write_once(path: Path, payload: Any, *, overwrite: bool, name: str) -> None:
    if path.exists() and not overwrite:
        existing = load_json_object(path, name)
        if existing != payload:
            raise FileExistsError(
                f"{name} already exists with different content: {path}. "
                "Use --overwrite after confirming regeneration."
            )
        return
    write_json_atomic(path, payload)


def mapping_groups(result: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    groups = {key: [] for key in ("new", "matched", "not_found", "uncertain")}
    for mapping in result.get("mappings") or []:
        classification = mapping.get("classification")
        if classification in groups:
            groups[classification].append(mapping)
    return groups


def indication_text(mapping: dict[str, Any], side: str) -> str:
    value = mapping.get(side)
    if isinstance(value, dict) and isinstance(value.get("indication"), str):
        return value["indication"]
    return "Not available"


def exception_review_markdown(
    preflight: dict[str, Any],
    reconciliation: dict[str, Any],
    *,
    reconciliation_path: Path,
    latest_indications_path: Path,
) -> str:
    groups = mapping_groups(reconciliation)
    lines = [
        "# Indication reconciliation exceptions",
        "",
        f"- Application: {preflight['application_number']}",
        f"- MOAlmanac curated label date: {preflight['curated_label_date']}",
        f"- Latest FDA label date: {preflight['latest_label_date']}",
        f"- Reconciliation verified: {'yes' if reconciliation.get('verified') else 'no'}",
        "",
        f"- Existing indications not found: {len(groups['not_found'])}",
        f"- Uncertain mappings: {len(groups['uncertain'])}",
        "",
        "`not_found` means no counterpart was identified in the latest extraction. It is",
        "not evidence that FDA removed the indication.",
    ]
    sections = (
        ("Existing indications not found", "not_found"),
        ("Uncertain mappings", "uncertain"),
    )
    for title, classification in sections:
        lines.extend(["", f"## {title}", ""])
        if not groups[classification]:
            lines.append("None.")
            continue
        for mapping in groups[classification]:
            lines.extend(
                [
                    f"- Existing: {indication_text(mapping, 'existing_indication')}",
                    f"  - Latest: {indication_text(mapping, 'latest_indication')}",
                    f"  - Reason: {mapping.get('reason') or 'Not provided'}",
                ]
            )
    lines.extend(
        [
            "",
            "## Full artifacts",
            "",
            f"- [Reconciliation JSON](<{reconciliation_path}>)",
            f"- [Latest-label indication extraction](<{latest_indications_path}>)",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    work_dir = args.work_dir.resolve()
    documents_path, indications_path = required_database_paths(args.database_dir)
    intermediate = work_dir / "intermediate"
    review_dir = work_dir / "review"
    preflight_path = intermediate / "curation-preflight.json"
    reconciliation_path = intermediate / "indication-reconciliation.json"
    review_path = review_dir / "reconciliation-exceptions.md"

    preflight = check_curation_preflight(args.application_number, documents_path)
    if not preflight["previously_curated"]:
        raise ValueError("Update review requires a previously curated FDA application")
    if not preflight["newer_label_available"]:
        raise ValueError("Update review requires a newer approved FDA label")
    write_once(
        preflight_path,
        preflight,
        overwrite=args.overwrite,
        name="Curation status artifact",
    )

    document_path = intermediate / "document.proposal.json"
    if document_path.exists() and not args.overwrite:
        document = load_json_object(document_path, "Document proposal")
        if document.get("publication_date") != preflight["latest_label_date"]:
            raise FileExistsError(
                f"Document proposal does not use the latest label: {document_path}"
            )
    else:
        document_args = argparse.Namespace(
            application_number=preflight["application_number"],
            accessed_date=date.today(),
            company=None,
            label_url=preflight["latest_label_url"],
        )
        document = curate_document(document_args)
        write_json_atomic(document_path, document)

    stem = output_stem(document["drug_name_brand"], preflight["application_number"])
    latest_indications_path = intermediate / f"{stem}-claude_chunked_indication_fields.json"
    if not latest_indications_path.exists() or args.overwrite:
        command = [
            sys.executable,
            "-m",
            "moalmanac_fda_curation.core.extract_indications_from_fda_label",
            "--document-json",
            str(document_path),
            "--output-dir",
            str(work_dir),
            "--model",
            args.extraction_model,
            "--max-tokens",
            str(args.max_tokens),
        ]
        if args.overwrite:
            command.append("--overwrite")
        subprocess.run(command, check=True)

    latest_payload = load_json_object(
        latest_indications_path, "Latest indication artifact"
    )
    existing = load_existing_indications(indications_path, preflight["document_id"])
    latest = indexed_latest_indications(
        latest_payload, biomarker_only=not args.include_non_biomarker
    )
    if reconciliation_path.exists() and not args.overwrite:
        reconciliation = load_json_object(
            reconciliation_path, "Indication reconciliation artifact"
        )
    else:
        reconciliation = map_existing_to_latest_indications(
            existing,
            latest,
            model=args.reconciliation_model,
            max_tokens=args.max_tokens,
        )
        reconciliation["new_indication_candidates"] = (
            select_new_indication_candidates(reconciliation)
            if reconciliation["verified"]
            else []
        )
        reconciliation["document_id"] = preflight["document_id"]
        reconciliation["biomarker_only"] = not args.include_non_biomarker
        write_json_atomic(reconciliation_path, reconciliation)

    if not reconciliation.get("verified"):
        raise ValueError(
            f"Indication reconciliation is unverified: {reconciliation_path}"
        )
    groups = mapping_groups(reconciliation)
    exceptions = groups["not_found"] + groups["uncertain"]
    if exceptions:
        markdown = exception_review_markdown(
            preflight,
            reconciliation,
            reconciliation_path=reconciliation_path,
            latest_indications_path=latest_indications_path,
        )
        if review_path.exists() and not args.overwrite:
            if review_path.read_text(encoding="utf-8") != markdown:
                raise FileExistsError(
                    f"Exception review exists with different content: {review_path}"
                )
        else:
            review_path.parent.mkdir(parents=True, exist_ok=True)
            review_path.write_text(markdown, encoding="utf-8")
        print(f"Reconciliation exception review: {review_path}")
        print("Curator review required before continuing.")
    else:
        print("Reconciliation exceptions: none")
    new_indexes = [
        mapping["latest_indication"]["latest_indication_index"]
        for mapping in groups["new"]
    ]
    print(f"Possible new indications: {len(groups['new'])}")
    if new_indexes:
        print("New indication indexes: " + ", ".join(map(str, new_indexes)))
    print(f"Matched existing indications: {len(groups['matched'])}")
    print(f"Existing indications not found: {len(groups['not_found'])}")
    print(f"Uncertain mappings: {len(groups['uncertain'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
