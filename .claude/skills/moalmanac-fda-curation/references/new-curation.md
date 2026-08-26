# First-time FDA curation

Use this procedure only after preflight reports `previously_curated: false`.

## Prepare and screen candidates

1. Run `prepare-document-review` without `--label-url` to select the latest approved
   label. Use a specific FDA label URL only when the curator requests an earlier version.
2. Show the selected label date before downstream extraction. Keep the FDA URL in
   pipeline data, not in curator-facing review Markdown.
3. Review `document.md` and record the curator's explicit decision.
4. Run `extract-indication-candidates`, link `indication-candidates.md`, and ask which
   candidates should continue.
5. After one plain-language preview, run `prepare-selected-review` for all selected
   indexes in one command.

## Review vertically

For one selected indication, review `indication.md`, `description.md`, and `approval.md`
in sequence before moving to the next indication. Use the proposal's `review_label` as
the heading; retain its numeric index only for tool calls and provenance.

Record a decision only after the curator explicitly accepts, edits, excludes, or marks
the item unresolved. `record-decision` rebuilds the corresponding review file. After an
edit, show only the resolved field and value and ask the curator to confirm it. If they
correct it, record the replacement and confirm again.

Keep supported batch operations batched. Do not insert curator confirmation between
internal stages when no review occurs. Run `assemble-reviewed` only when every retained
indication has complete explicit decisions.

## Assess descriptions

Read [review-standards.md](review-standards.md). Assess only detail added from Clinical
Studies or Clinical Pharmacology. Other wording differences between description and
indication are intentional editorial transformations owned by the description prompt.

For added clinical detail, assess whether it resolves a real ambiguity, is supported by
the selected source, and avoids irrelevant trial design, population, endpoint, or
efficacy information. Recommend removal when it does not clarify the approval, but do
not apply that recommendation without explicit curator approval.

Ensure `description.md` and `approval.md` repeat the current curator-reviewed indication
near the top. Read [moalmanac-examples.md](moalmanac-examples.md) only when checking final
shape or editorial precedent.
