"""Compare a newer FDA label with curated indications and identify new ones."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ..core.artifacts import load_json_object, write_json_atomic
from ..core.check_curation_preflight import check_curation_preflight
from ..core.curate_doc_from_drugsfda_endpoint import curate_document
from ..core.extract_indications_from_fda_label import (
    DEFAULT_MAX_TOKENS as EXTRACTION_MAX_TOKENS,
    DEFAULT_MODEL as EXTRACTION_MODEL,
    download_pdf_bytes,
    output_stem,
    write_bytes,
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


def required_database_paths(database_dir: Path) -> tuple[Path, Path, Path]:
    root = database_dir.resolve()
    documents = root / "referenced" / "documents.json"
    indications = root / "referenced" / "indications.json"
    urls = root / "referenced" / "urls.json"
    missing = [str(path) for path in (documents, indications, urls) if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "The supplied moalmanac-db path is missing required file(s): "
            + ", ".join(missing)
        )
    return documents, indications, urls


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


def print_new_indication_summary(
    mappings: list[dict[str, Any]], candidates: list[dict[str, Any]]
) -> None:
    """Report every unmatched indication and identify the curation subset."""
    candidate_indexes = {
        candidate["latest_indication_index"] for candidate in candidates
    }
    print(f"New label indications without an existing match: {len(mappings)}")
    for mapping in mappings:
        latest = mapping["latest_indication"]
        index = latest["latest_indication_index"]
        label = latest.get("review_label") or latest["indication"]
        biomarker = latest.get("raw_biomarkers") or "none"
        scope = "curation candidate" if index in candidate_indexes else "outside biomarker scope"
        print(f"New indication {index}: {label} | Biomarker: {biomarker} | {scope}")
    print(f"New indications eligible for curation: {len(candidates)}")
    if candidate_indexes:
        print("New indication indexes: " + ", ".join(map(str, sorted(candidate_indexes))))


def new_indication_review_markdown(
    preflight: dict[str, Any],
    mappings: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    *,
    label_markdown_path: Path,
    label_pdf_path: Path,
    reconciliation_path: Path,
    latest_indications_path: Path,
) -> str:
    """Create a compact verification surface for unmatched label indications."""
    candidate_indexes = {
        candidate["latest_indication_index"] for candidate in candidates
    }
    lines = [
        "# Newly identified label indications",
        "",
        f"- Application: {preflight['application_number']}",
        f"- Latest FDA label date: {preflight['latest_label_date']}",
        f"- Without an existing MOAlmanac match: {len(mappings)}",
        f"- Eligible for biomarker curation: {len(candidates)}",
    ]
    for mapping in mappings:
        latest = mapping["latest_indication"]
        index = latest["latest_indication_index"]
        label = latest.get("review_label") or f"Indication {index}"
        scope = (
            "curation candidate"
            if index in candidate_indexes
            else "outside biomarker scope"
        )
        indication = latest["indication"]
        lines.extend(
            [
                "",
                f"## {index} — {label}",
                "",
                f"- Biomarker: {latest.get('raw_biomarkers') or 'none'}",
                f"- Scope: {scope}",
                f"- Source chunk: {latest.get('source_chunk_index', 'not available')}",
                f"- Match assessment: {mapping.get('reason') or 'Not provided'}",
                "",
                "### Exact extracted indication",
                "",
                *(f"> {line}" for line in indication.splitlines()),
            ]
        )
    lines.extend(
        [
            "",
            "## Sources and artifacts",
            "",
            f"- [Latest FDA label Markdown](<{label_markdown_path}>)",
            f"- [Latest FDA label PDF](<{label_pdf_path}>)",
            f"- [Latest-label indication extraction](<{latest_indications_path}>)",
            f"- [Reconciliation JSON](<{reconciliation_path}>)",
            "",
        ]
    )
    return "\n".join(lines)


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "mapping"


def markdown_json(value: Any) -> list[str]:
    return ["```json", json.dumps(value, indent=2, ensure_ascii=False), "```"]


def table_value(value: Any) -> str:
    if value is None:
        return "Not available"
    return str(value).replace("|", "\\|").replace("\n", " ")


def match_review_filename(mapping: dict[str, Any], position: int) -> str:
    classification = mapping["classification"]
    identity = mapping.get("existing_indication_id")
    if identity is None:
        identity = f"latest-{mapping.get('latest_indication_index', position)}"
    return f"{slugify(classification)}-{slugify(str(identity))}.md"


def local_review_label_pdf(
    url: str,
    label_date: str,
    directory: Path,
    *,
    overwrite: bool,
) -> Path:
    """Download one review-source label to a stable local path."""
    source_name = Path(urlsplit(url).path).name
    filename = source_name if source_name.lower().endswith(".pdf") else "label.pdf"
    path = directory / f"{slugify(label_date)}-{filename}"
    if not path.exists() or overwrite:
        write_bytes(path, download_pdf_bytes(url), overwrite=overwrite)
    return path


def match_review_markdown(
    preflight: dict[str, Any],
    mapping: dict[str, Any],
    *,
    reconciliation_path: Path,
    latest_indications_path: Path,
    label_markdown_path: Path,
    curated_label_pdf_path: Path,
    initial_label_pdf_path: Path | None = None,
) -> str:
    classification = mapping["classification"]
    if classification not in {"not_found", "uncertain"}:
        raise ValueError("Match reviews are only generated for unresolved mappings")
    existing = mapping.get("existing_indication")
    latest = mapping.get("latest_indication")
    title = (
        "Existing indication not found in latest-label extraction"
        if classification == "not_found"
        else "Uncertain indication mapping"
    )
    lines = [
        f"# {title}",
        "",
        f"- Application: {preflight['application_number']}",
        f"- MOAlmanac curated label date: {preflight['curated_label_date']}",
        f"- Latest FDA label date: {preflight['latest_label_date']}",
        f"- Classification: `{classification}`",
        "",
        "## Mapping assessment",
        "",
        mapping.get("reason") or "Not provided",
    ]
    if classification == "not_found":
        lines.extend(
            [
                "",
                "This means no counterpart was identified in the latest extraction. It",
                "does not establish that FDA removed the indication.",
            ]
        )
    if isinstance(existing, dict):
        lines.extend(["", "## Existing MOAlmanac record", "", *markdown_json(existing)])
    if isinstance(latest, dict):
        lines.extend(["", "## Possible latest-label counterpart", "", *markdown_json(latest)])
    if classification == "uncertain":
        existing = existing if isinstance(existing, dict) else {}
        latest = latest if isinstance(latest, dict) else {}
        lines.extend(
            [
                "",
                "## Structured comparison",
                "",
                "| Field | Existing MOAlmanac | Latest-label candidate |",
                "|---|---|---|",
                f"| Biomarker | {table_value(existing.get('raw_biomarkers'))} | {table_value(latest.get('raw_biomarkers'))} |",
                f"| Cancer type | {table_value(existing.get('raw_cancer_type'))} | {table_value(latest.get('raw_cancer_type'))} |",
                f"| Therapeutics | {table_value(existing.get('raw_therapeutics'))} | {table_value(latest.get('raw_therapeutics'))} |",
            ]
        )
    initial_date = existing.get("initial_approval_date") if isinstance(existing, dict) else None
    initial_url = existing.get("initial_approval_url") if isinstance(existing, dict) else None
    show_initial_label = (
        initial_label_pdf_path is not None
        and initial_url != preflight.get("curated_label_url")
        and initial_url != preflight.get("latest_label_url")
    )
    lines.extend(
        [
            "",
            "## Review these",
            "",
            f"- [Previous curated label — {preflight['curated_label_date']}](<{curated_label_pdf_path}>)",
            f"- [Latest label — {preflight['latest_label_date']}](<{label_markdown_path}>)",
            "",
            "## More evidence",
            "",
            *(
                [f"- [Initial approval label — {initial_date}](<{initial_label_pdf_path}>)"]
                if show_initial_label
                else []
            ),
            f"- [Latest-label indication extraction](<{latest_indications_path}>)",
            f"- [Mapping details](<{reconciliation_path}>)",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    work_dir = args.work_dir.resolve()
    documents_path, indications_path, urls_path = required_database_paths(
        args.database_dir
    )
    intermediate = work_dir / "intermediate"
    review_dir = work_dir / "review"
    preflight_path = intermediate / "curation-status.json"
    reconciliation_path = intermediate / "indication-reconciliation.json"
    match_review_dir = review_dir / "indication-matches"
    review_label_dir = work_dir / "labels" / "review-sources"
    new_review_path = review_dir / "new-indications.md"

    preflight = check_curation_preflight(
        args.application_number, documents_path, urls_path
    )
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
    latest = indexed_latest_indications(latest_payload)
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
            select_new_indication_candidates(
                reconciliation,
                biomarker_only=not args.include_non_biomarker,
            )
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
    new_candidates = select_new_indication_candidates(
        reconciliation,
        biomarker_only=not args.include_non_biomarker,
    )
    groups = mapping_groups(reconciliation)
    exceptions = groups["not_found"] + groups["uncertain"]
    if exceptions:
        latest_label_pdf = work_dir / "labels" / f"{stem}.pdf"
        local_label_paths: dict[str, Path] = {
            preflight["latest_label_url"]: latest_label_pdf
        }

        def local_label(url: str, label_date: str) -> Path:
            if url not in local_label_paths:
                local_label_paths[url] = local_review_label_pdf(
                    url,
                    label_date,
                    review_label_dir,
                    overwrite=args.overwrite,
                )
            return local_label_paths[url]

        curated_label_pdf = local_label(
            preflight["curated_label_url"], preflight["curated_label_date"]
        )
        for position, mapping in enumerate(exceptions):
            existing_indication = mapping.get("existing_indication")
            initial_url = (
                existing_indication.get("initial_approval_url")
                if isinstance(existing_indication, dict)
                else None
            )
            initial_date = (
                existing_indication.get("initial_approval_date")
                if isinstance(existing_indication, dict)
                else None
            )
            initial_label_pdf = (
                local_label(initial_url, initial_date or "initial-approval")
                if isinstance(initial_url, str)
                else None
            )
            path = match_review_dir / match_review_filename(mapping, position)
            markdown = match_review_markdown(
                preflight,
                mapping,
                reconciliation_path=reconciliation_path,
                latest_indications_path=latest_indications_path,
                label_markdown_path=work_dir / "labels" / f"{stem}.md",
                curated_label_pdf_path=curated_label_pdf,
                initial_label_pdf_path=initial_label_pdf,
            )
            if path.exists() and not args.overwrite:
                if path.read_text(encoding="utf-8") != markdown:
                    raise FileExistsError(
                        f"Indication match review exists with different content: {path}"
                    )
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(markdown, encoding="utf-8")
            print(f"Indication mapping review: {path}")
        print("Curator review required before continuing.")
    else:
        print("All existing indications matched confidently.")
    if groups["new"]:
        new_review = new_indication_review_markdown(
            preflight,
            groups["new"],
            new_candidates,
            label_markdown_path=work_dir / "labels" / f"{stem}.md",
            label_pdf_path=work_dir / "labels" / f"{stem}.pdf",
            reconciliation_path=reconciliation_path,
            latest_indications_path=latest_indications_path,
        )
        if new_review_path.exists() and not args.overwrite:
            if new_review_path.read_text(encoding="utf-8") != new_review:
                raise FileExistsError(
                    f"New indication review exists with different content: {new_review_path}"
                )
        else:
            new_review_path.parent.mkdir(parents=True, exist_ok=True)
            new_review_path.write_text(new_review, encoding="utf-8")
        print(f"New indication review: {new_review_path}")
    print_new_indication_summary(groups["new"], new_candidates)
    print(f"Matched existing indications: {len(groups['matched'])}")
    print(f"Existing indications not found: {len(groups['not_found'])}")
    print(f"Uncertain mappings: {len(groups['uncertain'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
