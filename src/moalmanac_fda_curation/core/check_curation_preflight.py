"""Check whether an FDA application is curated and has a newer label."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from .curate_doc_from_drugsfda_endpoint import (
    fda_date_to_iso,
    fetch_fda_record,
    get_label_version_fields,
)


def normalize_application_number(application_number: str) -> tuple[str, int]:
    """Return the openFDA form and numeric identifier for an application number."""
    normalized = re.sub(r"[\s-]+", "", application_number).upper()
    match = re.fullmatch(r"(ANDA|BLA|NDA)(\d+)", normalized)
    if match is None:
        raise ValueError(
            "Application number must include its type, for example BLA125554"
        )
    return normalized, int(match.group(2))


def load_documents(documents_path: Path) -> list[dict[str, Any]]:
    """Load the MOAlmanac documents collection."""
    with documents_path.open(encoding="utf-8") as file:
        documents = json.load(file)
    if not isinstance(documents, list):
        raise ValueError(f"Documents file at {documents_path} must contain a JSON list")
    return documents


def resolve_curated_label_url(document: dict[str, Any], urls_path: Path) -> str:
    """Return the concrete label URL referenced by a curated FDA document."""
    label_ref = next(
        (ref for ref in document.get("urls", []) if str(ref).endswith(":label")),
        None,
    )
    if label_ref is None:
        raise ValueError(f"{document.get('id')} does not reference a label URL")
    with urls_path.open(encoding="utf-8") as file:
        urls = json.load(file)
    url_by_id = {entry["id"]: entry["url"] for entry in urls}
    if label_ref not in url_by_id:
        raise ValueError(f"{urls_path} does not define {label_ref!r}")
    return url_by_id[label_ref]


def find_curated_fda_document(
    documents: list[dict[str, Any]], identification_number: int
) -> dict[str, Any] | None:
    """Find the single FDA document with the requested numeric application ID."""
    matches = [
        document
        for document in documents
        if document.get("agent_id") == "fda"
        and document.get("identification_number") == identification_number
    ]
    if len(matches) > 1:
        ids = ", ".join(str(document.get("id")) for document in matches)
        raise ValueError(
            f"Multiple FDA documents use identification number "
            f"{identification_number}: {ids}"
        )
    return matches[0] if matches else None


def check_curation_preflight(
    application_number: str,
    documents_path: Path,
    urls_path: Path,
    *,
    fetch_record: Callable[[str], dict[str, Any]] = fetch_fda_record,
) -> dict[str, Any]:
    """Report whether an application was curated and a newer label is available."""
    normalized_application, identification_number = normalize_application_number(
        application_number
    )
    document = find_curated_fda_document(
        load_documents(documents_path), identification_number
    )

    if document is None:
        return {
            "application_number": normalized_application,
            "previously_curated": False,
            "newer_label_available": None,
            "document_id": None,
            "curated_label_date": None,
            "curated_label_url": None,
            "latest_label_date": None,
            "latest_label_url": None,
        }

    curated_label_date = document.get("publication_date")
    if not isinstance(curated_label_date, str):
        raise ValueError(
            f"{document.get('id')} does not have a publication_date to compare"
        )
    curated_label_url = resolve_curated_label_url(document, urls_path)

    latest_label = get_label_version_fields(fetch_record(normalized_application))
    latest_label_date = fda_date_to_iso(latest_label["publication_date_raw"])

    return {
        "application_number": normalized_application,
        "previously_curated": True,
        "newer_label_available": latest_label_date > curated_label_date,
        "document_id": document["id"],
        "curated_label_date": curated_label_date,
        "curated_label_url": curated_label_url,
        "latest_label_date": latest_label_date,
        "latest_label_url": latest_label["label_url"],
    }
