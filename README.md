# MOAlmanac FDA Curation Assistant

An agentic, human-in-the-loop workflow for evidence-backed FDA label curation for the
[Molecular Oncology Almanac](https://moalmanac.org).

The pipeline retrieves label evidence and generates structured proposals. A reusable
skill lets Claude or Codex guide the curator through source-linked review, edits,
exclusions, and final assembly.

## Get started

You need Python 3.11+, an Anthropic API key, and either the
[Claude](https://code.claude.com/docs) or [ChatGPT](https://developers.openai.com/codex/)
desktop app. Clone the repository, open its folder in the desktop app, and invoke the
curation skill. The agent will inspect the environment and guide you through any needed
setup.

```shell
git clone https://github.com/sabrinacamp2/moalmanac-fda-curation.git
```

Do not commit API keys.

## Recommended experience

We recommend using the Claude or ChatGPT desktop app. Their conversational interface and
file previews make it easier to move through the review, open generated Markdown, inspect
source evidence, and ask questions without losing your place.

## Curate with Claude

Open the cloned repository in the Claude desktop app's Code tab, then invoke the project
skill:

```text
/moalmanac-fda-curation
```

Provide an NDA or BLA application number when prompted. The skill selects the latest
approved label, explains each phase, and links the generated review files. You can ask
questions, inspect local source evidence, edit proposals, exclude indications, and accept
the final reviewed output.

## Curate with ChatGPT

Open the cloned repository in Codex in the ChatGPT desktop app and ask:

```text
Use the MOAlmanac FDA curation skill at
.claude/skills/moalmanac-fda-curation/SKILL.md to curate a new FDA label.
```

Then provide the NDA or BLA application number when prompted. The review workflow and
outputs are the same in either harness.

To find the application number, search the drug or active ingredient in
[Drugs@FDA](https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm). Open the product
record and use its NDA or BLA number, for example `NDA208558` or `BLA761174`.

Completed runs write `reviewed/document.json` and `reviewed/indication.json`. Generated
proposals remain separate from explicitly accepted curator decisions.

For an application that MOAlmanac already curated and that has a newer approved label,
the update workflow combines latest-label preparation, indication extraction, and
reconciliation into one routing step:

```shell
moalmanac-fda-curation find-new-indications \
  --application-number BLA125554 \
  --database-dir /path/to/moalmanac-db \
  --work-dir analyses/BLA125554
```

Successful matches are retained in JSON without requiring review. If any existing
indication is not found or a mapping is uncertain, review
`review/reconciliation-exceptions.md` before continuing. Otherwise, curate any new
indication indexes printed by the command and then proceed to revision analysis.

Revision analysis uses `prepare-revision-review`. It retains the complete assessment in
JSON while creating Markdown only for indications flagged as revised. Each review shows
the exact removed and added words, the complete changed label passage, and proposed field changes;
unchanged indications are omitted from curator-facing review. The existing historical
event matcher runs on the bounded baseline-to-latest changelog and uses a verified later
event to populate `initial_approval_date` and `initial_approval_url` in a full proposed
indication record.

## Manual setup and troubleshooting

If guided setup does not complete successfully, see the
[workflow commands and environment checks](.claude/skills/moalmanac-fda-curation/references/workflow-tools.md#setup).

## Repository structure

```text
src/moalmanac_fda_curation/
  core/                       FDA extraction and evidence logic
  review/                     Review packets, decisions, and final assembly
  workflows/                  Curator-facing workflow orchestration
  cli.py                      Stable command-line entry point
  doctor.py                   Implementation for the `check-setup` command
.claude/skills/               Agent workflow instructions
tests/                        Workflow and review tests
analyses/                     Revision notebook plus ignored local curation runs
```

## Current scope

The primary reviewed workflow creates new entries from FDA labels. CLI analysis commands
also check whether an application was previously curated, reconcile existing indications
against a newer label, identify revised indications from deterministic source diffs, and
propose minimal patches. These update commands do not yet record curator decisions or
assemble reviewed database updates. The project does not write to `moalmanac-db`, commit,
push, or open pull requests.
