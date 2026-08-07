"""Persistent review state and deterministic workflow controller."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .fixtures import fixture


STAGES = ("source", "document", "indications", "descriptions", "approval_dates", "final")
REVIEW_STAGES = STAGES[1:-1]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_state() -> dict[str, Any]:
    data = fixture()
    return {
        "version": 1,
        "current_stage": "document",
        "data": data,
        "reviews": {stage: {"status": "pending", "edited": False} for stage in REVIEW_STAGES},
        "chat": [
            {
                "role": "assistant",
                "content": "I prepared a Lynparza curation fixture. Ask me about any proposed field, its raw source evidence, or the approval-date timeline.",
                "tools": [],
            }
        ],
        "pending_edits": [],
        "edit_history": [],
        "activity": [
            {
                "time": _now(),
                "message": "Agent acquired the pinned label and prepared the document proposal.",
            }
        ],
    }


class CurationStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            state = new_state()
            self.save(state)
            return state
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def reset(self) -> dict[str, Any]:
        state = new_state()
        self.save(state)
        return state


def _log(state: dict[str, Any], message: str) -> None:
    state["activity"].append({"time": _now(), "message": message})


def _stage_index(stage: str) -> int:
    return STAGES.index(stage)


def decide_next_stage(state: dict[str, Any]) -> str:
    """Select the first review stage that has not been accepted."""
    for stage in REVIEW_STAGES:
        if state["reviews"][stage]["status"] != "accepted":
            return stage
    return "final"


def accept_current(state: dict[str, Any]) -> None:
    stage = state["current_stage"]
    if stage not in REVIEW_STAGES:
        return
    state["reviews"][stage]["status"] = "accepted"
    _log(state, f"Curator accepted the {stage.replace('_', ' ')} proposal.")
    next_stage = decide_next_stage(state)
    state["current_stage"] = next_stage
    if next_stage == "final":
        _log(state, "Agent validated the accepted stages and prepared the export preview.")
    else:
        _log(state, f"Agent advanced to {next_stage.replace('_', ' ')} review.")


def reject_current(state: dict[str, Any]) -> None:
    stage = state["current_stage"]
    if stage not in REVIEW_STAGES:
        return
    state["reviews"][stage]["status"] = "rejected"
    _log(state, f"Curator rejected the {stage.replace('_', ' ')} proposal; agent paused the workflow.")


def edit_current(state: dict[str, Any], payload: str) -> None:
    stage = state["current_stage"]
    if stage not in REVIEW_STAGES:
        return
    parsed = json.loads(payload)
    key = stage
    state["data"][key] = parsed
    state["reviews"][stage] = {"status": "pending", "edited": True}

    current_index = _stage_index(stage)
    invalidated = []
    for later_stage in REVIEW_STAGES:
        if _stage_index(later_stage) > current_index and state["reviews"][later_stage]["status"] == "accepted":
            state["reviews"][later_stage]["status"] = "pending"
            invalidated.append(later_stage.replace("_", " "))
    message = f"Curator edited the {stage.replace('_', ' ')} proposal."
    if invalidated:
        message += " Agent invalidated downstream reviews: " + ", ".join(invalidated) + "."
    _log(state, message)


def jump_to_stage(state: dict[str, Any], stage: str) -> None:
    if stage in REVIEW_STAGES or stage == "final":
        state["current_stage"] = stage


def _proposal_for_edit(state: dict[str, Any], stage: str, index: int | None) -> dict[str, Any]:
    proposal = state["data"][stage]
    if isinstance(proposal, list):
        if index is None or index < 0 or index >= len(proposal):
            raise ValueError(f"A valid indication_index is required for {stage}")
        return proposal[index]
    if not isinstance(proposal, dict):
        raise ValueError(f"The {stage} proposal cannot be edited")
    return proposal


def create_pending_edit(
    state: dict[str, Any],
    stage: str,
    changes: dict[str, Any],
    reason: str,
    evidence: str,
    indication_index: int | None = None,
) -> dict[str, Any]:
    """Record an agent-authored edit without changing the active proposal."""
    if stage not in REVIEW_STAGES:
        raise ValueError(f"Unsupported editable stage: {stage}")
    target = _proposal_for_edit(state, stage, indication_index)
    unknown = set(changes) - set(target)
    if unknown:
        raise ValueError(f"Unknown fields for {stage}: {sorted(unknown)}")
    actual_changes = {
        key: {"before": target.get(key), "after": value}
        for key, value in changes.items()
        if target.get(key) != value
    }
    if not actual_changes:
        raise ValueError("The requested edit does not change the proposal")
    pending = {
        "id": max((item["id"] for item in state.get("pending_edits", [])), default=0) + 1,
        "stage": stage,
        "indication_index": indication_index,
        "changes": actual_changes,
        "reason": reason,
        "evidence": evidence,
        "status": "pending",
        "created_at": _now(),
    }
    state.setdefault("pending_edits", []).append(pending)
    _log(state, f"Agent drafted edit {pending['id']} for {stage.replace('_', ' ')} review.")
    return pending


def _pending_edit(state: dict[str, Any], edit_id: int) -> dict[str, Any]:
    for edit in state.get("pending_edits", []):
        if edit["id"] == edit_id and edit["status"] == "pending":
            return edit
    raise ValueError(f"Pending edit {edit_id} was not found")


def accept_pending_edit(state: dict[str, Any], edit_id: int) -> None:
    edit = _pending_edit(state, edit_id)
    target = _proposal_for_edit(state, edit["stage"], edit.get("indication_index"))
    for key, change in edit["changes"].items():
        if target.get(key) != change["before"]:
            raise ValueError(f"Field {key} changed since this edit was proposed")
        target[key] = change["after"]
    edit["status"] = "accepted"
    edit["decided_at"] = _now()
    state.setdefault("edit_history", []).append(dict(edit))

    changed_index = _stage_index(edit["stage"])
    invalidated = []
    for stage in REVIEW_STAGES:
        if _stage_index(stage) >= changed_index and state["reviews"][stage]["status"] == "accepted":
            state["reviews"][stage]["status"] = "pending"
            invalidated.append(stage.replace("_", " "))
    state["current_stage"] = edit["stage"]
    message = f"Curator accepted agent edit {edit_id}."
    if invalidated:
        message += " Invalidated reviews: " + ", ".join(invalidated) + "."
    _log(state, message)


def reject_pending_edit(state: dict[str, Any], edit_id: int) -> None:
    edit = _pending_edit(state, edit_id)
    edit["status"] = "rejected"
    edit["decided_at"] = _now()
    state.setdefault("edit_history", []).append(dict(edit))
    _log(state, f"Curator rejected agent edit {edit_id}; the proposal was unchanged.")


def export_bundle(state: dict[str, Any]) -> dict[str, Any]:
    """Build the database-shaped preview from accepted proposals."""
    indications = []
    descriptions = {
        item["indication_id"]: item["description"] for item in state["data"]["descriptions"]
    }
    dates = {item["indication_id"]: item for item in state["data"]["approval_dates"]}
    for indication in state["data"]["indications"]:
        item = {key: value for key, value in indication.items() if key != "source_text"}
        item["document_id"] = state["data"]["document"]["id"]
        item["description"] = descriptions.get(item["id"])
        date = dates.get(item["id"], {})
        item["initial_approval_date"] = date.get("proposed_date")
        item["initial_approval_url"] = date.get("proposed_url")
        indications.append(item)
    return {"document.json": state["data"]["document"], "indication.json": indications}
