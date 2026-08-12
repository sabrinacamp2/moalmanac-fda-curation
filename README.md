# MOAlmanac FDA-label curation

Tools for turning an FDA oncology product label into reviewable
[Molecular Oncology Almanac](https://moalmanac.org) document and indication drafts.

The repository combines a Python pipeline with a Claude Code skill. The pipeline
extracts and structures label evidence; Claude Code presents the results step by step
so a curator can review, edit, or exclude each proposal.

## Workflow

Given an FDA application number, the workflow can use the latest approved label to:

1. prepare document metadata;
2. extract biomarker-relevant indications;
3. draft descriptions from relevant label sections;
4. track how the approved indications changed across label versions;
5. propose initial approval dates; and
6. assemble draft MOAlmanac JSON.

Generated values remain proposals. The workflow retains source text and provenance so
the curator can verify them before acceptance.

## Setup

Requirements: Python 3.11+, Claude Code, and an Anthropic API key.

```bash
git clone <repository-url>
cd moalmanac-fda-curation
test -d .venv || python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
export ANTHROPIC_API_KEY="YOUR_API_KEY"
moalmanac-fda-curation doctor
```

Do not commit API keys.

## Guided curation

Start Claude Code from the repository root:

```bash
claude
```

Invoke the project skill:

```text
/moalmanac-fda-curation
```

Then provide the FDA application number. The workflow selects the latest approved
label and shows its date for confirmation. A specific label URL can optionally
be supplied to curate an earlier label version. The skill guides the curation one
review decision at a time.

To find the application number, search the drug or active ingredient in
[Drugs@FDA](https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm). Open the product
record and use its NDA or BLA number, for example `NDA208558` or `BLA761174`.

## Command line

The pipeline can also be run directly:

```text
moalmanac-fda-curation prepare-document-review
moalmanac-fda-curation extract-indication-candidates
moalmanac-fda-curation prepare-selected-review
moalmanac-fda-curation record-decision
moalmanac-fda-curation assemble-reviewed
```

Run `moalmanac-fda-curation <command> --help` for command options.

## Current scope

The workflow currently creates new-entry drafts. It does not yet reconcile revised
labels with existing MOAlmanac records, update `moalmanac-db`, or open pull requests.
Curator review is required before using any generated content.
