# Workflow tool reference

## Runtime

Install this repository into an isolated environment:

```bash
python -m pip install -e .
```

Run the unified `moalmanac-fda-curation` command from the repository root. Export
`ANTHROPIC_API_KEY` before model-backed commands. Never expose `.env` contents.

Before invoking a command, inspect its `--help` output and existing target artifacts.
Use `--overwrite` only after explaining what will be regenerated; model-backed
regeneration can incur cost.

## 1. Prepare document metadata

```bash
moalmanac-fda-curation prepare-document \
  --application-number NDA208558 \
  --output OUTPUT_DIR/document.json
```

Without `--label-url`, the command selects the latest approved label in the Drugs@FDA
application record. Present its date and URL for confirmation before continuing.
Use optional `--label-url FDA_LABEL_URL` only to select a specific approved historical
label for that application.

Optional `--company` is a curator-supplied normalized value. Otherwise the proposal
uses the FDA sponsor value, which may require editorial normalization. The command
generates the document proposal; the harness presents it for review rather than
rebuilding it.

## 2. Extract indications

```bash
moalmanac-fda-curation extract-indications \
  --document-json OUTPUT_DIR/document.json \
  --output-dir OUTPUT_DIR
```

Key artifacts:

- `labels/*.{pdf,md}`: pinned label and converted text;
- `intermediate/*.raw_ind.md`: extracted Section 1 text; and
- `intermediate/*-claude_chunked_indication_fields.json`: field proposals, broad
  supporting source chunks, and `source_chunk_index` provenance.

The source chunk is a broad provenance anchor and may contain more than the exact
sentence used by one proposal. Present it as supporting source, not an exact minimal
span.

## 3. Generate descriptions

Run `moalmanac-fda-curation generate-descriptions` with the document JSON,
indication-fields JSON, and converted pinned label Markdown. Repeat
`--indication-index N` to limit work to curator-retained indications.

The command performs batched Clinical Studies span selection and individual
description drafting. Its output stores both. The harness presents the proposed
description and selected span; it does not independently select a second span or
redraft the description unless the curator requests a challenge.

## 4. Build historical Section 1 changes

```bash
moalmanac-fda-curation build-history \
  --document-json OUTPUT_DIR/document.json \
  --work-dir OUTPUT_DIR
```

The first usable approved label becomes an `initial` event. Later logical Section 1
changes become insert/replace events. Inspect `skipped_labels` before treating the
history as complete. Missing historical coverage is a stop condition for accepting a
date, not an invitation to substitute another source.

## 5. Match approval dates

Run `moalmanac-fda-curation match-dates` with the indication-fields JSON and changelog
JSON. Repeat `--indication-index N` to match only retained candidates.

The model selects event numbers. The command then deterministically hydrates the date,
URL, change type, before/after text, and verification result. Present these stored
values in the approval-date review card. Do not independently scan and rank every
event during normal review. Expand earlier events only when the curator requests it,
the result reports uncertainty, or the displayed evidence suggests an error.

When the changelog has exactly one event, the command skips the model call and records
`auto_matched_single_event: true`. Confirm that historical-label discovery did not
miss another label before accepting it.

Verification proves that the selected event exists and its stored quotes agree with
the changelog. It does not prove that the event is clinically the earliest correct
event.

## 6. Assemble the draft

Run `moalmanac-fda-curation assemble-draft` with the reviewed document, indication
fields, description candidates, and date-match artifacts. By default it retains only
non-empty biomarker candidates. It refuses missing descriptions, unverified dates,
duplicate indexes, and empty output. Use `--include-all-indications` only after an
explicit curator decision.

Assembly produces draft indication JSON. It does not merge records into
`moalmanac-db` or update other database tables.

## Decision log

Maintain `OUTPUT_DIR/intermediate/<Brand>-<APPL>-review.md` as a compact record of
curator decisions, not a second generated report. Start with:

```markdown
# <Brand> <application number> review

- Pinned label: <URL>
- Label date: <date>
- Workflow: new-entry draft
- Status: in progress
```

For each reviewed item, append:

```markdown
## <stage or indication index>

- Decision: accepted | edited | excluded | unresolved
- Original proposal: <value or artifact link>
- Accepted value: <value, if different>
- Curator note: <brief reason, if supplied>
- Evidence: <artifact link and source location>
```

Do not duplicate full labels, large chunks, complete changelogs, or invented model
reasoning in this file. Preserve generated artifacts separately.

## Cache and dependency behavior

- Editing document citation metadata usually does not require re-extracting label
  indications unless the pinned label URL or application changed.
- Editing the meaning of an indication can stale its description and approval-date
  match.
- Excluding an indication means it should not receive description or date calls.
- Editing a description alone does not stale the indication or approval date.
- Correcting an approval date does not require regenerating extraction or description
  artifacts.
