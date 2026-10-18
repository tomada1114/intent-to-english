# Closing out: cleanup and report

Read at step 8c (re-queueing the run's own output), step 9 (cleanup) and step 10
(report) — everything past the ordering and safety rules the SKILL.md body already
states inline.

## Table of Contents

- [Re-queueing the run's own output](#re-queueing-the-runs-own-output)
- [Cleanup scope](#cleanup-scope)
- [Approval-gated commands](#approval-gated-commands)
- [What the report must not omit](#what-the-report-must-not-omit)

## Re-queueing the run's own output

Before cleanup, re-plan (`plan.py --mode <same> --refresh --allow-existing-worktrees`)
and keep going through **what this run produced**: the follow-ups filed at step 8 and
the issues step 8b unblocked. Each runs the same steps 3–8, one PR at a time. With an
explicit issue number, the re-plan only ever looks at that number and prints
`select: none` — so re-plan each candidate by its own number instead
(`plan.py --mode <m> --refresh`). Take one on only when all three hold:

1. **Depth 1** — it came from _this_ run's own work. A follow-up filed while shipping a
   follow-up is recorded and left for the next run.
2. **Shippable on the ordinary [readiness gate](dependency-triage.md#readiness-gate)**;
   a `DEFERRED` design is not.
3. **[Budget left](cost-discipline.md#run-budget).** Out of budget, or a design decision
   still in flight once everything else is done → stop and name it at step 10 rather
   than waiting.

In `all` mode these join the existing queue with no privilege over the backlog's own
issues. With no argument or an explicit number, this step is the _only_ thing that
extends the run past its first merge.

## Cleanup scope

Preview first. Inspect the target branches, worktrees and any gitignored artifacts
before confirming the concrete deletions, reusing an approval that covers them.
Only after confirmation, run the same cleanup command without `--dry-run` and verify
its result. The preflight cache update follows cleanup when applicable.

```bash
.agents/skills/shipping-issues/scripts/cleanup_run.sh --dry-run --branch <name> [--branch <name> ...] \
    [--remote] [--worktree-root <runstate>/worktrees] [--merged-only] [--force]
.agents/skills/shipping-issues/scripts/preflight.sh \
    --profile-cache <runstate>/repo-profile.json --set-worktree-viable <yes|no>
```

Step 7 already left `HEAD` on the up-to-date default branch, which the branch deletion
requires — it refuses to delete whatever is currently checked out, in the main checkout
_or_ in a surviving worktree. Pass every branch this run created as `--branch <name>`.
Without it the script deletes every merged-PR branch in the repository — other people's
included — which is not this run's to decide. Pass `--worktree-root` only when this run
created worktrees. The `preflight.sh` call runs only when this run actually probed
worktree viability; it persists the answer so the next run's plan skips the probe.

All deletion goes through `cleanup_run.sh`, in **one batch after the last merge** — not
once per batch. Never run `rm`, `git worktree remove`, or `git branch -D` ad hoc in the
main context or in a sub-agent: the single entry point gates deletion on merge
status. Confirm destructive targets before cleanup, reusing existing approvals.

**That covers temporary files too, not just the repository.** A throwaway fixture, a
scratch clone, a probe directory under the session scratchpad or `/tmp` is left exactly
where it is until the final cleanup decision. Revert a probe _inside_ a
checkout with `git checkout --` or by moving it out with `mv` into the holding area
([below](#approval-gated-commands)), never with `rm`. Say in the step 10 report where
any leftover scratch directories are; the holding area is offered for deletion in the
final confirmation, a scratchpad left in place is the user's to delete if they care.
Every sub-agent prompt that has a sub-agent create a fixture must carry this prohibition
explicitly — three separate agents in one observed run reached for `rm` on their own
scratch directories despite the instruction being implied rather than stated.

Deleting worktrees mid-run to stay under the concurrency cap is the one tempting
exception, and it complicates cleanup ownership and recovery. Carry
them to the end and clean once. If disk genuinely is the constraint, that is a reason to
shrink the batch, not to add cleanup calls. The script touches only: worktrees under an
explicitly given `--worktree-root`; harness `worktree-agent-*` branches (a leftover
branch-naming convention from the Claude Code harness — a different thing from this
skill's own worktrees, which are never branch-named that way); and branches whose PR is
merged. `--remote` extends the last of those to the same refs on origin. Nothing this
run generated should be sitting uncommitted in a checkout to begin with: prompts, issue
bodies and CI logs all live under `<runstate>/` (run-record.md).

**The worktree pass runs first, and only when `--worktree-root` is given.** A branch
checked out in a worktree cannot be deleted, so the worktrees have to go before the
branch pass can do its job; a serial run passes no root and the pass is skipped, which
is correct. Two things decide how to call it — the default removes every worktree under
the root including one another session may be using, and gitignored files inside a
worktree are lost with it — both spelled out in
[worktree-parallelism.md#teardown](worktree-parallelism.md#teardown).

Record the cleanup outcome (`--event cleanup ...`) and report anything it left
`SKIPPED`.

## Approval-gated commands

When the host requires approval, prepare the exact command, target and effect,
then ask the user. A required operation is not prohibited merely because it needs
confirmation. Preserve the current state and continue independent work while the
approval is pending. Never change commands or tools to evade a denial.

Batch optional cleanup at the end of the run. Keep disposable files in place until
then, or move task-owned files to the holding area when preserving them is part of
the intended change. Check targets before any move or deletion; do not touch
unrelated files. A holding-area move is a preservation choice, not a substitute
for an approval required by the action.

If acceptance or a required check cannot proceed without the operation, request
approval at that point and report what needs to run and why. Do not skip the check
or defer a necessary operation while claiming completion. An unavailable approval
channel is a reported blocker for that operation, not permission to bypass it.

**The holding area** is `<runstate>/holding/<n>/` — `<n>` the issue being worked, `run`
for anything not tied to one. It sits outside every checkout, so a moved-out directory
never reads as untracked content (the reason `<runstate>` exists —
[run-record.md](run-record.md)). Keep the original's relative path under it
(`holding/42/src/intent_to_english/legacy/`) so the report can name what came from where; on a
name collision add a suffix rather than overwrite. A move across filesystems is a
copy-then-delete — fine for a fixture, slow for a `.venv`; keep holding for what
the run actually needs out of the way. **Never move anything this run did not create or
the issue did not name** — the holding area is not a way to clear someone else's
untracked work out of a dirty tree; that is a
[stop condition](../SKILL.md#stop-conditions).

Sub-agents follow the same rule and are handed the path as `{holding_dir}`
([delegation-templates.md](delegation-templates.md#standing-prohibitions-for-every-brief));
their reports name what they moved there.

### The final confirmation

If `<runstate>/holding/` or `<runstate>/deferred.md` holds optional cleanup from this
run, prepare one concrete cleanup proposal. List each held path with its original
location and each deferred command with its reason. Reuse existing approvals or
request the remaining confirmation once, then run the approved cleanup and verify
the result before the final report. Delete only this run's holding directories,
never `<runstate>/holding/` wholesale: earlier holdings remain untouched.

If confirmation is declined or the host refuses the call, preserve the paths and
report the unfinished cleanup. Do not retry with different command spelling.
Nothing required for the PRs to count as shipped may be deferred here; merges and
issue closures must already be verified.

## What the report must not omit

**There is no prescribed report format.** Shape, order and headings are yours — write
the report the run actually needs. What is fixed is the list below: each line is a fact
whose absence changes what the reader believes happened, so omitting one is a defect,
not a stylistic choice.

- **Any issue left open behind a merged PR.** This is the failure mode the skill exists
  to prevent; it can never be implied, only stated.
- **How each merged PR was reviewed** — each round's verdict and the commit it read
  (`reviewed_sha:`), every finding with its round, its classification (accepted,
  rejected, out of scope, or accepted and filed as a follow-up for its `P3` badge) and
  reason, which commit fixed the fixed ones, any `REJECTED` line from a fix run this
  session did not resolve, and whether the last fixes got a review of their own or
  landed on `NO_NEW_REVIEW` or the 3-round cap, verified locally and by current-head CI.
  A finding past the cap left untriaged is named, and so is a review that completed
  after its PR merged (`completed_at:` later than the merge), so it can be checked. A
  PR held on `NO_REVIEW` or a review `ERROR` is named with the PR left open. A run that
  shipped unreviewed must not read like one that passed.
- **Acceptance criteria that shipped `not-met`, and why that was accepted.** If none
  did, say the criteria were met. If the issue carried none, say that — rather than
  implying it passed a check it never had.
- **Every `DEFERRED` design's open question**, phrased as the question. These are the
  only part of the report the user has to act on.
- **Follow-ups filed**, what was fixed _inline_ instead of filed (an unexplained widened
  diff is indistinguishable from scope creep), and findings checked and deliberately
  _not_ filed with what prevented each — a verified non-issue is a result, and silence
  reads as "nothing was noticed".
- **Everything held or deferred**, and any approval-gated command that had to run
  mid-run with why it could not wait — see
  [the final confirmation](#the-final-confirmation).
- **Operator actions** the run surfaced — things resolved by running a command or
  changing a setting rather than by a PR. The backlog will never show them, so the
  report is their only record.
- **A serial fallback when parallel was expected**, and which gate failed. Otherwise a
  repository that could not support worktrees reads as a slow run.
- **The verification command actually used**, when the plan's suggestion was overridden.
- **Issues whose ship contract had to be guessed at** — the `PARTIAL` grouping's
  undeclared issues and anything `issue_digest.py --audit` flagged. This is what stops
  the next run paying the same judgement cost.
- **What was left undone, with the specific reason each** — blocked, needing
  clarification, hit the retry ceiling, still held for `blocked: design`, or a design
  agent still queued or in flight. An issue whose design this run decided but whose
  implementation it did not reach is **ready**, not blocked: it is the next run's first
  candidate, and that is a different thing from being stuck.
