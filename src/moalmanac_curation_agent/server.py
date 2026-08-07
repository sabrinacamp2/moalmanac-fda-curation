"""Dependency-free browser UI for the curation workflow prototype."""

from __future__ import annotations

import argparse
import html
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from .agent import ask_agent
from .workflow import (
    REVIEW_STAGES,
    STAGES,
    CurationStore,
    accept_current,
    accept_pending_edit,
    edit_current,
    export_bundle,
    jump_to_stage,
    reject_current,
    reject_pending_edit,
)


CSS = """
:root { --ink:#17211b; --muted:#68736c; --paper:#f7f7f2; --panel:#fff;
  --green:#1f6b4f; --green-soft:#e7f1eb; --gold:#9b6b16; --gold-soft:#fff5d9;
  --red:#9a3e38; --line:#dce1dc; }
* { box-sizing:border-box; }
body { margin:0; color:var(--ink); background:var(--paper); font:15px/1.5 Inter, ui-sans-serif, system-ui, sans-serif; }
header { height:68px; display:flex; align-items:center; justify-content:space-between; padding:0 28px;
  color:white; background:#173f32; }
header h1 { font-size:18px; margin:0; letter-spacing:.2px; }
.badge { padding:5px 10px; border-radius:999px; background:#315e50; font-size:12px; }
.layout { min-height:calc(100vh - 68px); display:grid; grid-template-columns:220px 380px minmax(0,1fr); }
aside { padding:26px 20px; border-right:1px solid var(--line); background:#f0f2ed; }
.conversation { position:sticky; top:0; height:calc(100vh - 68px); display:flex; flex-direction:column;
  padding:22px; border-right:1px solid var(--line); background:white; }
.messages { flex:1; overflow:auto; margin:14px -5px; padding:0 5px; }
.message { max-width:92%; margin:0 0 14px; padding:11px 13px; border-radius:12px; white-space:pre-wrap; }
.message.user { margin-left:auto; background:#173f32; color:white; }
.message.assistant { background:#eef2ee; }
.tool-trace { display:block; margin-top:7px; color:var(--muted); font-size:11px; }
.chat-form textarea { min-height:76px; resize:vertical; font-family:inherit; font-size:13px; }
.chat-form button { width:100%; margin-top:8px; }
.eyebrow { color:var(--muted); font-size:11px; font-weight:700; letter-spacing:.12em; text-transform:uppercase; }
.steps { margin:16px 0 28px; padding:0; list-style:none; }
.steps button { width:100%; padding:10px; border:0; border-radius:8px; color:var(--ink); background:transparent;
  text-align:left; cursor:pointer; }
.steps button:hover, .steps .active button { background:white; }
.step-dot { display:inline-grid; width:24px; height:24px; margin-right:8px; place-items:center; border:1px solid #aeb8b1; border-radius:50%; font-size:12px; }
.accepted .step-dot { color:white; border-color:var(--green); background:var(--green); }
.active .step-dot { color:var(--green); border:2px solid var(--green); background:white; }
main { max-width:1000px; width:100%; padding:34px 42px 80px; margin:0 auto; }
h2 { margin:4px 0 6px; font-family:Georgia,serif; font-size:30px; font-weight:500; }
h3 { margin:0 0 10px; font-size:15px; }
.subtitle { color:var(--muted); margin:0 0 24px; }
.card { margin:0 0 18px; padding:22px; border:1px solid var(--line); border-radius:12px; background:var(--panel); box-shadow:0 1px 2px #17211b0a; }
.grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
.field { padding:12px 0; border-bottom:1px solid #edf0ed; }
.field:last-child { border:0; }
.label { color:var(--muted); font-size:12px; font-weight:650; text-transform:uppercase; letter-spacing:.05em; }
.value { margin-top:3px; white-space:pre-wrap; }
.evidence { padding:14px; border-left:3px solid #83968b; border-radius:4px; background:#f4f6f3; white-space:pre-wrap; }
.note, .warning { margin:16px 0; padding:13px 15px; border-radius:8px; }
.note { color:#244b3d; background:var(--green-soft); }
.warning { color:#67460e; background:var(--gold-soft); }
.pending-edit { border:2px solid #c79539; background:#fffdf7; }
.diff { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin:10px 0 16px; }
.before, .after { padding:12px; border-radius:7px; white-space:pre-wrap; overflow-wrap:anywhere; }
.before { background:#f8e8e6; } .after { background:#e5f2e9; }
.timeline { margin:8px 0 0 8px; padding-left:20px; border-left:2px solid #cad2cc; }
.event { position:relative; margin:0 0 18px; }
.event:before { content:""; position:absolute; width:10px; height:10px; left:-26px; top:6px; border-radius:50%; background:#83968b; }
.event.recommended:before { background:var(--green); box-shadow:0 0 0 4px #dcebe3; }
.event strong { display:block; }
.actions { position:sticky; bottom:0; display:flex; gap:10px; justify-content:flex-end; padding:16px 0;
  background:linear-gradient(#f7f7f200, var(--paper) 25%); }
button, .button { padding:9px 14px; border:1px solid #aeb8b1; border-radius:8px; background:white; cursor:pointer; font-weight:650; }
.primary { color:white; border-color:var(--green); background:var(--green); }
.danger { color:var(--red); }
textarea { width:100%; min-height:360px; padding:14px; border:1px solid #aeb8b1; border-radius:8px; font:13px/1.45 ui-monospace, monospace; }
.activity-list { margin:15px 0; padding:0; list-style:none; }
.activity-list li { margin-bottom:16px; color:#3f4b44; font-size:13px; }
.activity-list time { display:block; color:#849087; font-size:11px; }
pre { overflow:auto; padding:16px; border-radius:8px; background:#15231d; color:#dfece4; font-size:12px; }
a { color:var(--green); }
details.source { margin-top:16px; border:1px solid var(--line); border-radius:8px; }
details.source summary { padding:12px 14px; cursor:pointer; font-weight:650; }
details.source .evidence { margin:0 14px 14px; }
@media(max-width:1100px) { .layout { grid-template-columns:200px 330px minmax(0,1fr); } main { padding:28px 24px 70px; } }
@media(max-width:850px) { .layout { display:block; } aside { border:0; } .conversation { position:relative; height:520px; border-bottom:1px solid var(--line); } main { padding:24px 18px 70px; } .grid { grid-template-columns:1fr; } }
"""


def esc(value: object) -> str:
    return html.escape(str(value))


def fields(values: dict) -> str:
    return "".join(
        f'<div class="field"><div class="label">{esc(key.replace("_", " "))}</div>'
        f'<div class="value">{esc(value)}</div></div>'
        for key, value in values.items()
    )


def stage_title(stage: str) -> str:
    return stage.replace("_", " ").title()


def sidebar(state: dict) -> str:
    rows = []
    for stage in STAGES:
        if stage == "source":
            status = "accepted"
        elif stage == "final":
            status = "accepted" if state["current_stage"] == "final" else ""
        else:
            status = state["reviews"][stage]["status"]
        active = " active" if state["current_stage"] == stage else ""
        icon = "✓" if status == "accepted" else "•"
        rows.append(
            f'<li class="{status}{active}"><form method="post" action="/stage">'
            f'<input type="hidden" name="stage" value="{stage}">'
            f'<button><span class="step-dot">{icon}</span>{stage_title(stage)}</button></form></li>'
        )
    return f"""
    <aside><div class="eyebrow">Workflow</div><ul class="steps">{''.join(rows)}</ul>
    <div class="eyebrow">Source</div><p><strong>{esc(state['data']['source']['application_number'])}</strong><br>
    Label date {esc(state['data']['source']['label_date'])}</p>
    <form method="post" action="/reset"><button class="danger">Reset prototype</button></form></aside>
    """


def chat_panel(state: dict) -> str:
    messages = "".join(
        f'<div class="message {esc(item["role"])}">{esc(item["content"])}'
        + (
            f'<span class="tool-trace">Inspected: {esc(", ".join(item.get("tools", [])))}</span>'
            if item.get("tools") else ""
        )
        + "</div>"
        for item in state.get("chat", [])
    )
    return f"""
    <section class="conversation"><div class="eyebrow">Ask the curation agent</div>
    <div class="messages">{messages}</div>
    <form class="chat-form" method="post" action="/chat">
      <textarea name="question" placeholder="Why did you choose this date? Show me the raw evidence."></textarea>
      <button class="primary">Ask</button>
    </form></section>
    """


def document_view(state: dict) -> str:
    data = state["data"]
    return f"""
    <div class="grid"><section class="card"><h3>Proposed document</h3>{fields(data['document'])}</section>
    <section class="card"><h3>FDA source values</h3>{fields(data['document_evidence'])}</section></div>
    <div class="note"><strong>Agent note</strong><br>{esc(data['document_evidence']['agent_note'])}</div>
    """


def indications_view(state: dict) -> str:
    cards = []
    for index, item in enumerate(state["data"]["indications"], start=1):
        proposed = {k: v for k, v in item.items() if k not in {"source_text"}}
        cards.append(f"""
        <section class="card"><div class="eyebrow">Candidate {index}</div><h3>Proposed indication</h3>
        {fields(proposed)}<details class="source"><summary>View raw Section 1 evidence</summary>
        <div class="evidence">{esc(item['source_text'])}</div></details></section>
        """)
    return "".join(cards)


def descriptions_view(state: dict) -> str:
    return "".join(
        f'<section class="card"><h3>Proposed description</h3><p>{esc(item["description"])}</p>'
        f'<details class="source"><summary>View selected Clinical Studies evidence</summary><div class="evidence">{esc(item["evidence"])}</div></details></section>'
        for item in state["data"]["descriptions"]
    )


def dates_view(state: dict) -> str:
    blocks = []
    for item in state["data"]["approval_dates"]:
        events = "".join(
            f'<div class="event {"recommended" if event["recommended"] else ""}"><strong>{esc(event["date"])}'
            f'{" · recommended" if event["recommended"] else ""}</strong>{esc(event["summary"])}<br>'
            f'<a href="{esc(event["url"])}" target="_blank">Open FDA label</a></div>'
            for event in item["events"]
        )
        blocks.append(f"""
        <section class="card"><h3>Proposed initial approval</h3>
        {fields({'date': item['proposed_date'], 'url': item['proposed_url']})}
        <div class="warning"><strong>Needs review</strong><br>{esc(item['warning'])}</div>
        <h3>Candidate timeline</h3><div class="timeline">{events}</div></section>
        """)
    return "".join(blocks)


def final_view(state: dict) -> str:
    bundle = export_bundle(state)
    content = "".join(
        f'<section class="card"><h3>{esc(filename)}</h3><pre>{esc(json.dumps(value, indent=2))}</pre></section>'
        for filename, value in bundle.items()
    )
    return '<div class="note"><strong>Ready for export</strong><br>Every required review stage has been accepted. PR creation is intentionally out of scope for this prototype.</div>' + content


def pending_edits_view(state: dict) -> str:
    cards = []
    for edit in state.get("pending_edits", []):
        if edit.get("status") != "pending":
            continue
        changes = "".join(
            f'<div class="label">{esc(field.replace("_", " "))}</div><div class="diff">'
            f'<div class="before"><strong>Current</strong><br>{esc(change["before"])}</div>'
            f'<div class="after"><strong>Proposed</strong><br>{esc(change["after"])}</div></div>'
            for field, change in edit["changes"].items()
        )
        cards.append(f"""
        <section class="card pending-edit"><div class="eyebrow">Agent-proposed change · pending</div>
        <h3>{stage_title(edit['stage'])} edit</h3>{changes}
        <p><strong>Reason:</strong> {esc(edit['reason'])}</p>
        <details class="source"><summary>Evidence used for this edit</summary><div class="evidence">{esc(edit['evidence'])}</div></details>
        <div class="actions">
          <form method="post" action="/reject-edit"><input type="hidden" name="edit_id" value="{edit['id']}"><button class="danger">Reject change</button></form>
          <form method="post" action="/accept-edit"><input type="hidden" name="edit_id" value="{edit['id']}"><button class="primary">Accept change</button></form>
        </div></section>
        """)
    return "".join(cards)


def edit_view(state: dict) -> str:
    stage = state["current_stage"]
    payload = json.dumps(state["data"][stage], indent=2)
    return f"""
    <section class="card"><h3>Edit {stage_title(stage)} proposal as JSON</h3>
    <p class="subtitle">Saving an upstream edit invalidates any accepted downstream reviews.</p>
    <form method="post" action="/save"><textarea name="payload">{esc(payload)}</textarea>
    <div class="actions"><a class="button" href="/">Cancel</a><button class="primary">Save proposal</button></div></form></section>
    """


def actions(state: dict) -> str:
    if state["current_stage"] not in REVIEW_STAGES:
        return ""
    return """
    <div class="actions">
      <form method="post" action="/reject"><button class="danger">Reject</button></form>
      <a class="button" href="/edit">Edit</a>
      <form method="post" action="/accept"><button class="primary">Accept &amp; next</button></form>
    </div>
    """


def page(state: dict, editing: bool = False, error: str | None = None) -> str:
    stage = state["current_stage"]
    renderers = {
        "document": document_view,
        "indications": indications_view,
        "descriptions": descriptions_view,
        "approval_dates": dates_view,
        "final": final_view,
    }
    content = edit_view(state) if editing else renderers.get(stage, document_view)(state)
    error_html = f'<div class="warning"><strong>Could not save</strong><br>{esc(error)}</div>' if error else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
    <title>MOAlmanac Curation Assistant</title><style>{CSS}</style></head><body>
    <header><h1>MOAlmanac Curation Assistant</h1><span class="badge">{esc(state['data']['title'])} · Draft</span></header>
    <div class="layout">{sidebar(state)}{chat_panel(state)}<main><div class="eyebrow">Human-in-the-loop review</div>
    <h2>{stage_title(stage)}</h2><p class="subtitle">Review the proposal alongside its provenance. The agent cannot accept it for you.</p>
    {error_html}{pending_edits_view(state)}{content}{'' if editing else actions(state)}</main></div></body></html>"""


class Handler(BaseHTTPRequestHandler):
    store: CurationStore

    def _send(self, body: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _redirect(self, location: str = "/") -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def _form(self) -> dict[str, list[str]]:
        length = int(self.headers.get("Content-Length", "0"))
        return parse_qs(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802
        state = self.store.load()
        if self.path == "/":
            self._send(page(state))
        elif self.path == "/edit" and state["current_stage"] in REVIEW_STAGES:
            self._send(page(state, editing=True))
        elif self.path == "/health":
            self._send("ok")
        else:
            self._send("Not found", HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        state = self.store.load()
        try:
            if self.path == "/accept":
                accept_current(state)
            elif self.path == "/reject":
                reject_current(state)
            elif self.path == "/stage":
                jump_to_stage(state, self._form().get("stage", [""])[0])
            elif self.path == "/save":
                edit_current(state, self._form().get("payload", [""])[0])
            elif self.path == "/chat":
                question = self._form().get("question", [""])[0].strip()
                if not question:
                    raise ValueError("Enter a question for the curation agent.")
                answer, used_tools = ask_agent(state, question)
                state.setdefault("chat", []).extend(
                    [
                        {"role": "user", "content": question, "tools": []},
                        {"role": "assistant", "content": answer, "tools": used_tools},
                    ]
                )
            elif self.path in {"/accept-edit", "/reject-edit"}:
                edit_id = int(self._form().get("edit_id", ["0"])[0])
                if self.path == "/accept-edit":
                    accept_pending_edit(state, edit_id)
                else:
                    reject_pending_edit(state, edit_id)
            elif self.path == "/reset":
                self.store.reset()
                self._redirect()
                return
            else:
                self._send("Not found", HTTPStatus.NOT_FOUND)
                return
            self.store.save(state)
            self._redirect()
        except (json.JSONDecodeError, RuntimeError, TypeError, ValueError) as error:
            self._send(
                page(state, editing=self.path == "/save", error=str(error)),
                HTTPStatus.BAD_REQUEST,
            )

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--state-file",
        type=Path,
        default=Path(os.environ.get("MOALMANAC_CURATION_STATE", "data/curation.json")),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    Handler.store = CurationStore(args.state_file.resolve())
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"MOAlmanac Curation Assistant: http://{args.host}:{args.port}")
    print(f"State: {Handler.store.path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
