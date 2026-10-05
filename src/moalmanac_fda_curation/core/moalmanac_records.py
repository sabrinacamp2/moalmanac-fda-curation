"""Read and construct records in the moalmanac-db referenced schema.

The curation pipeline describes an indication with working fields: `indication`
(the verbatim label text), `statement_description`, `raw_biomarkers`,
`raw_cancer_types`, `raw_therapeutics`, an `initial_approval_date`, and an
approval `status`. moalmanac-db stores the verbatim text as the indication's
`description` and the approval date as a dated contribution from the FDA agent.
This module is the only place that translates between the two shapes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

FDA_AGENT_ID = "agent:org:fda"
DEFAULT_CURATOR_AGENT_ID = "agent:user:vanallenlab"
APPROVAL_STATUSES = ("Approved", "Accelerated")
FDA_APPROVAL_CONTRIBUTIONS = {
    "Approved": "Indication received traditional approval.",
    "Accelerated": "Indication received accelerated approval.",
}
DATABASE_TABLES = ("agents", "contributions", "documents", "indications", "urls")
ACCELERATED_APPROVAL = re.compile(r"\baccelerated\s+approval\b", re.IGNORECASE)
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def database_table_path(database_dir: Path, table: str) -> Path:
    return database_dir / "referenced" / f"{table}.json"


def database_schema_dir(database_dir: Path) -> Path:
    return database_dir / "schemas" / "referenced"


def require_database(database_dir: Path) -> Path:
    """Resolve a moalmanac-db checkout and report every missing required input."""
    root = database_dir.resolve()
    required = [database_table_path(root, table) for table in DATABASE_TABLES]
    missing = [str(path) for path in required if not path.is_file()]
    if not database_schema_dir(root).is_dir():
        missing.append(str(database_schema_dir(root)))
    if missing:
        raise FileNotFoundError(
            "The supplied moalmanac-db path is missing required input(s): "
            + ", ".join(missing)
        )
    return root


def load_table(database_dir: Path, table: str) -> list[dict[str, Any]]:
    path = database_table_path(database_dir, table)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"{path} must contain a JSON list of objects")
    return payload


def load_database(database_dir: Path) -> dict[str, list[dict[str, Any]]]:
    root = require_database(database_dir)
    return {table: load_table(root, table) for table in DATABASE_TABLES}


def record_slug(brand_name: str) -> str:
    """Return the lowercase, hyphenated brand slug used in record IDs."""
    slug = re.sub(r"[^a-z0-9]+", "-", brand_name.lower()).strip("-")
    if not slug:
        raise ValueError(f"Cannot derive a record ID from brand name {brand_name!r}")
    return slug


def fda_document_id(brand_name: str) -> str:
    return f"doc:fda:{record_slug(brand_name)}"


def url_id(document_id: str, kind: str) -> str:
    return f"url:{document_id.removeprefix('doc:')}:{kind}"


def indication_id(document_id: str, number: int) -> str:
    return f"ind:{document_id.removeprefix('doc:')}:{number}"


def indication_number(record_id: str, document_id: str) -> int | None:
    """Return the trailing number of an indication ID that belongs to a document."""
    prefix = indication_id(document_id, 0).rsplit(":", 1)[0] + ":"
    suffix = record_id.removeprefix(prefix)
    return int(suffix) if record_id.startswith(prefix) and suffix.isdigit() else None


def next_indication_number(indications: list[dict[str, Any]], document_id: str) -> int:
    """Return the first indication number after every one the document already uses."""
    numbers = [
        number
        for record in indications
        if (number := indication_number(str(record.get("id", "")), document_id)) is not None
    ]
    return max(numbers, default=-1) + 1


def initial_curation_description(document: dict[str, Any]) -> str:
    return (
        f"Initial curation of FDA's approval of {document['drug_name_brand']} "
        f"({document['drug_name_generic']})."
    )


def revised_curation_description(document: dict[str, Any], label_date: str) -> str:
    return (
        f"Revised curation of FDA's approval of {document['drug_name_brand']} "
        f"({document['drug_name_generic']}) using the label published {label_date}."
    )


def approval_status(indication_text: str) -> str:
    """Return `Accelerated` when the label text states accelerated approval."""
    return "Accelerated" if ACCELERATED_APPROVAL.search(indication_text or "") else "Approved"


def validate_approval(approval: dict[str, Any], name: str) -> None:
    date = approval.get("initial_approval_date")
    if not isinstance(date, str) or not ISO_DATE.match(date):
        raise ValueError(f"{name} needs an initial_approval_date in YYYY-MM-DD form")
    if approval.get("status") not in APPROVAL_STATUSES:
        raise ValueError(f"{name} status must be one of {list(APPROVAL_STATUSES)}")


def existing_indication_view(
    record: dict[str, Any], contributions_by_id: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Express one database indication in the pipeline's working fields."""
    missing = [cid for cid in record["contributions"] if cid not in contributions_by_id]
    if missing:
        raise ValueError(f"{record['id']} references unknown contributions: {missing}")
    contributions = [contributions_by_id[cid] for cid in record["contributions"]]
    fda_dates = sorted(
        item["date"] for item in contributions if item["agent_id"] == FDA_AGENT_ID
    )
    return {
        "id": record["id"],
        "indication": record["description"],
        "statement_description": record["statement_description"],
        "raw_biomarkers": record["raw_biomarkers"],
        "raw_cancer_types": record["raw_cancer_types"],
        "raw_therapeutics": record["raw_therapeutics"],
        "status": record["status"],
        "initial_approval_date": fda_dates[0] if fda_dates else None,
        "contributions": contributions,
    }


def load_existing_indications(database_dir: Path, document_id: str) -> list[dict[str, Any]]:
    """Load the current (Approved or Accelerated) indications reported in a document."""
    contributions = {item["id"]: item for item in load_table(database_dir, "contributions")}
    records = [
        record
        for record in load_table(database_dir, "indications")
        if document_id in (record.get("reportedIn") or [])
        and record.get("status") in APPROVAL_STATUSES
    ]
    if not records:
        raise ValueError(f"No Approved or Accelerated indications report {document_id}")
    return [existing_indication_view(record, contributions) for record in records]


def indication_record(
    *,
    record_id: str,
    document_id: str,
    values: dict[str, Any],
    status: str,
    contributions: list[str],
) -> dict[str, Any]:
    """Build a database indication from reviewed working fields."""
    return {
        "id": record_id,
        "type": "Indication",
        "description": values["indication"],
        "contributions": contributions,
        "reportedIn": [document_id],
        "status": status,
        "statement_description": values["statement_description"],
        "raw_biomarkers": values.get("raw_biomarkers"),
        "raw_cancer_types": values.get("raw_cancer_types"),
        "raw_therapeutics": values.get("raw_therapeutics"),
        "superseded_by": [],
    }


def contribution_agent_key(agent_id: str) -> str:
    return agent_id.rsplit(":", 1)[-1]


class ContributionLedger:
    """Reuse matching database contributions and allocate IDs for new ones."""

    def __init__(self, existing: list[dict[str, Any]]) -> None:
        self._ids = {
            (item["agent_id"], item["date"], item["description"]): item["id"]
            for item in existing
        }
        self._dates = {item["id"]: item["date"] for item in existing}
        self._next_number: dict[str, int] = {}
        for item in existing:
            prefix, _, number = item["id"].rpartition(":")
            if number.isdigit():
                self._next_number[prefix] = max(
                    self._next_number.get(prefix, 0), int(number) + 1
                )
        self.new_records: list[dict[str, Any]] = []

    def reference(self, agent_id: str, date: str, description: str) -> str:
        key = (agent_id, date, description)
        if key in self._ids:
            return self._ids[key]
        prefix = f"ctrb:{contribution_agent_key(agent_id)}:{date}"
        number = self._next_number.get(prefix, 0)
        self._next_number[prefix] = number + 1
        record = {
            "id": f"{prefix}:{number}",
            "type": "Contribution",
            "agent_id": agent_id,
            "description": description,
            "date": date,
        }
        self._ids[key] = record["id"]
        self._dates[record["id"]] = date
        self.new_records.append(record)
        return record["id"]

    def ordered(self, contribution_ids: list[str]) -> list[str]:
        """Deduplicate contribution IDs and order them by date, newest first."""
        unique = list(dict.fromkeys(contribution_ids))
        unknown = [cid for cid in unique if cid not in self._dates]
        if unknown:
            raise ValueError(f"Unknown contribution IDs: {unknown}")
        return sorted(unique, key=lambda cid: self._dates[cid], reverse=True)


def require_unused_ids(
    records: list[dict[str, Any]], existing: list[dict[str, Any]], table: str
) -> None:
    taken = {item.get("id") for item in existing}
    collisions = [record["id"] for record in records if record["id"] in taken]
    if collisions:
        raise ValueError(f"moalmanac-db {table} already contains IDs: {collisions}")


def require_known_agents(agent_ids: list[str], agents: list[dict[str, Any]]) -> None:
    known = {agent.get("id") for agent in agents}
    unknown = sorted(set(agent_ids) - known)
    if unknown:
        raise ValueError(f"moalmanac-db agents does not define: {unknown}")
