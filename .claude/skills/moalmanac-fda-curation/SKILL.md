---
name: moalmanac-fda-curation
description: Guide evidence-backed review of new MOAlmanac entries from FDA oncology product labels. Use the repository CLI to select the latest approved label from an FDA application number, or an optional specific label URL, then prepare document metadata, extract biomarker-relevant indication proposals, generate descriptions, build label history, propose initial approval dates, and assemble draft document and indication JSON. Present pipeline outputs and provenance step by step, answer curator questions from stored evidence, and apply curator-approved edits.
---

# MOAlmanac FDA-label curation

Guide a curator through the repository's existing workflow. Treat pipeline values as
proposals and the curator as the final authority.

## Divide responsibilities

Let the pipeline perform specialized derivation:

- document metadata retrieval;
- Section 1 extraction and indication-field generation;
- Clinical Studies span selection and description drafting;
- historical Section 1 changelog construction;
- approval-event selection, deterministic hydration, and verification; and
- draft assembly and structural validation.

Use the harness to:

- inspect existing artifacts and choose the next appropriate command;
- explain the command, its expected artifacts, and whether it makes a paid call;
- present pipeline proposals with their stored provenance in a consistent review
  format;
- answer questions by retrieving the relevant source artifact;
- record explicit curator decisions and apply curator-supplied edits; and
- identify which downstream artifacts became stale.

Do not independently re-extract, redraft, or rematch a pipeline result during normal
review. Challenge a result only when the curator asks, a pipeline warning requires
investigation, or the displayed evidence reveals a specific discrepancy. Never
replace a pipeline artifact with an unstated harness inference.

## Locate the workspace

Use the installable `moalmanac-fda-curation` command in this repository. A sibling
`moalmanac-db` checkout is optional for checking current output shape and editorial
precedent. Resolve actual paths before running commands. Read
[references/workflow-tools.md](references/workflow-tools.md) before invoking a
workflow command.

## Establish the target

Obtain an FDA application number. By default, let `prepare-document` select the latest
approved label recorded for that application. Show the selected label date and URL to
the curator before downstream extraction.

If the curator does not know the application number, direct them to search by drug or
active ingredient in Drugs@FDA and use the product record's NDA or BLA number. Do not
guess the application number.

Accept a specific FDA label URL only when the curator wants a particular historical
version. Once a label has been selected, never silently replace it with a different
version or openFDA label text. Preserve the selected label URL, label date, and
application number as provenance.

Create or reuse a dedicated output directory. Inspect existing artifacts before
deciding which command to run. Explain reuse or regeneration that could affect API
cost or provenance.

This workflow prepares a new-entry draft. If the drug already has MOAlmanac content
and the task is to revise that content for a newer label, explain that the revision
workflow is not implemented and do not improvise database merging or replacement.
The tools may be used for investigation only when the curator explicitly requests
it.

## Review one stage at a time

Use this normal progression, adapting it to the curator's question and existing
artifacts:

1. Prepare the document proposal, then present the document review card.
2. Extract indication candidates, then present one indication review card at a time.
3. Generate descriptions only for accepted or provisionally retained indications,
   then present one description review card at a time.
4. Build the Section 1 history and match dates only for retained indications, then
   present one approval-date review card at a time.
5. Assemble and validate the draft only after the required proposals have explicit
   curator decisions.

Read [references/review-formats.md](references/review-formats.md) and use its review
cards. Lead with the proposed value and the decision needed. Keep raw command output
out of chat unless it helps diagnose a problem.

Do not interpret successful execution, verified matching, or valid JSON as curator
approval. Do not force the curator through stages irrelevant to their question. If
they ask why a value was proposed, show the stored evidence before proceeding.

## Record decisions

Keep a lightweight per-curation decision log at
`intermediate/<Brand>-<APPL>-review.md`. Record the pinned target and each explicit
decision: accepted, edited, excluded, or unresolved. For edits, preserve the original
proposal, accepted value, and a short curator note. Link to source artifacts instead
of copying every large source passage into the log.

Do not manufacture model reasoning or reconstruct a rejected draft that was not
preserved. The pipeline artifacts remain the record of generated proposals and raw
provenance; the review log records curator decisions.

## Apply curator changes

For a curator-supplied field correction, edit the draft artifact directly, show a
concise diff, cite the supporting evidence, and record the decision. Do not rerun a
generation command solely to apply a supplied value.

Rerun only when a change requires new derivation or upstream data, such as a different
label URL, application number, accepted indication meaning, or retained indication
set. Before a paid rerun, explain what will be discarded and obtain confirmation.
Use the cache/dependency guidance in
[references/workflow-tools.md](references/workflow-tools.md).

Never alter a raw label, extracted source section, changelog event, or other provenance
artifact to make it agree with a proposal.

## Enforce evidence quality

Read [references/review-standards.md](references/review-standards.md) when reviewing
indications, descriptions, or approval dates.

Stop and flag the label rather than improvising when:

- Section 1 is missing, implausibly short, or contains headings without body text;
- a proposed indication lacks supporting label text;
- PDF extraction is predominantly symbols or layout fragments;
- historical label coverage is incomplete for a proposed date; or
- a claimed approval event cannot be verified against the changelog JSON.

Do not substitute undated or differently dated label text as a fallback.

## Use database examples carefully

Read [references/moalmanac-examples.md](references/moalmanac-examples.md) when checking
final JSON shape or editorial style. Treat examples as patterns, not facts about the
current target. The pinned FDA label and current workflow artifacts remain
authoritative. If a sibling `moalmanac-db` is available, prefer its current records
over the copied examples.

## Stop at a draft

The current workflow does not add entries to `moalmanac-db`, update related tables,
create a branch, commit, push, or open a pull request. Do not perform any of those
actions unless the curator makes a separate explicit request and the required scope
and tooling are available.

## Communicate for nontechnical curators

Translate implementation errors into curation consequences. Provide clickable file
paths and short source excerpts instead of directing the curator to inspect code.
Offer clear decisions such as accept, edit, exclude, inspect more evidence, or ask a
question.
