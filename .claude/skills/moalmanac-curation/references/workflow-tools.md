# Workflow tool reference

## Runtime

Install this repository into an isolated environment:

```bash
python -m pip install -e .
```

Run the unified `moalmanac-curation` command from the repository root. Export
`ANTHROPIC_API_KEY` before model-backed commands. Never expose `.env` contents.

## 1. Prepare document metadata

```bash
moalmanac-curation prepare-document \
  --application-number NDA208558 \
  --label-url PINNED_FDA_LABEL_URL \
  --output OUTPUT_DIR/document.json
```

Optional `--company` is a curator-supplied normalized value. Otherwise show the
FDA sponsor value for review.

## 2. Extract indications

```bash
moalmanac-curation extract-indications \
  --document-json OUTPUT_DIR/document.json \
  --output-dir OUTPUT_DIR
```

Key artifacts:

- `labels/*.{pdf,md}`: pinned raw label and converted text
- `intermediate/*.raw_ind.md`: extracted Section 1 text
- `intermediate/*-claude_chunked_indication_fields.json`: proposals, structured
  raw fields, source chunks, and `source_chunk_index` provenance

Use `--overwrite` only for intentional regeneration. It makes paid model calls.

## 3. Generate descriptions

Run `moalmanac-curation generate-descriptions` with the document JSON,
indication-fields JSON, and converted pinned label Markdown. Repeat
`--indication-index N` to limit work to curator-retained indications. The output
records batched Clinical Studies selections and individual description proposals.
Show both during review.

## 4. Build historical Section 1 changes

```bash
moalmanac-curation build-history \
  --document-json OUTPUT_DIR/document.json \
  --work-dir OUTPUT_DIR
```

The first usable approved label becomes an `initial` event. Later logical Section 1
changes become insert/replace events. Inspect `skipped_labels` and extraction text
before treating the history as complete.

## 5. Match approval dates

Run `moalmanac-curation match-dates` with the indication-fields JSON and changelog
JSON. Repeat `--indication-index N` to match only retained candidates. The LLM
selects event numbers; the command deterministically hydrates date, URL, change
type, and exact event text and verifies the returned values.

When the changelog has exactly one event, the command skips the model call and
auto-matches selected indications to that event. The result records
`auto_matched_single_event: true`. Confirm that historical-label discovery did not
miss another label before accepting it.

Verification proves that the selected event exists and its quotes match. It does
not prove that the event is clinically the earliest correct event. Curator review
is always required.

## 6. Assemble the draft

Run `moalmanac-curation assemble-draft` with the document, indication fields,
description candidates, and date-match artifacts. By default it retains only
non-empty biomarker candidates. It refuses missing descriptions, unverified dates,
duplicate indexes, and empty output. Use `--include-all-indications` only after an
explicit curator decision.

## Cache and dependency behavior

- Editing document citation metadata usually does not require re-extracting label
  indications unless the pinned label URL/application changed.
- Editing an indication can stale its description and approval-date match.
- Excluding an indication means it should not receive description/date calls.
- Editing a description alone does not stale the indication or approval date.
- Correcting an approval date does not require regenerating extraction or
  description artifacts.
