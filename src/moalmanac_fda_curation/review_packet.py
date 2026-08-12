"""Build deterministic, stage-specific curator review files."""

from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path
from typing import Any

from .review_state import load_decisions
from .workflow_artifacts import load_document_artifact, load_json_object, write_json_atomic

STAGES = ("document", "candidates", "indication", "description", "approval")


def load_json_list(path: Path, name: str) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"{name} must be a JSON list of objects: {path}")
    return payload


def item_by_index(items: list[dict[str, Any]], index: int) -> dict[str, Any] | None:
    return next((item for item in items if item.get("indication_index") == index), None)


def display_name(indication: dict[str, Any], index: int) -> str:
    explicit = indication.get("review_label")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    parts = [indication.get("raw_biomarkers"), indication.get("raw_cancer_type")]
    compact = " — ".join(str(part).strip() for part in parts if part)
    return compact or f"Indication {index}"


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "indication"


def source_excerpt(
    source_text: str | None,
    indication: dict[str, Any],
    limit: int = 6000,
) -> str | None:
    """Return relevant source paragraphs without loading a whole broad chunk."""
    if not source_text or len(source_text) <= limit:
        return source_text
    paragraphs = [part.strip() for part in source_text.split("\n\n") if part.strip()]
    anchors = [indication.get("raw_biomarkers"), indication.get("raw_cancer_type")]
    anchors = [str(anchor).lower() for anchor in anchors if anchor]
    matches = [
        index
        for index, paragraph in enumerate(paragraphs)
        if any(anchor in paragraph.lower() for anchor in anchors)
    ]
    if not matches:
        return source_text[:limit].rstrip() + "\n\n[…open the full source artifact…]"
    selected_indexes: set[int] = set()
    for index in matches:
        selected_indexes.update(range(max(0, index - 1), min(len(paragraphs), index + 2)))
    excerpt = "\n\n".join(paragraphs[index] for index in sorted(selected_indexes))
    return excerpt[:limit].rstrip() + "\n\n[…open the full source artifact…]"


def apply_decision_overrides(value: dict[str, Any], decision: dict[str, Any] | None) -> dict[str, Any]:
    resolved = copy.deepcopy(value)
    if decision and decision.get("decision") == "edited":
        resolved.update(decision.get("overrides") or {})
    return resolved


def target_metadata(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "identification_number": document.get("identification_number"),
        "selected_label_date": document.get("publication_date"),
        "selected_label_url": next(
            (url for url in document.get("urls", []) if str(url).lower().endswith(".pdf")),
            None,
        ),
    }


def require_indication_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload or not isinstance(payload.get("indications"), list):
        raise ValueError("This review stage requires an indication-fields artifact")
    return payload


def build_stage_packet(
    stage: str,
    document: dict[str, Any],
    indication_payload: dict[str, Any] | None = None,
    indication_index: int | None = None,
    descriptions: dict[str, Any] | None = None,
    date_matches: list[dict[str, Any]] | None = None,
    decisions: dict[str, Any] | None = None,
    artifact_paths: dict[str, str] | None = None,
) -> dict[str, Any]:
    decisions = decisions or {"document": {}, "indications": {}}
    base = {
        "schema_version": 1,
        "stage": stage,
        "curation_target": target_metadata(document),
        "artifacts": artifact_paths or {},
    }
    if stage == "document":
        return {
            **base,
            "pipeline_document_proposal": document,
            "current_reviewed_document": apply_decision_overrides(
                document, decisions.get("document")
            ),
            "decision": decisions.get("document") or None,
        }

    indication_payload = require_indication_payload(indication_payload)
    indications = indication_payload["indications"]
    if stage == "candidates":
        source_chunks = indication_payload.get("source_chunks") or []
        return {
            **base,
            "candidates": [
                {
                    "indication_index": index,
                    "display_name": display_name(indication, index),
                    "pipeline_proposal": indication,
                    "fda_indications_and_usage_excerpt": source_excerpt(
                        next(
                            (
                                item.get("source_chunk_text")
                                for item in source_chunks
                                if item.get("source_chunk_index")
                                == indication.get("source_chunk_index")
                            ),
                            None,
                        ),
                        indication,
                        limit=1800,
                    ),
                    "decision": decisions.get("indications", {})
                    .get(str(index), {})
                    .get("indication"),
                }
                for index, indication in enumerate(indications)
            ],
        }

    if indication_index is None or not 0 <= indication_index < len(indications):
        raise ValueError(f"Stage {stage} requires a valid --indication-index")
    indication = indications[indication_index]
    stage_decisions = decisions.get("indications", {}).get(str(indication_index), {})
    reviewed_indication = apply_decision_overrides(
        indication, stage_decisions.get("indication")
    )
    common = {
        **base,
        "indication_index": indication_index,
        "display_name": display_name(reviewed_indication, indication_index),
        "pipeline_indication_proposal": indication,
        "current_reviewed_indication": reviewed_indication,
    }

    if stage == "indication":
        source_chunks = indication_payload.get("source_chunks") or []
        chunk = next(
            (
                item
                for item in source_chunks
                if item.get("source_chunk_index") == indication.get("source_chunk_index")
            ),
            None,
        )
        provenance = indication_payload.get("provenance") or {}
        return {
            **common,
            "fda_indications_and_usage_excerpt": source_excerpt(
                chunk.get("source_chunk_text") if chunk else None, indication
            ),
            "fda_indications_and_usage_source_chunk": chunk,
            "fda_highlights_source": {
                "drug_class_phrase": provenance.get("highlights_drug_class_phrase"),
                "full_text": provenance.get("highlights_indications_and_usage_text"),
                "used_by_pipeline": indication.get("highlights_drug_class_used", False),
            },
            "decision": stage_decisions.get("indication"),
        }

    if stage == "description":
        description = item_by_index((descriptions or {}).get("indications") or [], indication_index)
        if description is None:
            raise ValueError(f"No description proposal exists for indication {indication_index}")
        return {
            **common,
            "pipeline_description_proposal": description,
            "current_reviewed_description": apply_decision_overrides(
                description, stage_decisions.get("description")
            ),
            "decision": stage_decisions.get("description"),
        }

    approval = item_by_index(date_matches or [], indication_index)
    if approval is None:
        raise ValueError(f"No approval proposal exists for indication {indication_index}")
    match = approval.get("llm_match") or approval.get("materialized_match") or {}
    event = (approval.get("verification") or {}).get("matched_event") or {}
    reviewed_approval = apply_decision_overrides(
        {
            "initial_approval_date": event.get("date")
            or match.get("approval_date_candidate"),
            "initial_approval_url": event.get("label_url"),
        },
        stage_decisions.get("approval"),
    )
    return {
        **common,
        "pipeline_approval_proposal": approval,
        "current_reviewed_approval": reviewed_approval,
        "decision": stage_decisions.get("approval"),
    }


def blockquote(value: str | None) -> list[str]:
    if not value:
        return ["> Not available"]
    return [f"> {line}" if line else ">" for line in value.strip().splitlines()]


def artifact_links(packet: dict[str, Any]) -> list[str]:
    if not packet.get("artifacts"):
        return []
    return [
        "",
        "## Full artifacts",
        "",
        *(f"- [{name}](<{path}>)" for name, path in packet["artifacts"].items()),
    ]


def decision_json(packet: dict[str, Any]) -> list[str]:
    if not packet.get("decision"):
        return []
    return [
        "",
        "## Recorded curator decision",
        "",
        "```json",
        json.dumps(packet["decision"], indent=2),
        "```",
    ]


def resolved_edit_json(packet: dict[str, Any], resolved: dict[str, Any]) -> list[str]:
    """Show only fields changed by an explicitly recorded curator edit."""
    decision = packet.get("decision") or {}
    overrides = decision.get("overrides") or {}
    if decision.get("decision") != "edited" or not overrides:
        return []
    values = {field: resolved.get(field) for field in overrides}
    return [
        "",
        "## Resolved curator edit",
        "",
        "```json",
        json.dumps(values, indent=2),
        "```",
    ]


def document_markdown(packet: dict[str, Any]) -> str:
    target = packet["curation_target"]
    visible_proposal = copy.deepcopy(packet["pipeline_document_proposal"])
    visible_proposal.pop("urls", None)
    lines = [
        "# Document review",
        "",
        "## Curation target — FDA metadata",
        "",
        f"- FDA application identification number: {target.get('identification_number')}",
        f"- Selected label date: {target.get('selected_label_date')}",
        "",
        "## Pipeline proposal — generated locally from FDA metadata",
        "",
        "```json",
        json.dumps(visible_proposal, indent=2),
        "```",
        *resolved_edit_json(packet, packet["current_reviewed_document"]),
        *decision_json(packet),
        *artifact_links(packet),
    ]
    return "\n".join(lines) + "\n"


def candidates_markdown(packet: dict[str, Any]) -> str:
    lines = [
        "# Indication candidates",
        "",
        "Use this short list for a genomic-biomarker relevance gut check. Detailed source",
        "review happens one indication at a time for candidates that continue.",
    ]
    for candidate in packet["candidates"]:
        proposal = candidate["pipeline_proposal"]
        lines.extend(
            [
                "",
                f"## {candidate['display_name']}",
                "",
                *blockquote(proposal.get("indication")),
                "",
                f"- Biomarker: {proposal.get('raw_biomarkers') or 'null'}",
            ]
        )
        if candidate.get("decision"):
            lines.extend(["", f"Decision: `{candidate['decision'].get('decision')}`"])
    lines.extend(artifact_links(packet))
    return "\n".join(lines) + "\n"


def indication_markdown(packet: dict[str, Any]) -> str:
    proposal = packet["pipeline_indication_proposal"]
    highlights = packet["fda_highlights_source"]
    lines = [
        f"# {packet['display_name']} — indication review",
        "",
        "## FDA source — verbatim Indications and Usage",
        "",
        *blockquote(packet.get("fda_indications_and_usage_excerpt")),
    ]
    if highlights.get("used_by_pipeline") and highlights.get("drug_class_phrase"):
        lines.extend(
            [
                "",
                "## FDA source — verbatim Highlights phrase used by pipeline",
                "",
                *blockquote(highlights["drug_class_phrase"]),
            ]
        )
    lines.extend(
        [
            "",
            "## Pipeline proposal — model generated",
            "",
            *blockquote(proposal.get("indication")),
            "",
            f"- Biomarker: {proposal.get('raw_biomarkers') or 'null'}",
            f"- Cancer type: {proposal.get('raw_cancer_type') or 'null'}",
            f"- Therapeutics: {proposal.get('raw_therapeutics') or 'null'}",
            *resolved_edit_json(packet, packet["current_reviewed_indication"]),
            *decision_json(packet),
            *artifact_links(packet),
        ]
    )
    return "\n".join(lines) + "\n"


def description_markdown(packet: dict[str, Any]) -> str:
    proposal = packet["pipeline_description_proposal"]
    selections = proposal.get("supporting_label_section_selections") or []
    selected_span = selections[0].get("selected_span") if selections else None
    lines = [
        f"# {packet['display_name']} — description review",
        "",
        "## Indication being described — curator-reviewed when available",
        "",
        *blockquote(packet["current_reviewed_indication"].get("indication")),
        "",
        "## Pipeline description proposal — model generated",
        "",
        *blockquote(proposal.get("description")),
        "",
        "## FDA Clinical Studies source — verbatim, span selected by pipeline model",
        "",
        *blockquote(selected_span.get("text") if selected_span else None),
        "",
        f"- Pipeline says Clinical Studies detail was added: {proposal.get('clinical_detail_used', False)}",
        f"- Added detail: {proposal.get('clinical_detail_text') or 'None'}",
        f"- Claimed purpose: {proposal.get('clinical_detail_purpose') or 'None'}",
        *resolved_edit_json(packet, packet["current_reviewed_description"]),
        *decision_json(packet),
        *artifact_links(packet),
    ]
    return "\n".join(lines) + "\n"


def approval_markdown(packet: dict[str, Any]) -> str:
    approval = packet["pipeline_approval_proposal"]
    match = approval.get("llm_match") or approval.get("materialized_match") or {}
    verification = approval.get("verification") or {}
    event = verification.get("matched_event") or {}
    event_number = match.get("changelog_event_number")
    event_path = (packet.get("artifacts") or {}).get("selected changelog event")
    lines = [
        f"# {packet['display_name']} — initial approval review",
        "",
        "## Indication being dated — curator-reviewed when available",
        "",
        *blockquote(packet["current_reviewed_indication"].get("indication")),
        "",
        "## Pipeline selection — event selected by model",
        "",
        f"- Proposed date: {event.get('date') or match.get('approval_date_candidate') or 'unmatched'}",
        f"- Event: {event_number or 'unmatched'}",
        *(
            [f"- [Open Event {event_number} in the full local changelog](<{event_path}>)"]
            if event_path and event_number is not None
            else []
        ),
        f"- Model rationale: {match.get('why_this_event_is_full_match') or 'Not available'}",
        f"- Why earlier events were judged incomplete: {match.get('why_earlier_events_are_incomplete') or 'Not available'}",
        f"- Missing or uncertain details: {json.dumps(match.get('missing_or_uncertain_details') or [])}",
        "",
        "## Deterministically retrieved event evidence",
        "",
        f"- Structural verification: {'passed' if verification.get('verified') else 'not verified'}",
        "",
        "### Before — verbatim changelog text",
        "",
        *blockquote(match.get("matched_before_quote")),
        "",
        "### After — verbatim changelog text",
        "",
        *blockquote(match.get("matched_after_quote")),
        *resolved_edit_json(packet, packet["current_reviewed_approval"]),
        *decision_json(packet),
        *artifact_links(packet),
    ]
    return "\n".join(lines) + "\n"


MARKDOWN_BUILDERS = {
    "document": document_markdown,
    "candidates": candidates_markdown,
    "indication": indication_markdown,
    "description": description_markdown,
    "approval": approval_markdown,
}


def output_paths(output_dir: Path, stage: str, packet: dict[str, Any]) -> tuple[Path, Path]:
    if stage == "document":
        stem_dir, stem = output_dir, "document"
    elif stage == "candidates":
        stem_dir, stem = output_dir, "indication-candidates"
    else:
        stem_dir = output_dir / "indications" / slugify(packet["display_name"])
        stem = stage
    return stem_dir / f"{stem}.json", stem_dir / f"{stem}.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=STAGES, required=True)
    parser.add_argument("--document-json", type=Path, required=True)
    parser.add_argument("--indication-fields-json", type=Path)
    parser.add_argument("--indication-index", type=int)
    parser.add_argument("--descriptions-json", type=Path)
    parser.add_argument("--date-matches-json", type=Path)
    parser.add_argument("--decisions-json", type=Path)
    parser.add_argument("--label-pdf", type=Path)
    parser.add_argument("--label-markdown", type=Path)
    parser.add_argument("--changelog-markdown", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.stage != "document" and (not args.label_pdf or not args.label_markdown):
        raise ValueError(
            f"{args.stage} review requires --label-pdf and --label-markdown"
        )
    if args.stage == "approval" and not args.changelog_markdown:
        raise ValueError("approval review requires --changelog-markdown")
    required_local_sources = [
        path
        for path in (args.label_pdf, args.label_markdown, args.changelog_markdown)
        if path is not None
    ]
    missing_local_sources = [str(path) for path in required_local_sources if not path.is_file()]
    if missing_local_sources:
        raise FileNotFoundError(
            "Review source file(s) do not exist: " + ", ".join(missing_local_sources)
        )
    document_path = args.document_json.resolve()
    indication_path = args.indication_fields_json.resolve() if args.indication_fields_json else None
    descriptions_path = args.descriptions_json.resolve() if args.descriptions_json else None
    dates_path = args.date_matches_json.resolve() if args.date_matches_json else None
    decisions = load_decisions(args.decisions_json.resolve()) if args.decisions_json else None
    artifacts = {"document proposal": str(document_path)}
    for name, path in (
        ("indication proposals", indication_path),
        ("description proposals", descriptions_path),
        ("approval evidence", dates_path),
        ("label PDF", args.label_pdf.resolve() if args.label_pdf else None),
        ("label Markdown", args.label_markdown.resolve() if args.label_markdown else None),
    ):
        if path:
            artifacts[name] = str(path)
    if args.stage == "approval" and args.changelog_markdown:
        approval_items = load_json_list(dates_path, "Date matches") if dates_path else []
        approval_item = item_by_index(approval_items, args.indication_index)
        match = (
            (approval_item or {}).get("llm_match")
            or (approval_item or {}).get("materialized_match")
            or {}
        )
        event_number = match.get("changelog_event_number")
        suffix = f"#event-{event_number}" if event_number is not None else ""
        artifacts["selected changelog event"] = (
            f"{args.changelog_markdown.resolve()}{suffix}"
        )
    packet = build_stage_packet(
        stage=args.stage,
        document=load_document_artifact(document_path),
        indication_payload=(
            load_json_object(indication_path, "Indication fields") if indication_path else None
        ),
        indication_index=args.indication_index,
        descriptions=(
            load_json_object(descriptions_path, "Descriptions") if descriptions_path else None
        ),
        date_matches=load_json_list(dates_path, "Date matches") if dates_path else None,
        decisions=decisions,
        artifact_paths=artifacts,
    )
    json_path, markdown_path = output_paths(args.output_dir.resolve(), args.stage, packet)
    write_json_atomic(json_path, packet)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(MARKDOWN_BUILDERS[args.stage](packet), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
