---
name: moalmanac-fda-curation
description: Guide evidence-backed review of new MOAlmanac entries from FDA oncology product labels. Use the repository CLI to select an approved label, generate document and indication proposals, review one indication end-to-end with source provenance, record explicit curator decisions, and assemble reviewed document.json and indication.json outputs.
---

# Curate an FDA label for MOAlmanac

Use the pipeline for extraction, generation, matching, validation, and state changes.
Use the harness to orchestrate tools, present compact evidence, assess proposals, and
ask for curator decisions.

## Protect source and generated output

- Treat downloaded labels and every pipeline-generated artifact as immutable.
- Never edit generated JSON, Markdown, changelogs, or source files.
- Never infer approval from silence or from successful execution.
- Record a decision only after the curator explicitly accepts, edits, excludes, or
  marks the item unresolved.
- Use `record-decision` for every state change. Do not write decision files manually.
- When `--overwrite` would repeat an Anthropic API request, explain that additional API
  usage and obtain confirmation first.
- Never replace the selected label version or use openFDA label text as a fallback.

## Start safely

1. Read [references/workflow-tools.md](references/workflow-tools.md).
2. Check for `.venv` before installing anything. If it exists, activate and reuse it.
   Create `.venv` only when it is absent. Then run `moalmanac-fda-curation doctor`
   inside the active environment and resolve failures before curation.
3. Obtain the NDA or BLA application number. If unknown, direct the curator to search
   Drugs@FDA by drug or active ingredient; never guess it.
4. Use `prepare-document-review` without `--label-url` for the latest approved label.
   Use a specific FDA label URL only when the curator requests an earlier version.
5. Show the selected label date before downstream extraction. Keep the FDA URL in
   pipeline data, not in curator-facing review Markdown.

## Generate efficiently, review vertically

Use these curator-facing phases:

1. Run `prepare-document-review` to generate the document proposal and `document.md`;
   review the document.
2. Run `extract-indication-candidates` to generate all indication proposals and
   `indication-candidates.md`; ask which candidates should continue.
3. After one plain-language preview, run `prepare-selected-review` to generate
   descriptions, approval evidence, and stage-specific review files only for the
   selected candidates.
4. For one selected indication, generate and review `indication.md`, `description.md`,
   and `approval.md` in sequence before moving to the next indication.
5. Record each explicit decision with `record-decision`.
6. Run `assemble-reviewed` only when all retained indications are complete.

`record-decision` automatically rebuilds the corresponding review file. After an edit,
show only the resolved edited field and value in chat, then ask the curator to confirm it
is correct. Do not continue until they confirm. If they correct it, record the replacement
edit and confirm again.

Keep external workflow model requests batched where the existing tools support batching.
Do not insert curator confirmation between internal pipeline stages when no review occurs
there.

Use the proposal's descriptive `review_label` as the heading. Keep the numeric pipeline
index available only for tool calls and provenance.

## Present source-backed review

Read [references/review-formats.md](references/review-formats.md). For each decision,
provide a prominent link to the deterministically generated Markdown review file.
Do not reproduce or paraphrase that file's source text, proposal fields, rationale, or
verification in chat. The file is the canonical review surface.

Use chat only to show:

1. the review-file link;
2. **Harness assessment** — clearly labeled reasoning produced by the harness; and
3. numbered decision options to accept, edit, exclude, inspect evidence, or ask a
   question.

Quote from a review file in chat only when answering a specific curator question, and
label the text as a quotation from that file.

Say “Indications and Usage,” not “Section 1.” Clearly distinguish curation provenance
(application, selected label, local files) from fields that will appear in
`document.json` or `indication.json`.

Use converted Markdown as the primary source for in-context review. Every review file
after document review must link to both the local label Markdown and PDF. The document
review is the only exception because extraction has not created those local files yet.
Do not promise that the harness can render the PDF.

## Explain before shell confirmation

Before submitting a meaningful shell command, explain in plain language:

- the curation phase and why it is needed;
- the information it will retrieve or generate;
- whether it downloads public FDA files;
- which local artifact group it will write; and
- what the curator will review after it completes.

Only when the command sends content to the workflow's configured Anthropic API, add a
short sentence saying so and that it may incur additional API usage. Do not discuss API
usage for local processing, review rendering, metadata retrieval, or decision recording.

Then submit the command so the harness's shell-approval dialog is the confirmation.
Do not ask a redundant conversational “ready?” when the shell approval will immediately
follow. Group uninterrupted pipeline work under one explanation and, where possible,
one wrapper command. Give a new explanation only at a meaningful curator boundary,
before an overwrite, or when the planned scope or cost changes.

## Assess descriptions

For every description, identify any detail added from Clinical Studies and assess:

- whether it resolves a real ambiguity in the indication;
- whether the selected source supports it; and
- whether it adds irrelevant trial design, population, endpoint, or efficacy detail.

Recommend indication-only wording when the additional detail does not clarify the
approval. Do not apply the recommendation without explicit curator approval.

Ensure `description.md` and `approval.md` repeat the current curator-reviewed indication
near the top. The curator must be able to judge description relevance and approval-date
reasoning without reopening another file to remember the indication.

Read [references/review-standards.md](references/review-standards.md) for clinical
review rules and [references/moalmanac-examples.md](references/moalmanac-examples.md)
only when checking final shape or editorial precedent.

## Stop conditions

Stop rather than improvise when source extraction is unusable, a proposal lacks source
support, historical coverage is incomplete, an approval event fails verification, or
review decisions are stale relative to their source hashes.

The workflow creates reviewed new-entry drafts only. Do not revise existing MOAlmanac
records, change `moalmanac-db`, commit, push, or open a pull request unless the curator
makes a separate explicit request.
