# MOAlmanac curation tools

Evidence-backed FDA oncology-label curation tools and agent skills for
MOAlmanac collaborators. The repository is designed to run inside an existing
agent harness such as Claude Code or Codex; it does not implement its own agent
or require the experimental `ai-assisted-gk-curation` repository.

## What is included

- Installable Python commands for document preparation, indication extraction,
  description generation, Section 1 history, approval-date matching, and final
  draft assembly
- A project Claude Code skill under `.claude/skills/moalmanac-curation/`
- Raw-label, source-span, changelog, and verification artifacts for curator review
- An optional fixture-backed UI experiment retained under
  `moalmanac_curation_agent`

The workflow creates draft files only. It does not modify `moalmanac-db`, commit,
push, or open pull requests automatically.

## Install

```bash
git clone REPOSITORY_URL
cd moalmanac-curation-agent
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Set `ANTHROPIC_API_KEY` before running extraction, description, or approval-date
matching commands. Do not commit credentials. See `.env.example` for variable
names used by the project.

## Use with Claude Code

Start Claude Code from the repository root so it discovers the project skill:

```bash
claude
```

Then ask naturally:

```text
Help me curate NDA208558 using this pinned FDA label. Show me evidence and pause
for review before each downstream model call.
```

You can also invoke `/moalmanac-curation` explicitly when it is listed by the
harness.

## Commands

```text
moalmanac-curation prepare-document
moalmanac-curation extract-indications
moalmanac-curation generate-descriptions
moalmanac-curation build-history
moalmanac-curation match-dates
moalmanac-curation assemble-draft
```

Run `moalmanac-curation <command> --help` for full arguments. Regeneration flags
can make paid model calls, so inspect existing artifacts first.

## Optional UI experiment

The earlier fixture-backed interaction prototype remains available for product
exploration and is not required for the scripts-and-skills workflow:

```bash
moalmanac-curation-demo
```

