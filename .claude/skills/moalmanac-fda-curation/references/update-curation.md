# Newer-label update analysis

Use this procedure only after preflight reports both `previously_curated: true` and
`newer_label_available: true`.

Follow the phases below in order. Finish the new-indication phase before introducing
revision analysis. New indications can use the existing indication review and decision
workflow, but revision proposals and final update assembly remain analysis-only.

## Introduce the update

Use a conversational transition based on the preflight result:

1. “We last curated this drug on CURATED_LABEL_DATE.”
2. “Let's check whether FDA has published a newer approved label.”
3. If one exists, report its date and say: “There is a newer label. Let's first see
   whether it contains any new indications.”

Convey this meaning naturally; do not expose raw preflight JSON unless the curator asks.

## Find and curate new indications first

Explain that one preparation step will retrieve and extract the newer label, compare its
indications with the existing MOAlmanac indications, and create a local Markdown review;
it will not modify `moalmanac-db`. Then run:

```bash
moalmanac-fda-curation prepare-update-indication-review \
  --application-number APPLICATION_NUMBER \
  --database-dir MOALMANAC_DB_ROOT \
  --work-dir RUN_DIR
```

The command derives the brand and generated filenames internally. Do not search for
either. It loads the project's `.env` through the CLI, so do not source the API key in a
separate shell command. Keep the default biomarker-only scope unless the curator
explicitly expands it.

After it completes, route from its counts without asking the curator to review successful
matches:

- If `not_found` or `uncertain` is nonzero, link
  `review/reconciliation-exceptions.md` and stop for curator review.
- If new candidates exist and there are no exceptions, begin their indication-level
  curation using the printed indexes.
- If there are no new candidates or exceptions, proceed directly to revision analysis.

The complete mapping remains in `intermediate/indication-reconciliation.json` for
provenance, but do not present it as a required review surface.

Interpret the groups as follows:

- `matched`: eligible for revision assessment; it is not automatically unchanged.
- `new`: a candidate for the first-time indication workflow.
- `not_found`: a possible extraction miss, label omission, removal, merge, or scope
  mismatch; flag it for curator investigation and never call it removed.
- `uncertain`: stop automated routing for the affected records and ask the curator to
  inspect the identity evidence.

Do not begin revision assessment while new indications or exceptions remain. If one or
more mappings are `new`, use their printed stable indexes and complete the workflow in
[new-curation.md#review-vertically](new-curation.md#review-vertically), including
description and approval review, before continuing. Do not repeat document review or
assemble a duplicate document record.

If no new indications are found, say so plainly and continue. Resolve or explicitly
defer `not_found` and `uncertain` exceptions before continuing; do not let them silently
disappear and do not call them removed.

## Then assess previously curated indications

Only after the new-indication phase is complete, transition with: “Now let's see whether
any indications we already curated were modified in the newer label.”

Run `prepare-label-history --work-dir RUN_DIR`. It will reuse history created during new
indication approval review when available. Use the exact cache path printed by the
command as `--section-cache-json`; do not search for or reverse-engineer its filename.
Confirm the cache contains both baseline and latest label URLs, and stop if historical
coverage is incomplete.

Run `assess-revised-indications` with the exact curated baseline URL and latest URL.
Require `verified: true`. Review every assessment, including `not_revised`, because
verification establishes coverage rather than clinical correctness.

Run `propose-revised-indications` only after the revision assessment is verified. A
proposal is a minimal, allow-listed patch to an existing indication; it is not an
accepted change.

Present links to the assessment and proposal JSON artifacts with a concise harness
assessment. Because curator-facing revision Markdown and revision decision commands do
not exist yet, do not offer accept/edit choices that imply persistence. Instead ask the
curator to inspect, question, or flag individual results. Do not send `not_found` or
`uncertain` records into revision proposal generation.

Conclude with three separate summaries:

1. new indication candidates;
2. revised indication proposals; and
3. `not_found` or `uncertain` records requiring investigation.

Distinguish reviewed new-indication decisions from revision analysis. State explicitly
that the session still awaits an update-specific assembler and that revision proposals
have not been accepted.
