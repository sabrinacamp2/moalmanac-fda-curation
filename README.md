# MOAlmanac FDA Curation Assistant

An agent-assisted workflow for turning FDA oncology product labels into reviewed
[Molecular Oncology Almanac](https://moalmanac.org) document and indication JSON.

The pipeline retrieves label evidence and generates structured proposals. A reusable
skill lets Claude or Codex guide the curator through source-linked review, edits,
exclusions, and final assembly.

## Install

Requirements: Python 3.11+, an Anthropic API key, and either the
[Claude](https://code.claude.com/docs) or [ChatGPT](https://developers.openai.com/codex/)
desktop app.

```shell
git clone https://github.com/sabrinacamp2/moalmanac-fda-curation.git
cd moalmanac-fda-curation
test -d .venv || python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
export ANTHROPIC_API_KEY="YOUR_API_KEY"
moalmanac-fda-curation doctor
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

## Repository structure

```text
src/moalmanac_fda_curation/   Pipeline and review tools
.claude/skills/               Agent workflow instructions
tests/                        Workflow and review tests
analyses/                     Local curation runs; not committed
```

## Current scope

The workflow currently creates new entries from FDA labels. It does not yet revise
existing MOAlmanac records, update `moalmanac-db`, or open pull requests.
