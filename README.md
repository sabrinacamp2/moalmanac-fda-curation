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
  doctor.py                   Installation and environment checks
.claude/skills/               Agent workflow instructions
tests/                        Workflow and review tests
analyses/                     Local curation runs; not committed
```

## Current scope

The workflow currently creates new entries from FDA labels. It does not yet revise
existing MOAlmanac records, update `moalmanac-db`, or open pull requests.
