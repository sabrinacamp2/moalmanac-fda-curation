# Step-by-step review formats

Use these compact cards in chat. Show one indication at a time unless the curator asks
for a summary. Link the full artifact and quote only enough evidence to make the
decision understandable.

## Document proposal

```text
Document proposal

Brand (generic): <value>
Company: <value>
Application: <value>
Pinned label date: <value>
Pinned label: <URL>
Citation: <value>

Review note: <pipeline warning or editorial field needing attention>
Decision: accept, edit a field, inspect the source, or ask a question.
```

Do not claim to show an original FDA sponsor value separately unless the artifact or
command output preserves it.

## Indication proposal

```text
Indication <pipeline index>

Proposal:
> <indication>

Structured fields:
- Biomarker: <raw_biomarkers or null>
- Cancer type: <raw_cancer_type or null>
- Therapeutics: <raw_therapeutics or null>

Supporting Section 1 source:
> <short relevant excerpt from the linked broad source chunk>

Warnings: <specific discrepancy or none observed>
Decision: accept, edit, exclude, inspect more source, or ask a question.
```

Do not silently produce a replacement extraction. If a discrepancy is visible, name
it and ask for a decision.

## Description proposal

```text
Description for indication <pipeline index>

Proposal:
> <description>

Selected Clinical Studies evidence:
> <short excerpt, or "No span selected">

Review focus: Does the added detail clarify an ambiguity in this indication?
Warnings: <different disease/biomarker/regimen, unsupported detail, or none observed>
Decision: accept, edit, use indication-only wording, inspect more source, or ask a
question.
```

Do not independently choose a replacement span during normal review. If the selected
span appears wrong, flag the mismatch and offer to inspect or regenerate it.

## Approval-date proposal

```text
Initial approval proposal for indication <pipeline index>

Date: <date or unmatched>
Event: <number and change type>
Label: <URL>
Pipeline rationale: <stored rationale>

Before:
> <stored before text or none>

After:
> <stored after text>

Verification: <passed/failed and any uncertainty>
Decision: accept, inspect earlier events, choose another event, or ask a question.
```

Do not independently rank the full timeline unless requested or investigating a
specific warning. Verification is structural, not proof of earliest clinical
equivalence.

## Final draft

```text
Draft ready for final review

- Document: <artifact link>
- Indications included: <indexes/count>
- Excluded candidates: <indexes/count>
- Unresolved decisions: <items or none>
- Structural validation: <result>

This is a draft only; it has not been merged into moalmanac-db.
```
