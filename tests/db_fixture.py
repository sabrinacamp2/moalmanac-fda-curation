"""Write a minimal moalmanac-db checkout for tests.

The schemas are trimmed copies of moalmanac-db's referenced schemas. They keep the
required fields, closed records, ID patterns, and status enums the tool relies on.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

ORGANIZATIONS = "(fda|ema|hse|hc|hpra)"

AGENTS = [
    {
        "id": "agent:user:vanallenlab",
        "type": "Agent",
        "agentType": "contributor",
        "name": "Van Allen Lab",
        "description": "Curators.",
    },
    {
        "id": "agent:org:fda",
        "type": "Agent",
        "agentType": "organization",
        "name": "U.S. Food and Drug Administration",
        "description": "Regulatory agency.",
    },
]

CONTRIBUTIONS = [
    {
        "id": "ctrb:vanallenlab:2024-10-30:0",
        "type": "Contribution",
        "agent_id": "agent:user:vanallenlab",
        "description": "Initial access of FDA approvals",
        "date": "2024-10-30",
    },
    {
        "id": "ctrb:fda:2020-01-01:0",
        "type": "Contribution",
        "agent_id": "agent:org:fda",
        "description": "Indication received traditional approval.",
        "date": "2020-01-01",
    },
]

DOCUMENT = {
    "id": "doc:fda:example",
    "type": "Document",
    "documentType": "Regulatory approval",
    "name": "Example (examplemab) [package insert]. FDA.",
    "title": None,
    "aliases": [],
    "description": (
        "Example Co. Example (examplemab) [package insert]. U.S. Food and Drug "
        "Administration website. https://example.test/old.pdf. Revised January 2024. "
        "Accessed February 1, 2024."
    ),
    "urls": ["url:fda:example:label", "url:fda:example:overview"],
    "doi": None,
    "pmid": None,
    "agent_id": "agent:org:fda",
    "company": "Example Co.",
    "drug_name_brand": "Example",
    "drug_name_generic": "examplemab",
    "first_publication_date": "2020-01-01",
    "identification_number": 123456,
    "publication_date": "2024-01-01",
    "status": "Active",
}

DATED_DOCUMENT = {
    **DOCUMENT,
    "id": "doc:fda:example:2020-01-01",
    "description": (
        "Example Co. Example (examplemab) [package insert]. U.S. Food and Drug "
        "Administration website. https://example.test/2020.pdf. Revised January 2020. "
        "Accessed October 6, 2026."
    ),
    "urls": ["url:fda:example:label:2020-01-01", "url:fda:example:overview"],
    "publication_date": "2020-01-01",
    "status": "Deprecated",
}

URLS = [
    {"id": "url:fda:example:label", "url": "https://example.test/old.pdf"},
    {"id": "url:fda:example:overview", "url": "https://example.test/overview"},
    {"id": "url:fda:example:label:2020-01-01", "url": "https://example.test/2020.pdf"},
]

INDICATION = {
    "id": "ind:fda:example:0",
    "type": "Indication",
    "description": "EXAMPLE is indicated for HER2-positive breast cancer.",
    "contributions": ["ctrb:vanallenlab:2024-10-30:0", "ctrb:fda:2020-01-01:0"],
    "reportedIn": ["doc:fda:example", "doc:fda:example:2020-01-01"],
    "status": "Approved",
    "statement_description": (
        "The U.S. Food and Drug Administration granted approval to examplemab for "
        "patients with HER2-positive breast cancer."
    ),
    "raw_biomarkers": "HER2-positive",
    "raw_cancer_types": "breast cancer",
    "raw_therapeutics": "Example (examplemab)",
    "superseded_by": [],
}


def latest_proposal(label_url: str = "https://example.test/latest.pdf") -> dict[str, Any]:
    """Return a document proposal for a newer label of the fixture document."""
    document = copy.deepcopy(DOCUMENT)
    document.update(
        {
            "description": (
                "Example Co. Example (examplemab) [package insert]. U.S. Food and Drug "
                f"Administration website. {label_url}. Revised January 2026. "
                "Accessed February 1, 2026."
            ),
            "publication_date": "2026-01-02",
        }
    )
    return {
        "document": document,
        "urls": [
            {"id": "url:fda:example:label", "url": label_url},
            {"id": "url:fda:example:overview", "url": "https://example.test/overview"},
        ],
    }


def nullable(kind: str) -> dict[str, Any]:
    return {"type": [kind, "null"]}


def closed(table: str, properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://moalmanac.org/schemas/referenced/{table}.schema.json",
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


SCHEMAS = {
    "contributions": closed(
        "contributions",
        {
            "id": {"type": "string", "pattern": r"^ctrb:[a-z]+:\d{4}-\d{2}-\d{2}:\d+$"},
            "type": {"const": "Contribution"},
            "agent_id": {"type": "string", "pattern": "^agent:(org|user):[a-z0-9]+$"},
            "description": {"type": "string"},
            "date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        },
    ),
    "documents": closed(
        "documents",
        {
            "id": {"type": "string", "pattern": f"^doc:{ORGANIZATIONS}:.+$"},
            "type": {"const": "Document"},
            "documentType": {"enum": ["Regulatory approval"]},
            "name": {"type": "string"},
            "title": nullable("string"),
            "aliases": {"type": "array", "items": {"type": "string"}},
            "description": {"type": "string"},
            "urls": {
                "type": "array",
                "items": {"type": "string", "pattern": f"^url:{ORGANIZATIONS}:.+$"},
            },
            "doi": nullable("string"),
            "pmid": nullable("string"),
            "agent_id": {"type": "string", "pattern": "^agent:(org|user):[a-z0-9]+$"},
            "company": {"type": "string"},
            "drug_name_brand": nullable("string"),
            "drug_name_generic": nullable("string"),
            "first_publication_date": nullable("string"),
            "identification_number": {"type": ["integer", "string", "null"]},
            "publication_date": nullable("string"),
            "status": {"enum": ["Active", "Deprecated"]},
        },
    ),
    "indications": closed(
        "indications",
        {
            "id": {"type": "string", "pattern": f"^ind:{ORGANIZATIONS}:.+$"},
            "type": {"const": "Indication"},
            "description": {"type": "string"},
            "contributions": {"type": "array", "items": {"type": "string"}},
            "reportedIn": {
                "type": "array",
                "minItems": 2,
                "maxItems": 2,
                "prefixItems": [
                    {"type": "string", "pattern": "^doc:fda:[^:]+$"},
                    {"type": "string", "pattern": r"^doc:fda:[^:]+:\d{4}-\d{2}-\d{2}$"},
                ],
            },
            "status": {"enum": ["Approved", "Accelerated", "Superseded", "Withdrawn"]},
            "statement_description": {"type": "string"},
            "raw_biomarkers": nullable("string"),
            "raw_cancer_types": {"type": "string"},
            "raw_therapeutics": {"type": "string"},
            "superseded_by": {"type": "array", "items": {"type": "string"}},
        },
    ),
    "urls": closed(
        "urls",
        {
            "id": {"type": "string", "pattern": f"^url:{ORGANIZATIONS}:.+$"},
            "url": {"type": "string"},
        },
    ),
}


def tables(**overrides: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Return in-memory database tables, replacing any supplied table."""
    result = {
        "agents": AGENTS,
        "contributions": CONTRIBUTIONS,
        "documents": [DOCUMENT, DATED_DOCUMENT],
        "indications": [INDICATION],
        "urls": URLS,
    }
    result.update(overrides)
    return copy.deepcopy(result)


def write_changelog(intermediate: Path, label_urls: dict[str, str]) -> Path:
    """Write a label changelog with one event per label date."""
    path = intermediate / "section1-changelogs" / "Example-nda123456-section1-changelog.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    events = [
        {
            "event_number": number,
            "date": label_date,
            "change_type": "insert",
            "label_url": label_url,
            "before_text": None,
            "after_text": "Example indication text.",
        }
        for number, (label_date, label_url) in enumerate(sorted(label_urls.items()), start=1)
    ]
    path.write_text(json.dumps({"events": events}), encoding="utf-8")
    return path


def write_database(root: Path, **overrides: list[dict[str, Any]]) -> Path:
    """Write the fixture tables and schemas under root and return root."""
    referenced = root / "referenced"
    schemas = root / "schemas" / "referenced"
    referenced.mkdir(parents=True, exist_ok=True)
    schemas.mkdir(parents=True, exist_ok=True)
    for table, records in tables(**overrides).items():
        (referenced / f"{table}.json").write_text(json.dumps(records), encoding="utf-8")
    for table, schema in SCHEMAS.items():
        (schemas / f"{table}.schema.json").write_text(json.dumps(schema), encoding="utf-8")
    return root
