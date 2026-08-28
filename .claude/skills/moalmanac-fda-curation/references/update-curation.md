# Newer-label update curation

Use this procedure only when preflight reports both `previously_curated: true` and
`newer_label_available: true`.

## Check for new indications

Tell the curator when the application was last curated, report the newer label date,
and explain that new indications will be checked first. Then run:

```bash
moalmanac-fda-curation prepare-update-indication-review \
  --application-number APPLICATION_NUMBER \
  --database-dir MOALMANAC_DB_ROOT \
  --work-dir RUN_DIR
```

Route from the command output:

- If it prints a reconciliation exception review, link that file and stop for curator
  input.
- If it prints new indication indexes, prepare and review those indexes using the
  indication-level steps in [new-curation.md#review-vertically](new-curation.md#review-vertically).
- If it reports no new indications or after their review is complete, continue to the
  revision phase.

Do not ask the curator to review successful indication matches. Do not repeat document
review or run new-entry assembly during an update session.

## Review flagged revisions

Tell the curator that existing indications will now be checked for revisions. Run:

```bash
moalmanac-fda-curation prepare-label-history \
  --work-dir RUN_DIR
```

Use the cache and changelog paths printed by that command, together with the preflight
metadata, to run:

```bash
moalmanac-fda-curation prepare-revision-review \
  --existing-indications-json MOALMANAC_DB_ROOT/referenced/indications.json \
  --document-id DOCUMENT_ID \
  --section-cache-json PRINTED_CACHE_PATH \
  --changelog-json PRINTED_CHANGELOG_PATH \
  --baseline-label-url CURATED_LABEL_URL \
  --latest-label-url LATEST_LABEL_URL \
  --baseline-label-date CURATED_LABEL_DATE \
  --latest-label-date LATEST_LABEL_DATE \
  --work-dir RUN_DIR
```

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
