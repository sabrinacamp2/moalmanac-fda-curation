# MOAlmanac FDA Curation Assistant

This project helps curators add FDA-approved oncology indications to the
[Molecular Oncology Almanac](https://moalmanac.org) and keep existing entries current
when labels change.

Give it an FDA application number and it finds the relevant label, checks what
MOAlmanac has already curated, and guides you through only the decisions that need human
review. You can compare proposed entries with their FDA evidence, make corrections, and
produce reviewed JSON ready for the database.

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

Open the repository in Claude's Code tab and run:

```text
/moalmanac-fda-curation
```

## Curate with ChatGPT

Open the repository in Codex and ask:

```text
Use the MOAlmanac FDA curation skill in this repository.
```

In either app, provide an NDA or BLA application number when prompted.

To find the application number, search the drug or active ingredient in
[Drugs@FDA](https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm). Open the product
record and use its NDA or BLA number, for example `NDA208558` or `BLA761174`.

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

The reviewed workflows create new entries from FDA labels and update existing entries
when a newer label changes their indications. The CLI checks whether an application was
previously curated, identifies new and changed indications, records explicit curator
decisions, and assembles reviewed JSON artifacts for the affected MOAlmanac records. The
project does not write directly to `moalmanac-db`, commit, push, or open pull requests.
