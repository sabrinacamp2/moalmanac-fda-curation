"""Validate assembled records against the JSON schemas shipped with moalmanac-db."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from .moalmanac_records import database_schema_dir


def schema_registry(schema_dir: Path) -> tuple[Registry, dict[str, dict[str, Any]]]:
    """Register every referenced-record schema by its `$id` and by table name."""
    schemas = {
        path.name.removesuffix(".schema.json"): json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(schema_dir.glob("*.schema.json"))
    }
    registry = Registry().with_resources(
        (
            schema["$id"],
            Resource.from_contents(schema, default_specification=DRAFT202012),
        )
        for schema in schemas.values()
        if "$id" in schema
    )
    return registry, schemas


def validate_records(
    database_dir: Path, records_by_table: dict[str, list[dict[str, Any]]]
) -> None:
    """Raise one error listing every schema violation in the assembled records."""
    registry, schemas = schema_registry(database_schema_dir(database_dir))
    problems = []
    for table, records in records_by_table.items():
        if table not in schemas:
            raise FileNotFoundError(
                f"moalmanac-db does not provide a referenced schema for {table}"
            )
        validator = Draft202012Validator(schemas[table], registry=registry)
        for record in records:
            for error in sorted(validator.iter_errors(record), key=lambda item: item.path):
                location = "/".join(str(part) for part in error.path) or "<record>"
                problems.append(
                    f"{table} {record.get('id', '<no id>')} {location}: {error.message}"
                )
    if problems:
        raise ValueError(
            "Assembled records do not match the moalmanac-db schemas:\n- "
            + "\n- ".join(problems)
        )
