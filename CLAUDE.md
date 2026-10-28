@AGENTS.md

# Claude Code Specifics

Shared, tool-agnostic project instructions live in `AGENTS.md` (imported
above). This file only records what Claude Code adds on top of them.

- `.claude/settings.json` holds one thing: a SessionStart hook that runs
  `just install` in a Claude Code cloud session (`CLAUDE_CODE_REMOTE=true`)
  and does nothing locally, since a cloud session reads no user-level or
  `.local` settings. The guard rails stay git hooks (`AGENTS.md`'s
  "Enforcement layers"), which run for every author. Permission rules, plugin
  marketplaces, and personal hooks such as format-on-edit (its snippet is in
  the `changing-gates` skill's `references/pre-commit-layer.md`) belong in
  `~/.claude/settings.json` or the gitignored `.claude/settings.local.json`.
- `.mcp.json` holds one server: `awsknowledge`, the AWS Knowledge MCP server
  (AWS documentation search and the AWS agent skills through `retrieve_skill`).
  It needs no credentials and is the AWS reference a cloud session has, because
  a cloud session loads no plugin, even one a committed `enabledPlugins` names.
  A server that acts on an AWS account needs credentials, so it stays a
  personal plugin (`aws-core`) in `.claude/settings.local.json`.
- `.claude/skills/` is a generated mirror of `.agents/skills/`. Never hand-edit
  it: edit `.agents/skills/`, run `just agents-sync`, and commit both.
- Each area's `CLAUDE.md` (`backend/CLAUDE.md`) only imports the `AGENTS.md`
  beside it, which Claude Code loads once it reads or edits a file in that
  directory: edit the area's `AGENTS.md`, never its `CLAUDE.md`.
- Hand a step to a sub-agent tier by `subagent_type` — `executor`, `architect`,
  `scout`, or `worker` — never by a bare `model`, which runs at the session's default
  effort rather than the tier's. The definitions in `.claude/agents/` shadow
  same-named ones in `~/.claude/agents/` inside this repository.
