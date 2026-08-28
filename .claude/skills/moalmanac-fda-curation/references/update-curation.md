# Newer-label update curation

Use this procedure only when the curation status reports both `previously_curated: true` and
`newer_label_available: true`.

## Check for new indications

Continue by saying: “We'll start with new indications.” Then run:

```bash
moalmanac-fda-curation find-new-indications \
  --application-number APPLICATION_NUMBER \
  --database-dir MOALMANAC_DB_ROOT \
  --work-dir RUN_DIR
```

Route from the command output:

- If it prints an indication match review, link that file and stop for curator input.
- Link the printed new-indication review and summarize the reported biomarker status.
  Present indications outside biomarker scope as findings and the biomarker-bearing
  subset as curation candidates.
- If it prints curation-eligible new indication indexes, prepare and review those indexes using the
  indication-level steps in [new-curation.md#review-vertically](new-curation.md#review-vertically).
- If it reports no new indications or after their review is complete, continue to the
  revision phase.

Do not ask the curator to review successful indication matches. Do not repeat document
review or run new-entry assembly during an update session.

## Review flagged revisions

Tell the curator: “Now we'll see if any indications have changed in the newer label.”
Then run:

```bash
moalmanac-fda-curation find-revised-indications \
  --database-dir MOALMANAC_DB_ROOT \
  --work-dir RUN_DIR
```

Do not narrate label-history downloads, caches, date coverage checks, or approval-date
matching. The command owns those mechanics and should surface them only when it cannot
complete the assessment.

Route from the command output:

- If it reports no flagged revisions, tell the curator and stop.
- Link only the Markdown files printed for flagged revisions, one at a time.
- If approval evidence is unresolved, describe that revision as incomplete.
- Do not present unchanged indications unless the curator asks.

An optional harness assessment may comment on whether the proposal appears supported by
the review file. Do not repeat the file's exact diff or proposal in chat. Revision
decisions and update assembly are not yet persisted, so ask the curator to inspect,
question, or flag the proposal rather than offering an accept/edit action that implies a
recorded decision.
