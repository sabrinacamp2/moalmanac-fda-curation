# Curation review standards

## Source and extraction quality

Require substantive raw text for every proposal. A model must not reconstruct an
indication from headings, drug knowledge, or other labels. Compare extracted Section
1 against obvious label structure and flag suspiciously short or fragmented text.

Known unsafe patterns include:

- symbol-only PDF conversion;
- Section 1 chunks containing later-section headings but no indication body;
- generated details absent from `source_chunk_text`; and
- a converted label whose section boundaries jump unexpectedly.

If the pinned PDF cannot be extracted, skip or flag the candidate. Do not silently
use openFDA text because its content may not correspond to the pinned label date.

## Indication review

Preserve complete patient-selection criteria, regulatory qualifiers, combination
partners, prior-treatment requirements, and companion diagnostic language. Keep
`raw_biomarkers`, `raw_cancer_type`, and `raw_therapeutics` grounded in label text.
Use `Brand (generic)` in `raw_therapeutics` for the label drug, without requiring
that formatting in the indication sentence itself.

The current workflow uses non-null `raw_biomarkers` as a routing proxy, not as a
complete definition of MOAlmanac relevance. Let the curator include or exclude
borderline candidates.

## Description review

Verify that the selected Clinical Studies span concerns the same disease, biomarker,
line of therapy, and regimen as the indication. The description must not import a
trial, endpoint, or population from a neighboring indication. Distinguish label
evidence from editorial wording.

Only pull Clinical Studies detail into the description when it resolves genuine
ambiguity in the indication's own wording — for example, naming which specific
prior therapies satisfy "a prior ROS1 kinase inhibitor," or which agents satisfy
"platinum-based chemotherapy." Do not add general trial design, enrollment counts,
demographic or baseline statistics, or eligibility criteria that do not disambiguate
anything already stated in the indication text.

When a disambiguating detail is warranted, keep the trial name or NCT number as a
short framing clause around that detail rather than presenting the specifics as a
bare fragment. See the EMA Libtayo (`ind:ema.libtayo:1`) and taletrectinib/Ibtrozi
(`ind:fda.ibtrozi:0`) entries in `moalmanac-db/referenced/indications.json` for this
pattern. Plain agency-attribution restatements of the indication (e.g. the Rozlytrek
and Augtyro ROS1 entries) are correct when the indication text needs no
disambiguation — do not add trial color to those by default.

## Initial approval date review

Select the earliest label event that contains all clinically meaningful qualifiers.
Do not delay the date for:

- headings or paragraph separation;
- bullets versus prose;
- punctuation, spacing, capitalization, or hyphenation;
- cross-reference changes;
- abbreviation expansion; or
- reordered but clinically equivalent language.

Inspect earlier similar events directly. Do not accept an LLM statement that a
qualifier is missing without checking the event text.

Known examples:

- Lynparza plus bevacizumab: `2020-05-08` introduced the indication; `2020-05-19`
  changed the heading and `HRD positive` to `HRD-positive`.
- Keytruda first-line PD-L1-positive NSCLC: `2019-04-11` already included TPS >=1%
  and the stage III/metastatic alternatives; `2019-06-10` reorganized the wording.
- Jemperli single-agent dMMR endometrial cancer: `2023-02-09` introduced the full
  indication; `2023-07-31` separated it into its own paragraph while adding another
  combination indication.

The changelog verifier confirms structural integrity of an LLM-selected event, not
semantic correctness or earliest clinical equivalence.

## Review and publication authority

Present generated values as proposals. Record curator edits separately from raw
model output where practical. Never infer acceptance from silence or from a tool's
success. Require explicit direction before changing the database or opening a PR.

