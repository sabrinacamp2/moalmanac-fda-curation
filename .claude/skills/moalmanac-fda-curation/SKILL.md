---
name: moalmanac-fda-curation
description: Determine whether an FDA oncology application needs first-time or update curation, then guide evidence-backed review of new or revised MOAlmanac indications using the repository CLI. Use for FDA-label curation sessions, including checking prior curation and comparing a newer label with existing records.
---

# Curate an FDA label for MOAlmanac

Use the CLI for all extraction, matching, validation, proposal generation, and state
changes. This skill coordinates those commands, routes from their outputs, presents
review files, and obtains explicit curator decisions. Use a harness assessment only as
an optional second check of curator-facing evidence.

## Protect source and generated output

- Treat downloaded labels and every pipeline-generated artifact as immutable.
- Never edit generated JSON, Markdown, changelogs, or source files.
- Never infer approval from silence or successful execution.
- Use `record-decision` for supported state changes; do not write decision files manually.
- Explain what `--overwrite` will regenerate and obtain confirmation first.
- Never replace the selected label version or substitute a different source.

## Start and route every session

1. Read [references/workflow-tools.md](references/workflow-tools.md).
2. Check for `.venv` before installing anything. Reuse it when present; create it only
   when absent. Run `moalmanac-fda-curation check-setup` in the active environment and
   resolve failures before curation.
3. Obtain the NDA or BLA application number. If unknown, direct the curator to search
   Drugs@FDA by drug or active ingredient; never guess it.
4. Ask the curator for the path to their local `moalmanac-db` repository. Do not infer
   its location or search for it. Validate the supplied path using
   [references/workflow-tools.md#locate-the-moalmanac-database](references/workflow-tools.md#locate-the-moalmanac-database).
   Before running `check-curation-status`, explain in curator-facing language that
   it will check whether the application already has an FDA document in MOAlmanac. If
   it does, it will compare the date of the curated label with FDA's latest approved
   label to determine whether this is an update session. It reads the database without
   changing it and writes a local status artifact used to select the workflow. Do not
   call this only a generic setup or preliminary check.
   Run `check-curation-status` before preparing a document or extracting indications,
   and persist its result inside the run's `intermediate/` directory.
5. Present the curation status as a short narrative rather than a status dump. For an
   existing application, first say when MOAlmanac last curated it, then say that the
   next step is checking for a newer approved label. Report the result and route exactly
   once:
   - `previously_curated: false`: read
     [references/new-curation.md](references/new-curation.md) and follow it.
   - `previously_curated: true` and `newer_label_available: false`: report that no
     newer approved label needs review and stop.
   - `previously_curated: true` and `newer_label_available: true`: read
     [references/update-curation.md](references/update-curation.md) and follow it.
6. If the curation status is ambiguous or the command fails, stop rather than choosing a
   branch from filenames, drug names, or memory.

Use one work directory for the session, named `analyses/<ApplicationNumber>/`, and reuse
that path for every command. The application number is sufficient; do not perform a
separate brand-name lookup merely to name the directory.

## Present source-backed review

Read [references/review-formats.md](references/review-formats.md) when the selected
branch produces curator-facing review files. Link the generated file prominently and
do not reproduce its proposal or source evidence in chat. Use chat only for the link,
a clearly labeled harness assessment, and numbered decision options.

Quote from a review file only to answer a specific curator question and identify it as
a quotation. Say “Indications and Usage,” not “Section 1.” Distinguish curation
provenance from fields intended for MOAlmanac output.

Use converted Markdown as the primary source for in-context review. Review files after
document review must link to the local label Markdown and PDF. Do not promise that the
harness can render the PDF.

## Explain before shell confirmation

Before a meaningful command, explain the phase, what it will retrieve or generate,
which artifact group it will write, and what the curator will review. Then submit the
command so the shell-approval dialog provides confirmation. Do not ask a redundant
conversational confirmation immediately beforehand.

Group uninterrupted internal pipeline work under one explanation. Give another
explanation at a curator boundary, before overwrite, or when scope or cost changes.

## Stop conditions

Stop when a command reports an unresolved condition or produces a curator-review file.
Do not reproduce or independently reimplement the command's validation logic in the
skill. If useful, add a clearly labeled harness assessment of the generated review
evidence without treating it as pipeline state.

First-time curation and the new-indication portion of an update support recorded review
decisions. Update-specific revision decisions and reviewed update assembly do not yet
exist. Do not describe revision analysis artifacts as curator-approved or database-ready,
and do not revise `moalmanac-db`, commit, push, or open a pull request without a separate
explicit request.
