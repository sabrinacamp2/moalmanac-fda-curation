# MOAlmanac FDA Curation Assistant: Project Handoff

## Purpose of this document

This document is intended for the next person who works on the `moalmanac-fda-curation`
project. It explains why the project exists, the approach taken so far, the current
workflow and architecture, what has been implemented, and the most important remaining
work.

The project is a pilot and is still under active development. Its current focus is FDA
oncology label curation for the Molecular Oncology Almanac (MOAlmanac), but the broader
goal is to explore a reusable model for AI-assisted genomic knowledge curation.

## Project brief

**Working title:** An agentic, human-in-the-loop workflow for evidence-backed FDA label
curation in the MOAlmanac precision medicine knowledgebase

The project develops a conversational curation assistant that helps a human curator
translate FDA oncology labels into structured MOAlmanac records. The assistant behaves
like a junior co-curator: it completes mechanical steps, makes evidence-grounded
proposals at judgment-intensive steps, and pauses for expert review before curator
decisions become final.

The aim is not to remove expert curators from the process. It is to give them a strong,
consistent first draft and a faster way to verify each proposed value against the source
text. The same guided workflow may also make it easier to onboard new curators by
embedding project-specific conventions and expert guidance in the tools and prompts.

## Background and motivation

Comprehensive genomic profiling has become a standard component of oncology care,
enabling clinicians to match patients to therapies based on the molecular
characteristics of their tumors. Translating profiling results into actionable clinical
guidance depends on curated knowledgebases that aggregate evidence linking molecular
alterations to treatment response, resistance, and prognosis. Resources such as
[MOAlmanac](https://paperpile.com/c/wV0u3G/goAp),
[CIViC](https://paperpile.com/c/wV0u3G/ySn0), and
[OncoKB](https://paperpile.com/c/wV0u3G/CbKv+GjBI) form an important foundation for
precision oncology workflows. Their accuracy, completeness, and currency directly
affect how useful they are to clinicians and researchers.

Maintaining these knowledgebases is difficult. Curators must find and review relevant
sources, determine which statements are in scope, translate unstructured evidence into
a structured schema, and revisit existing assertions as the evidence changes. FDA
labels, clinical guidelines, and the scientific literature continue to grow, while the
number of expert curators remains small. This creates an unavoidable delay between the
appearance of clinically meaningful evidence and its incorporation into the resources
that depend on it.

MOAlmanac is a source-centric precision oncology knowledgebase and clinical
interpretation method. Its database associates molecular features with therapeutic
sensitivity, resistance, and prognosis. FDA regulatory approvals are one of its core
evidence types. In the current data model, FDA curation produces two principal records:

- A **document record**, which represents the FDA package insert and includes its
  application number, drug names, manufacturer, publication date, citation, and source
  identifiers.
- One or more **indication records**, which represent distinct approved uses described
  by the label. Each record preserves the regulatory indication, a concise MOAlmanac
  description, biomarker, disease, and therapy text, and evidence for the indication's
  initial approval date.

## Prior work and the remaining gap

Computational methods have long attempted to reduce the burden of genomic knowledge
curation. Earlier systems concentrated on literature retrieval and entity extraction,
surfacing publications and candidate gene–variant–disease relationships for human
review. Examples include LitVar and CIViCmine. More recent work has moved closer to
curator-facing outputs by generating candidate structured annotations from source
documents ([Niyonkuru et al. 2025](https://paperpile.com/c/wV0u3G/wtYR)) or assessing
whether evidence supports a predefined claim
([Reisle et al. 2025](https://paperpile.com/c/wV0u3G/7Svr)).

An important remaining question is whether expert curation judgment can be encoded in
an AI assistant that works *with* the curator throughout an end-to-end workflow. The
assistant should reliably complete deterministic work, apply explicit expert guidance
when interpretation is necessary, and show the exact source evidence behind its
proposals. The curator should be able to inspect, question, edit, accept, exclude, or
leave unresolved each proposed result in a conversational interface.

This project explores that gap. Rather than treating an LLM as an autonomous curator or
as a one-shot annotation generator, it treats the agent as a junior co-curator embedded
in a controlled workflow.

## Thesis and objectives

The central thesis is that an effective AI curation assistant should combine:

1. deterministic tools for operations that can be specified and tested;
2. carefully prompted model calls for steps that require language interpretation or
   editorial judgment;
3. source-linked review artifacts that make verification fast;
4. explicit human decisions at meaningful curation boundaries; and
5. a conversational orchestration layer that guides the curator without owning domain
   logic.

The immediate objectives are to:

- provide a MOAlmanac FDA curation skill and command-line tools that can be used from
  more than one agent harness;
- support human-in-the-loop creation and revision of FDA-derived MOAlmanac records;
- reduce the time required for first-time and update curation;
- preserve provenance between every proposal and the FDA source evidence; and
- make MOAlmanac's curation conventions easier for a new curator to learn and apply.

## Design principles

### Tools own domain behavior

All extraction, matching, classification, validation, proposal generation, and state
changes belong in the Python tools. This includes both deterministic logic and
purpose-built LLM calls. The tools should produce consistent artifacts regardless of
whether the conversational harness is Claude or ChatGPT/Codex.

The skill should remain an orchestration and review layer. It determines command order,
routes from declared tool outcomes, presents review artifacts, and obtains explicit
curator decisions. It should not independently recreate curation logic from prose
instructions or generate database fields ad hoc in chat.

### The human remains the curator

The pipeline generates proposals; the curator makes decisions. Generated output and
curator-approved output remain separate. A successful command does not imply approval,
and ambiguous results stop at a review boundary rather than being silently resolved.

### Evidence should be adjacent to every proposal

Curator-facing Markdown files link proposed values to the relevant converted FDA label
and, where useful, quote the bounded source passage. For revisions, review artifacts
show exact additions and removals as well as the full changed passage. The goal is to
minimize the time between seeing a proposal and verifying why it was made.

### Review should follow the curator's mental model

The interface presents conceptual curation steps rather than internal pipeline details.
For a new indication, the curator reviews the indication, description, and approval
evidence together before moving to the next indication. Internal downloads, caching,
changelog construction, and intermediate transformations are hidden unless they produce
an unresolved condition.

### Generated and source artifacts are immutable

Downloaded labels and pipeline-generated JSON, Markdown, and changelogs should not be
edited by hand. Supported changes are recorded through the CLI so that decisions remain
explicit and reproducible.

## High-level architecture

```text
Human curator
    |
    v
Conversational harness (Claude or ChatGPT/Codex)
    |
    v
MOAlmanac curation skill
  - explains the workflow
  - invokes stable CLI commands
  - presents review artifacts
  - collects explicit decisions
    |
    v
moalmanac-fda-curation tools
  - deterministic retrieval, parsing, matching, diffing, validation, and assembly
  - prompted LLM extraction and proposal steps
  - source-linked Markdown and JSON artifacts
    |
    +--> FDA label sources / Drugs@FDA
    |
    +--> local curation run directory
    |
    +--> local moalmanac-db checkout for existing records and schema context
```

The main code is organized as follows:

```text
src/moalmanac_fda_curation/
  core/       FDA retrieval, extraction, evidence, matching, and proposal logic
  review/     Review packets, recorded decisions, and final assembly
  workflows/  Curator-facing operations that combine lower-level steps
  cli.py      Stable command-line entry point
  doctor.py   Environment and setup checks

.claude/skills/moalmanac-fda-curation/
  SKILL.md    Top-level conversational routing
  references/ Branch-specific workflow and review instructions

tests/        Unit and workflow tests
analyses/     Ignored local run artifacts and development notebooks
```

## Workflow

Every session begins with an FDA NDA or BLA application number and a local path to
`moalmanac-db`. The workflow checks the environment and then determines whether the
application has already been curated.

```text
FDA application number
        |
        v
Check setup and curation status
        |
        +-------------------------------+
        |                               |
        v                               v
Not previously curated             Previously curated
        |                               |
        v                               v
Select latest approved label       Is a newer label available?
        |                               |
        v                         +-----+-----+
Review document                   |           |
        |                         no          yes
        v                         |            |
Extract indication candidates     stop         v
        |                                  Reconcile old and
        v                                  latest indications
Select biomarker-bearing candidates            |
        |                                +------+------+
        v                                |             |
For each selected indication:            v             v
  review indication                 New indications  Existing indications
  review description                     |             |
  review approval evidence               v             v
        |                           Curate eligible   Detect label changes
        v                           new indications       |
Assemble reviewed document and                              v
indication JSON                                  Review flagged revisions
```

### First-time curation

For an application that is not in MOAlmanac, the workflow:

1. selects and converts the latest approved FDA label;
2. prepares a proposed document record for curator review;
3. extracts candidate indications from Indications and Usage;
4. distinguishes findings outside the project's biomarker scope from candidates that
   can continue through MOAlmanac curation;
5. prepares the selected candidates in a batch;
6. reviews each retained indication vertically: indication text, description, and
   initial approval evidence;
7. records explicit accept, edit, exclude, or unresolved decisions; and
8. assembles `reviewed/document.json` and `reviewed/indication.json` only after all
   retained fields have complete decisions.

The description step may use relevant Clinical Studies or Clinical Pharmacology text
when it resolves a meaningful ambiguity, but it should not add trial details simply
because they are available.

### Update curation

For a previously curated application with a newer approved label, the workflow has two
phases.

First, it reconciles the existing MOAlmanac indications with the latest label. Confident
matches do not require curator review. Uncertain mappings produce a dedicated review
file. Any genuinely new, biomarker-bearing indications then enter the same
indication-level review used for first-time curation.

Second, it compares matched indications across the relevant label history. It creates
review Markdown only for indications with meaningful changes. Each packet includes the
word-level diff, the complete changed passage, proposed field changes, and available
historical approval evidence. Unchanged indications are omitted from curator-facing
review.

## Current implementation status

### Implemented

- Environment checks and guided setup.
- Drugs@FDA application lookup and selection of the latest approved label.
- FDA label download and conversion to Markdown.
- Document metadata extraction and source-linked document review.
- Indication extraction from Indications and Usage.
- Biomarker-scope screening and selection of curation candidates.
- Proposed indication, description, raw biomarker, raw cancer type, and raw therapy
  fields.
- Label-history retrieval and Indications and Usage changelog construction.
- Initial indication approval-date matching against historical labels.
- Explicit decision recording for the first-time workflow and for new indications found
  during an update.
- Assembly of reviewed `document.json` and `indication.json` for first-time curation.
- Preflight detection of previously curated applications and newer labels.
- Reconciliation of existing MOAlmanac indications against a newer label.
- Identification of new indications in a newer label.
- Detection and proposal of revisions to existing indications using bounded label
  diffs.
- Source-linked Markdown review surfaces and reusable orchestration instructions for
  Claude and ChatGPT/Codex.
- Automated tests covering the main first-time and update workflow components.

### Partially implemented or intentionally out of scope today

- Revision proposals for existing indications can be generated and reviewed, but
  revision decisions are not yet persisted.
- Reviewed update records are not yet assembled into database-ready output.
- The workflow does not create or update URL records required by the referenced
  MOAlmanac schema.
- The project does not write directly to `moalmanac-db`.
- It does not create a branch, commit changes, push to GitHub, or open a pull request.
- The current source scope is FDA drug labels; other regulatory agencies and evidence
  types have not been implemented.

## Recommended next steps

### 1. Complete the update workflow

This is the clearest functional gap. Add supported decision recording for proposed
revisions, then assemble curator-approved new and revised indications into one reviewed
update artifact. Define how excluded and unresolved revisions are represented and
ensure the final output cannot be assembled while required decisions remain unresolved.

### 2. Bridge reviewed output into `moalmanac-db`

Design a controlled export or application step that validates reviewed records against
the current database schema, assigns or checks identifiers, creates any required URL
records, and produces a transparent change set. Preserve the separation between
proposal, curator decision, and database mutation.

### 3. Add an optional GitHub contribution workflow

After database export is reliable, consider commands that create a curation branch,
write the validated change set, update the content changelog, run database tests, and
prepare a pull request. These should require explicit authorization and should not be
implicit consequences of completing review.

### 4. Evaluate accuracy, speed, and curator experience

Run a structured evaluation on both unseen first-time approvals and labels with known
historical updates. Useful measures include:

- field-level agreement with expert-curated records;
- precision and recall for detecting new and revised indications;
- curator accept, edit, exclude, and unresolved rates by field;
- factual or provenance errors, especially unsupported added detail;
- time to complete curation compared with the existing manual workflow;
- time spent at each review boundary; and
- differences between experienced and newly onboarded curators.

Evaluation should distinguish pipeline proposal quality from final human-reviewed
quality. It should also record whether confidence or validation flags predict curator
edits.

### 5. Improve operational documentation and reproducibility

Add a small set of end-to-end fixtures or recorded demonstrations covering:

- a first-time application with one indication;
- a first-time application with multiple candidates and an exclusion;
- an existing application with no newer label;
- a newer label with a new indication;
- a newer label with a revised indication; and
- an ambiguous match or unresolved approval date.

Document model versions, prompt changes, and evaluation results so changes in LLM
behavior can be detected rather than mistaken for code regressions.

### 6. Consider broader generalization only after the FDA workflow is complete

The architecture may apply to other regulators, guidelines, or literature curation, but
each source has different evidence structures and editorial rules. Keep shared concepts
such as provenance, review decisions, and artifact assembly reusable while implementing
source-specific domain behavior in dedicated tools.

## Research and publication direction

A paper could frame this project as a human-in-the-loop framework for producing
structured, evidence-grounded genomic knowledge assertions. The contribution is not
simply using an LLM to extract fields. It is the combination of:

- an end-to-end curator workflow;
- deliberate allocation of deterministic and model-based tasks;
- encoded expert guidance at subjective steps;
- evidence adjacent to every proposed assertion;
- explicit curator control over state transitions; and
- a harness-independent skill for conversational interaction.

Potential research questions include:

1. How accurately does the system generate each component of a structured FDA
   assertion?
2. Which fields require the most curator correction?
3. How well does it distinguish new, unchanged, and revised indications?
4. Does source-linked review reduce curation time without reducing accuracy?
5. Do validation findings or model confidence predict curator edits and exclusions?
6. Does the guided assistant improve the consistency or speed of newly onboarded
   curators?
7. Which parts of the framework generalize beyond MOAlmanac and FDA labels?

The paper should compare raw proposals, final curator-reviewed outputs, and an expert
reference standard. It should report both accuracy and the amount of human effort
required to reach that accuracy.

## Getting started as the next developer

You will need:

- Python 3.11 or newer;
- an Anthropic API key;
- the Claude or ChatGPT desktop application;
- a clone of `moalmanac-fda-curation`; and
- a local clone of `moalmanac-db`.

Start with the repository `README.md`, then read these files in order:

1. `AGENTS.md` for the project's implementation principles.
2. `.claude/skills/moalmanac-fda-curation/SKILL.md` for top-level orchestration.
3. `.claude/skills/moalmanac-fda-curation/references/workflow-tools.md` for the stable
   CLI and artifact contract.
4. `references/new-curation.md` and `references/update-curation.md` for the two workflow
   branches.
5. `references/review-standards.md` and `references/review-formats.md` for curator-facing
   behavior.
6. The tests corresponding to the workflow you plan to change.

Run the setup check before attempting curation:

```shell
moalmanac-fda-curation check-setup
```

Use a separate `analyses/<ApplicationNumber>/` directory for each local curation run.
Do not commit API keys or local run artifacts.

## Open questions

- What is the exact database-ready representation of an update containing both new and
  revised indications?
- Should the pipeline generate referenced URL records, or should that remain a database
  integration responsibility?
- How should a curator reopen or amend a previously recorded decision while preserving
  an audit trail?
- Which model outputs need calibrated confidence, and how should that confidence affect
  the review interface?
- What is the appropriate expert reference set for evaluating revised indications?
- How should prompt and model-version changes be regression tested?
- At what point, if any, should the system learn from curator edits rather than relying
  on manually maintained prompts, examples, and rules?
- Which parts of the workflow are sufficiently general to extract into a reusable
  curation framework?

## Repository and project links

- MOAlmanac FDA curation assistant:
  <https://github.com/sabrinacamp2/moalmanac-fda-curation>
- MOAlmanac database: <https://github.com/vanallenlab/moalmanac-db>
- MOAlmanac: <https://moalmanac.org>
- Drugs@FDA: <https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm>

## Contacts

Add the primary scientific, engineering, and curation contacts here, along with any
project-specific communication channels and access instructions that should not be
stored in the repository.
