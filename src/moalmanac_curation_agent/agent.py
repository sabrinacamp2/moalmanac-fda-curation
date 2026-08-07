"""LLM tool-calling agent for questions about a curation draft."""

from __future__ import annotations

import json
import os
from typing import Any


SYSTEM_PROMPT = """You are a MOAlmanac curation assistant helping a collaborator
understand and verify a draft FDA-label curation. Use the available tools to inspect
the actual proposal and evidence before answering factual questions. Be concise but
specific. Distinguish source evidence from your interpretation. Surface uncertainty
and extraction warnings. Never claim that a curator accepted something unless the
state says so. When the curator explicitly asks you to change a proposal, use the
appropriate propose_*_edit tool to draft the change instead of merely describing it. A
proposed edit remains pending until the curator accepts it. You cannot approve or
publish records.
When discussing an approval date, compare the earliest clinically equivalent event;
do not treat headings, punctuation, hyphenation, or formatting as a new indication."""


TOOLS = [
    {
        "name": "get_curation_summary",
        "description": "Get the current workflow stage, review statuses, source label metadata, and proposal counts.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_document_proposal",
        "description": "Get the proposed document record and raw FDA document metadata used to create it.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_indication_proposal",
        "description": "Get one proposed indication, its structured fields, and exact Section 1 source evidence.",
        "input_schema": {
            "type": "object",
            "properties": {"indication_index": {"type": "integer", "minimum": 0}},
            "required": ["indication_index"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_description_evidence",
        "description": "Get the proposed description and the selected Clinical Studies evidence for one indication.",
        "input_schema": {
            "type": "object",
            "properties": {"indication_index": {"type": "integer", "minimum": 0}},
            "required": ["indication_index"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_approval_timeline",
        "description": "Get the proposed initial approval date, warnings, and historical candidate events for one indication.",
        "input_schema": {
            "type": "object",
            "properties": {"indication_index": {"type": "integer", "minimum": 0}},
            "required": ["indication_index"],
            "additionalProperties": False,
        },
    },
    {
        "name": "propose_document_edit",
        "description": "Draft a pending document edit explicitly requested by the curator. It is not applied until curator acceptance.",
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"}, "company": {"type": "string"},
                        "drug_name_brand": {"type": "string"}, "drug_name_generic": {"type": "string"},
                        "publication_date": {"type": "string"}, "status": {"type": "string"}
                    },
                    "additionalProperties": False,
                },
                "reason": {"type": "string"},
                "evidence": {"type": "string"},
            },
            "required": ["changes", "reason", "evidence"],
            "additionalProperties": False,
        },
    },
    {
        "name": "propose_indication_edit",
        "description": "Draft a pending edit to one indication explicitly requested by the curator.",
        "input_schema": {
            "type": "object",
            "properties": {
                "indication_index": {"type": "integer", "minimum": 0},
                "changes": {
                    "type": "object",
                    "properties": {
                        "indication": {"type": "string"}, "raw_biomarkers": {"type": ["string", "null"]},
                        "raw_cancer_type": {"type": ["string", "null"]}, "raw_therapeutics": {"type": ["string", "null"]}
                    },
                    "additionalProperties": False,
                },
                "reason": {"type": "string"}, "evidence": {"type": "string"},
            },
            "required": ["indication_index", "changes", "reason", "evidence"],
            "additionalProperties": False,
        },
    },
    {
        "name": "propose_description_edit",
        "description": "Draft a replacement description explicitly requested by the curator.",
        "input_schema": {
            "type": "object",
            "properties": {
                "indication_index": {"type": "integer", "minimum": 0},
                "description": {"type": "string"}, "reason": {"type": "string"}, "evidence": {"type": "string"},
            },
            "required": ["indication_index", "description", "reason", "evidence"],
            "additionalProperties": False,
        },
    },
    {
        "name": "propose_approval_date_edit",
        "description": "Draft a pending initial approval date and URL edit explicitly requested by the curator.",
        "input_schema": {
            "type": "object",
            "properties": {
                "indication_index": {"type": "integer", "minimum": 0},
                "proposed_date": {"type": "string", "description": "YYYY-MM-DD"},
                "proposed_url": {"type": "string"},
                "reason": {"type": "string"}, "evidence": {"type": "string"},
            },
            "required": ["indication_index", "proposed_date", "proposed_url", "reason", "evidence"],
            "additionalProperties": False,
        },
    },
]


def _indexed(values: list[dict[str, Any]], index: int) -> dict[str, Any]:
    if index < 0 or index >= len(values):
        return {"error": f"No indication exists at index {index}"}
    return values[index]


def execute_tool(state: dict[str, Any], name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute a bounded, read-only evidence tool."""
    data = state["data"]
    if name == "get_curation_summary":
        return {
            "current_stage": state["current_stage"],
            "reviews": state["reviews"],
            "source": data["source"],
            "counts": {
                "indications": len(data["indications"]),
                "descriptions": len(data["descriptions"]),
                "approval_dates": len(data["approval_dates"]),
            },
        }
    if name == "get_document_proposal":
        return {"proposal": data["document"], "source_values": data["document_evidence"]}
    index = arguments.get("indication_index", 0)
    if name == "get_indication_proposal":
        return _indexed(data["indications"], index)
    if name == "get_description_evidence":
        return _indexed(data["descriptions"], index)
    if name == "get_approval_timeline":
        return _indexed(data["approval_dates"], index)
    if name.startswith("propose_") and name.endswith("_edit"):
        from .workflow import create_pending_edit

        stage_by_tool = {
            "propose_document_edit": "document",
            "propose_indication_edit": "indications",
            "propose_description_edit": "descriptions",
            "propose_approval_date_edit": "approval_dates",
        }
        stage = stage_by_tool.get(name)
        if stage is None:
            return {"error": f"Unknown edit tool: {name}"}
        if name == "propose_description_edit":
            changes = {"description": arguments["description"]}
        elif name == "propose_approval_date_edit":
            changes = {
                "proposed_date": arguments["proposed_date"],
                "proposed_url": arguments["proposed_url"],
            }
        else:
            changes = arguments["changes"]
        return create_pending_edit(
            state,
            stage=stage,
            indication_index=arguments.get("indication_index"),
            changes=changes,
            reason=arguments["reason"],
            evidence=arguments["evidence"],
        )
    return {"error": f"Unknown tool: {name}"}


def _block_dict(block: Any) -> dict[str, Any]:
    if hasattr(block, "model_dump"):
        return block.model_dump()
    return {"type": getattr(block, "type", "text"), "text": getattr(block, "text", "")}


def ask_agent(state: dict[str, Any], question: str) -> tuple[str, list[str]]:
    """Let Claude choose evidence tools and answer a curator question."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Start the server from a shell where the key is exported."
        )
    try:
        from anthropic import Anthropic
    except ImportError as error:
        raise RuntimeError("The anthropic package is required for chat.") from error

    client = Anthropic()
    history = state.get("chat", [])[-8:]
    messages: list[dict[str, Any]] = [
        {"role": item["role"], "content": item["content"]}
        for item in history
        if item["role"] in {"user", "assistant"}
    ]
    messages.append({"role": "user", "content": question})
    used_tools: list[str] = []

    for _ in range(5):
        response = client.messages.create(
            model=os.environ.get("MOALMANAC_AGENT_MODEL", "claude-sonnet-4-5"),
            max_tokens=1200,
            temperature=0,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )
        blocks = [_block_dict(block) for block in response.content]
        tool_uses = [block for block in blocks if block.get("type") == "tool_use"]
        if not tool_uses:
            answer = "\n".join(
                block.get("text", "") for block in blocks if block.get("type") == "text"
            ).strip()
            return answer or "I could not produce an answer from the available evidence.", used_tools

        messages.append({"role": "assistant", "content": blocks})
        results = []
        for tool_use in tool_uses:
            name = tool_use["name"]
            used_tools.append(name)
            result = execute_tool(state, name, tool_use.get("input", {}))
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use["id"],
                    "content": json.dumps(result),
                }
            )
        messages.append({"role": "user", "content": results})

    raise RuntimeError("The agent exceeded the tool-call limit without answering.")
