# File-first curator review

The curator-facing workflow commands generate canonical Markdown review files alongside
their pipeline artifacts. Every new review prompt begins with a clickable absolute-path
link to the exact Markdown file for that decision. Follow the link with a brief statement
of the decision and the available actions. Do not copy the file contents into chat or
add a routine assessment or recommendation. If the curator asks for an opinion, read the
complete review file and answer the specific question without treating that opinion as
pipeline state.

Each review file presents the proposal first, followed by clearly labeled supporting
context and evidence. Recorded curator edits and decisions appear after the evidence.

## Before a command

Immediately before submitting a shell command, send a short preview:

```markdown
Next, I’ll prepare the document record. This collects FDA metadata about the drug and
selected label, including brand and generic names, manufacturer, application number,
label date and URLs, and citation text.

Afterward, you’ll review `document.md`, especially editorial fields such as company.
```

For indication extraction, state that the command reads the selected label's Indications
and Usage section and produces candidates with source provenance for selection.

For the post-selection preparation phase, state that the commands generate descriptions,
download historical labels, propose initial approval dates and approval status, and
prepare review files for only the selected candidates. Explain once before the
uninterrupted phase rather than once per internal step.

## Document review in chat

```markdown
[Open the document review](<absolute-path-to-review/document.md>)

1. Accept
2. Edit a field
3. Inspect source metadata
4. Ask a question
```

The linked file contains FDA target metadata and the exact generated document proposal.
It does not yet link local label files; those are created during indication extraction.

## Candidate selection in chat

```markdown
[Open the extracted indication candidates](<absolute-path-to-review/indication-candidates.md>)

Tell me which candidates should continue, which should be excluded, or what you want to
investigate.
```

The linked file is intentionally a quick genomic-biomarker relevance screen: each
candidate shows only its descriptive name, proposed indication, and raw biomarker.
Detailed source scrutiny happens during the one-by-one indication review. Do not run
descriptions or approval matching until the candidate set is explicit.

## Indication review in chat

```markdown
[Open the indication review](<absolute-path-to-review/indications/<slug>/indication.md>)

1. Accept
2. Edit
3. Exclude
4. Inspect more evidence
5. Ask a question
```

## Possible-revision screening in chat

Present each possible revision before preparing detailed curation reviews. Explain that
the tool intentionally surfaces small wording changes as well as substantive ones, and
this screening decides whether the change is meaningful enough to replace the existing
indication with a new record.

```markdown
[Open the possible revision](<absolute-path-to/review/revision-screening/<slug>.md>)

The tool found a source-text difference associated with this indication. Decide whether
it is meaningful enough to replace the existing MOAlmanac indication with a new record.

1. Replace it using the latest-label proposal
2. Edit the proposal, then replace it
3. This change does not warrant a replacement; keep the existing record
4. Leave unresolved
5. Ask a question
```

## Description review in chat

State only whether the pipeline reports added Clinical Studies or Clinical Pharmacology
detail. The curator still reviews every proposed description. Do not assess the proposal
or say that nothing remains to review when no clinical detail was added.

```markdown
[Open the description review](<absolute-path-to-review/indications/<slug>/description.md>)

1. Accept
2. Edit
3. Use indication-only wording
4. Inspect more evidence
5. Ask a question
```

## Approval review in chat

```markdown
[Open the initial approval review](<absolute-path-to-review/indications/<slug>/approval.md>)

1. Accept
2. Inspect earlier events
3. Choose another event
4. Change the approval status
5. Ask a question
```

The approval file repeats the current curator-reviewed indication before the date
evidence so the curator can judge clinical equivalence without changing context. Its
before/after evidence is copied directly from the selected changelog event, and it links
to that numbered event in the full local changelog. It also states the proposed
approval status, `Approved` or `Accelerated`, and the label wording that status is based
on. Record a status change as an approval edit, for example
`--override 'status="Accelerated"'`.

For a replacement of a changed indication, the same file is titled as an approval date
and status review. Ask the curator to consider two questions separately: whether the
selected event is the earliest post-baseline label that supports the revised wording,
and which approval date the new record should carry. The proposed date fits when the
revised wording represents a new approval; the existing approval date fits when it does
not. Present these options:

1. Use the proposed approval date
2. Keep the existing MOAlmanac approval date
3. Inspect earlier events
4. Choose another event
5. Change the approval status
6. Leave unresolved
7. Ask a question

When the curator keeps the existing approval date, let the tool retrieve it from the
existing MOAlmanac record:

```bash
moalmanac-fda-curation record-decision \
  --work-dir RUN_DIR \
  --stage approval \
  --indication-index INDEX \
  --decision edited \
  --keep-existing-field initial_approval_date
```

Add `--keep-existing-field status` when the curator also keeps the existing approval
status.

## Indication mapping review in chat

Present mapping reviews only for existing indications classified as `not_found` or
`uncertain`, one at a time. The linked file owns the evidence; curator choices stay in
chat.

For `not_found`:

```markdown
[Open the indication mapping review](<absolute-path-to/review/indication-matches/not-found-*.md>)

Tell me whether you found a current-label counterpart, believe the indication is absent,
want to inspect more evidence, or want to leave this unresolved.
```

For `uncertain`:

```markdown
[Open the indication mapping review](<absolute-path-to/review/indication-matches/uncertain-*.md>)

Tell me whether these are the same indication, whether another counterpart is a better
match, whether this reflects a split or merge, or whether to leave it unresolved.
```

## Confirm an edit

`record-decision` rebuilds the deterministic review file automatically. After an edit,
show only the resolved field and value in chat, then ask the curator to confirm it. Do not
copy the rest of the packet into chat or move to the next review until they confirm.

## Trust labels inside deterministic files

Review files must visibly distinguish:

- **FDA source — verbatim**;
- **Pipeline proposal — model generated**;
- **FDA source — verbatim, span selected by pipeline model**;
- **Pipeline selection — event selected by model**;
- **Deterministically retrieved event evidence**; and
- **Recorded curator decision**.

Agent opinions do not belong inside these deterministic files.
