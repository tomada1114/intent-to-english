# Landing the reviewed dependency plan

Use this after reviewing and recording the plan in SKILL.md. Keep each action
within the requested outcome and follow `AGENTS.md`'s "Task scope and confirmations".

## Individual PRs

Process selected PRs in ascending number, one at a time. Immediately before each merge,
verify its current head, repeat SKILL.md's Step 2 review if that head changed, and check
the complete required check set, feedback and required approvals. Confirm the merged
state and landed commit afterwards.

An earlier merge can leave a later selected PR behind the base. Request the
necessary bot rebase covered by the plan, then observe the changed head. Apply Step 4's
review and task-scope comparison before accepting its new checks. The planned
comment is:

```text
@dependabot rebase
```

That comment is a request, not a successful rebase. Never merge on checks for its old
head. Record each needed rerun's run/job and reason. Request confirmation when
required by the operation, reusing any approval that already covers it.

Every merged `uv` PR leaves the next one's `uv.lock` stale, and every merged
`npm_and_yarn` PR the next one's `pnpm-lock.yaml`, so each ecosystem's PRs land this
way one after another: merge, wait for Dependabot to rebase the next PR on its own (it
regenerates the lock), request that rebase with the comment above only if it has not
happened, review its new head, and only then merge it.

## Combined PR

Start an owned, clean branch (or worktree) from the current default-branch commit.
Record the base and the exact reviewed Actions and versions. Read each selected PR's
full diff to learn the intended changes; do not integrate its commits or resolve a
conflict by picking whichever version is higher.

Apply one reviewed change at a time:

- For an Action, edit only the reviewed `uses:` pins — every occurrence of that Action
  across `.github/workflows/` — copying the full new SHA and the `# vX.Y.Z` version
  comment from the reviewed PR exactly. Changes to permissions, triggers, secrets or
  source require the separate decision in SKILL.md.
- For a pre-commit hook reviewed in the plan, set its `rev:` in
  `.pre-commit-config.yaml` to the reviewed revision. Nothing else in that file changes.
- For a `uv` package the plan puts on the combined branch, apply the reviewed PR's
  range change to `backend/pyproject.toml` or the root `pyproject.toml`, if it has one,
  by hand, then regenerate the lock with `uv lock --upgrade-package <package>==<version>` for
  each reviewed package and version. A `python-minor-patch` group holding `ruff` moves
  whole: every member and every range edit the group PR made; the
  group PR closes as superseded only after the combined PR merges. `uv.lock` is never
  hand-edited and never taken
  from a bot branch, and the window still applies. A `[[package]]` the regenerated
  lock adds that the reviewed PR did not is a new package: SKILL.md's "Stop and ask".

### Verify and publish

```bash
just verify
uv run --locked pre-commit run --all-files
```

`just verify` is the non-mutating gate; the pre-commit run adds what it does not cover
for a workflow change — the `zizmor` workflow audit, `typos`, and YAML checks. Apply only
settled mechanical fixes inside the requested scope. A migration, new dependency,
changed supply-chain decision or weakened check is not such a fix.

Commit with the normal hook, inspect the committed tree, and push only the task
branch. Open or update its PR against the recorded default branch with a Conventional
Commit title (`chore(deps): …`) and `.github/PULL_REQUEST_TEMPLATE.md`, labelled
`dependencies` — the PR-title check skips that label, but a valid title keeps the
history consistent. Include the exact selected original PRs, Action versions and unit
completion, the pin review, executed checks, release-note findings, and the requested
stopping point.

Wait for all required current-head CI, review and approval evidence. A correction push
invalidates the previous head's evidence. Diagnose a required failure instead of waiting
passively; record needed reruns and ask about unresolved decisions outside the plan.

## Confirm landing before closing originals

When the requested outcome includes merge, re-read the head and default branch;
merge only the verified head and confirm the returned merge commit and PR state. A
requested PR-only run leaves the combined PR and originals open.

After a confirmed combined merge, close only the superseded originals identified in
the plan with a pointer to the combined PR. Confirm destructive cleanup targets before
deleting branches within the task, reusing existing approvals. Verify each closure
and deletion. If the combined PR remains open or is abandoned, leave the
originals open. Report partial cleanup separately from a successful merge.
