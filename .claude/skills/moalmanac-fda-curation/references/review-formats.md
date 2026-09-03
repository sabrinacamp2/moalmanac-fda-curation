# File-first curator review

The curator-facing workflow commands generate canonical Markdown review files alongside
their pipeline artifacts. Do not copy their contents into chat. Link to the relevant
file, add a clearly labeled harness assessment, and ask for a decision.

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
download historical labels, propose initial approval dates, and prepare review files for
only the selected candidates. Explain once before the uninterrupted phase rather than
once per internal step.

## Document review in chat

```markdown
[Open the document review](<absolute-path-to-review/document.md>)

**Harness assessment:** <Only the harness’s judgment about fields needing attention.>

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

**Harness assessment:** <Identify likely borderline candidates or extraction concerns;
do not restate the candidates.>

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

**Harness assessment:** <Assess source support and preserved qualifiers without copying
the proposal or source into chat.>

1. Accept
2. Edit
3. Exclude
4. Inspect more evidence
5. Ask a question
```

## Description review in chat

```markdown
[Open the description review](<absolute-path-to-review/indications/<slug>/description.md>)

**Harness assessment:** <Comment only on detail added from Clinical Studies or Clinical
Pharmacology: whether it genuinely clarifies the indication and whether the cited source
supports it. Do not assess other editorial wording differences.>

1. Accept
2. Edit
3. Use indication-only wording
4. Inspect more evidence
5. Ask a question
```

## Approval review in chat

```markdown
[Open the initial approval review](<absolute-path-to-review/indications/<slug>/approval.md>)

**Harness assessment:** <Assess the selected event and flag uncertainty without copying
the indication, rationale, or changelog text into chat.>

1. Accept
2. Inspect earlier events
3. Choose another event
4. Ask a question
```

The approval file repeats the current curator-reviewed indication before the date
evidence so the curator can judge clinical equivalence without changing context. Its
before/after evidence is copied directly from the selected changelog event, and it links
to that numbered event in the full local changelog.

## Revision review in chat

Only indications classified as revised receive a Markdown review. Do not list unchanged
indications unless the curator asks for the audit result.

```markdown
[Open the flagged revision](<absolute-path-to-review/revisions/<indication-id>.md>)

**Harness assessment:** <Assess whether the proposal is supported by the linked
source artifacts.>

1. Accept
2. Specify field edits
3. Record that no MOAlmanac field should change
4. Inspect or question the proposal
5. Mark unresolved
```

Present the generated revision review files one at a time.

## Indication mapping review in chat

Present mapping reviews only for existing indications classified as `not_found` or
`uncertain`, one at a time. The linked file owns the evidence; curator choices stay in
chat.

For `not_found`:

```markdown
[Open the indication mapping review](<absolute-path-to/review/indication-matches/not-found-*.md>)

**Harness assessment:** <Assess whether the indication appears absent, was missed by
extraction, or may correspond to differently worded current-label text.>

Tell me whether you found a current-label counterpart, believe the indication is absent,
want to inspect more evidence, or want to leave this unresolved.
```

For `uncertain`:

```markdown
[Open the indication mapping review](<absolute-path-to/review/indication-matches/uncertain-*.md>)

**Harness assessment:** <Assess the proposed relationship without restating both
records.>

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

No harness assessment belongs inside these deterministic files.
