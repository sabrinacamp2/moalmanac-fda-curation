"""Shared validation and metadata resolution for FDA workflow artifacts."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

OPENFDA_DRUGSFDA_URL = "https://api.fda.gov/drug/drugsfda.json"


def load_json_object(path: Path, artifact_name: str) -> dict[str, Any]:
    """Load one JSON object with an artifact-specific validation error."""
    with path.open(encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError(f"{artifact_name} at {path} must contain a JSON object")
    return payload


def partial_output_path(output_path: Path) -> Path:
    """Return the sidecar checkpoint path for one final JSON output."""
    return output_path.with_name(f"{output_path.stem}.partial.json")


def write_json_atomic(path: Path, payload: Any) -> None:
    """Atomically write JSON so interrupted checkpoints remain readable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def file_sha256(path: Path) -> str:
    """Return a stable fingerprint for checkpoint input validation."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_document_proposal(path: Path) -> dict[str, Any]:
    """Load a document proposal: one documents.json record plus its urls.json records."""
    proposal = load_json_object(path, "Document proposal")
    document = proposal.get("document")
    urls = proposal.get("urls")
    if not isinstance(document, dict) or not isinstance(urls, list) or not all(
        isinstance(item, dict) for item in urls
    ):
        raise ValueError(
            f"Document proposal at {path} must contain a document object and a urls list"
        )
    required_fields = {
        "id": str,
        "drug_name_brand": str,
        "drug_name_generic": str,
        "identification_number": int,
        "urls": list,
    }
    for field, expected_type in required_fields.items():
        if not isinstance(document.get(field), expected_type):
            raise ValueError(
                f"Document proposal at {path} must have {field!r} as "
                f"{expected_type.__name__}"
            )
    if not document["id"].startswith("doc:"):
        raise ValueError(f"Document proposal at {path} has an invalid document ID")
    url_ids = {item.get("id") for item in urls}
    missing = [ref for ref in document["urls"] if ref not in url_ids]
    if missing:
        raise ValueError(f"Document proposal at {path} cites undefined URLs: {missing}")
    return proposal


def proposal_label_url(proposal: dict[str, Any]) -> str:
    """Return the FDA label PDF URL cited by a document proposal."""
    document = proposal["document"]
    label_url = next(
        (
            item.get("url")
            for item in proposal["urls"]
            if item.get("id") in document["urls"]
            and str(item.get("id")).endswith(":label")
        ),
        None,
    )
    if (
        not isinstance(label_url, str)
        or urlparse(label_url).scheme not in {"http", "https"}
        or not urlparse(label_url).path.lower().endswith(".pdf")
    ):
        raise ValueError(f"{document['id']} does not cite a concrete FDA label PDF URL")
    return label_url


def same_url_path(first: str, second: str) -> bool:
    """Compare URL paths while ignoring HTTP/HTTPS differences."""
    return urlparse(first).path.lower() == urlparse(second).path.lower()


def fetch_application_candidate(application_number: str) -> dict[str, Any] | None:
    """Return one exact openFDA application record, or None when absent."""
    response = requests.get(
        OPENFDA_DRUGSFDA_URL,
        params={"search": f'application_number:"{application_number}"'},
        timeout=30,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    results = response.json().get("results", [])
    return results[0] if results else None


def record_label_urls(record: dict[str, Any]) -> list[str]:
    """Return all label URLs represented in one openFDA application record."""
    return [
        doc["url"]
        for submission in record.get("submissions", [])
        for doc in (submission.get("application_docs") or [])
        if doc.get("type") == "Label" and isinstance(doc.get("url"), str)
    ]


def resolve_document_application_number(proposal: dict[str, Any]) -> str:
    """Resolve an NDA/BLA/ANDA application number from a document proposal."""
    identification_number = f"{proposal['document']['identification_number']:06d}"
    label_url = proposal_label_url(proposal)
    matches: list[tuple[str, dict[str, Any]]] = []

    likely_bla = identification_number.startswith(("125", "761"))
    prefixes = (
        ("BLA", "NDA", "ANDA")
        if likely_bla
        else ("NDA", "BLA", "ANDA")
    )
    for prefix in prefixes:
        application_number = f"{prefix}{identification_number}"
        record = fetch_application_candidate(application_number)
        if record is not None:
            if any(
                same_url_path(label_url, url)
                for url in record_label_urls(record)
            ):
                return application_number
            matches.append((application_number, record))

    if not matches:
        raise ValueError(
            "Could not resolve an openFDA application for identification number "
            f"{identification_number}"
        )
    if len(matches) == 1:
        return matches[0][0]

    candidates = ", ".join(application_number for application_number, _ in matches)
    raise ValueError(
        f"Identification number {identification_number} is ambiguous: {candidates}"
    )
