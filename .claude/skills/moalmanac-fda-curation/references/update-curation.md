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

- If it prints indication mapping reviews, present the linked files one at a time and
  stop for curator input before continuing.
- Link the printed new-indication review and summarize the reported biomarker status.
  Present indications outside biomarker scope as findings and the biomarker-bearing
  subset as curation candidates.
- If it prints curation-eligible new indication indexes, prepare and review those indexes using the
  indication-level steps in [new-curation.md#review-vertically](new-curation.md#review-vertically).
- If it reports no new indications or after their review is complete, continue to the
  revision phase.

Do not ask the curator to review successful indication matches. Do not repeat document
review or run new-entry assembly during an update session.

## Review changes to existing indications

Tell the curator: “Now we'll see if any indications have changed in the newer label.”
Then run:

```bash
moalmanac-fda-curation find-revised-indications \
  --database-dir MOALMANAC_DB_ROOT \
  --work-dir RUN_DIR
```

Describe this as checking whether existing indications changed. The command owns the
label-history and comparison mechanics and surfaces them only when it cannot complete
the assessment.

Route from the command output:

- If it reports no changed matched indications, tell the curator and stop.
- Present each revision-screening Markdown file one at a time. Ask whether to use the
  latest-label proposal, edit it before use, keep the existing record, or leave the
  candidate unresolved. Persist the answer with `record-decision --stage revision`
  using `use_latest`, `keep_existing`, or `unresolved`; pass approved edits as overrides
  with `use_latest`.
- Treat those values as internal command vocabulary. In curator-facing summaries, say
  that an existing indication will be updated using the newer label, left unchanged, or
  still needs a decision. After screening is complete, say: “You chose to update these
  existing indications using the newer label. Next, we'll review each updated
  description and decide which label date and URL the record should use.” Include the
  number of indications when useful.
- After every screening decision is resolved, run `prepare-revision-reviews`. For each
  selected index, review its description, then say: “Next, let's decide which label date
  and URL this indication should use.” Present
  one indication and one stage at a time, recording each explicit decision with
  `record-decision`.
- For a changed existing indication, offer accept, edit, inspect, question, or unresolved
  outcomes. Keep the indication in the revision set while its mapping remains valid.
- Do not present unchanged indications unless the curator asks.

After description and label date and URL are resolved for every selected update, run
`assemble-revisions --database-dir MOALMANAC_DB_ROOT` and report the paths to the
reviewed document, URL, indication, and targeted update artifacts. The
curator already compared old and new values in the preceding reviews, so this finalization
does not require another decision.
