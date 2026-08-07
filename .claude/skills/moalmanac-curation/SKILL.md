---
name: moalmanac-curation
description: Curate pinned FDA oncology product labels into evidence-backed MOAlmanac document and indication drafts. Use when a collaborator asks Claude Code to start, resume, inspect, explain, review, correct, validate, or prepare database changes for an FDA label curation, including document metadata, biomarker-relevant indications, descriptions, historical label changelogs, and initial approval dates.
---

# MOAlmanac curation

Collaborate with the curator rather than running a blind pipeline. Use the existing
scripts as tools, inspect their artifacts, show raw provenance, answer questions,
and pause at meaningful review gates.

## Locate the workspace

Use the installable `moalmanac-curation` command in this repository. A sibling
`moalmanac-db` checkout is optional until database comparison or publication.
Resolve actual paths before running commands. Read
[references/workflow-tools.md](references/workflow-tools.md) before invoking a
workflow command.

## Establish the curation target

Obtain an FDA application number and pinned label URL. Never silently replace the
pinned label with a newer label or openFDA label text. Preserve the label URL, date,
and application number as provenance.

Create or reuse a dedicated output directory. Inspect existing artifacts before
deciding which tool to run. Explain any reuse or regeneration that could affect API
cost or provenance.

## Curate interactively

Use this normal progression, but adapt it to the curator's request and current state:

1. Prepare the document proposal.
2. Show proposed document fields beside the FDA-derived values. Ask the curator to
   accept or edit editorial fields such as company name.
3. Extract indication candidates and structured raw fields.
4. Inspect extraction quality before trusting model output.
5. Show each retained candidate beside its exact Section 1 source chunk. Let the
   curator accept, edit, or exclude it.
6. Generate descriptions only for accepted or provisionally retained indications.
7. Show the description beside the selected Clinical Studies span.
8. Build the Section 1 history and match initial approval events.
9. Show the proposed date with the earlier similar events and exact before/after
   label text. Treat curator judgment as authoritative.
10. Assemble and validate draft `document.json` and `indication.json` artifacts.

Do not interpret a successful script or valid JSON response as curator approval.
Do not force the curator through stages irrelevant to their question. If they ask
why a value was proposed, inspect the stored evidence and answer before proceeding.

## Apply curator changes

When asked to change a proposal, make the requested draft edit, show a concise diff,
cite the supporting raw evidence, and identify downstream artifacts that may now be
stale. For simple field-level corrections (e.g. normalizing a company name string),
edit the artifact JSON directly — never rerun a generation script solely to apply a
curator-supplied value, regardless of whether that script calls a paid API. Rerun a
script only when the change requires new derivation logic or upstream data, such as
a different label URL or a different application number.

Keep generated proposals, curator edits, and accepted values distinguishable in the
handoff. Never overwrite raw source artifacts to make them agree with a proposal.

## Enforce evidence quality

Read [references/review-standards.md](references/review-standards.md) when reviewing
indications, extraction quality, descriptions, or approval dates.

Stop and flag the label rather than improvising when:

- Section 1 is missing, implausibly short, or contains headings without body text;
- a model-generated indication lacks supporting raw label text;
- the PDF extraction is symbols or layout fragments;
- historical label coverage is incomplete for the proposed date; or
- a claimed approval event cannot be verified against the changelog JSON.

Do not substitute undated or differently dated label text as a fallback.

## Prepare publication safely

Validate final shapes against current `moalmanac-db` examples and show the complete
diff. Do not edit `moalmanac-db`, create a branch, commit, push, or open a pull
request unless the curator explicitly requests that action after reviewing the
draft. Treat publication as a separate approval boundary.

## Communicate for nontechnical curators

Lead with the proposed value and what needs review. Translate implementation errors
into curation consequences. Provide clickable file paths and small source excerpts
instead of directing the curator to inspect code. Keep detailed command output out
of the conversation unless it helps diagnose a problem.
