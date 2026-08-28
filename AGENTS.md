# Agent guidance

## Keep skills orchestration-focused

Skills should coordinate CLI tool calls and the curator interaction around them. They
may define command order, workflow branches, review and stop points, artifact links,
and when an optional harness assessment would provide a useful second check.

Implement domain behavior in the tools, not in skill instructions. This includes
extraction rules, matching and classification semantics, validation, protected wording
guidance, revision detection, approval-date attribution, and artifact construction.
The skill should route from the tool's declared outputs rather than duplicate,
reinterpret, or independently reimplement that logic.

When a workflow needs new deterministic behavior, add or extend a CLI command and test
it there. Then keep the corresponding skill change limited to invoking the command and
handling its curator-facing outcomes.

## Do not preserve compatibility by default

This repository is a pilot project without external users. Do not retain deprecated
commands, aliases, schemas, artifact names, or behavior solely for backward
compatibility. Prefer the clearest current interface and update the implementation,
tests, documentation, and skill together. Preserve compatibility only when the user
explicitly requests it for a particular change.
