# Pre-PR review, current-head CI and landing

## Review the branch before the PR

No review of the PR is waited for, requested or polled: the integration's automatic
review is not part of this workflow. Review happens on the branch, before it is
published, in a context that did not write the change.

1. Settle the diff identity: base SHA/ref and the branch head being reviewed, with local
   verification (`just verify`) already green.
2. Run one **read-only, fresh-context** review of `<base>...HEAD`. Use a sub-agent where
   the host provides one and the project is trusted (the `architect` tier for review);
   otherwise a separate pass that starts from the issue body, the acceptance map and the
   diff alone, not from the implementation's reasoning. It must not edit, create or
   delete anything, and it makes no GitHub write. It judges what the tests cannot: does
   the diff match what the issue asked, nothing missing and nothing widened; needless
   complexity; maintainability; whether the tests would fail with the bug present; a
   sibling case or silent error path the diff walked past. It reports defects, not
   patches: file, line, what is wrong, why it matters, with a severity.
3. Number the findings `F1`, `F2`, … and classify **every** one with a reason judged
   against the code: **accepted** (real, and part of this issue's own change, tests
   included), **rejected** (wrong on reading the code), or **out of scope** (real but
   not this diff's). A schema change or a new public surface is never accepted into the
   diff however small. A finding that needs an owner's decision, or a correctness
   finding you cannot settle, blocks publication: report it and preserve the branch.
4. Fix the accepted findings in this worktree, inspect the complete correction diff,
   run affected checks and `just verify`, and commit with normal hooks. One pass: do not
   re-review the fixes; local verification and current-head CI cover them.
5. Record the base/head reviewed, each finding with its classification and reason, the
   commit that addresses each fixed one, and out-of-scope findings as follow-up
   candidates; use `triaging-issues` when the requested workflow includes filing follow-ups.

Never post `@codex review`, change review settings, or close/reopen a PR to start a
review, and never read, reply to or resolve a review thread on the PR as part of this
run. Repository-required approvals and checks are separate from this review and cannot
be bypassed.

## Record revisions separately

Record repository, issue, PR URL/number, the head the pre-PR review read, current head
SHA, base SHA/ref, correction commits and check/run evidence. Refresh head/base when
checking CI or landing. A changed diff invalidates old CI and local acceptance
evidence, and a head the review did not read is reported as such.

## Verify CI on the current head

The local gate excludes process integration (`placing-tests`). Before landing,
require the `Coverage` job to execute and pass its process selection as well as
the ordinary tests; a local pass alone does not supply that CI-only evidence.

When `create-pr`'s host-restriction route was used, match each blocked local check to
the unchanged CI job and its successful result on this head. Record local failure
and remote success separately. A job missing the relevant test or acceptance does
not supply that evidence. The exception permits publication, never an unverified
merge or a claim that the local gate passed.

Inspect workflows, jobs/steps and required checks for the latest head through MCP or CLI,
including pagination. Compare with the committed ruleset and workflows; inspect
live requirements/approvals where either exposes them. Report unavailable policy fields
without inventing approvals or bypassing server-enforced requirements.

A green check for one job, an earlier SHA or a partial response is insufficient.
Distinguish success, failure, pending, skipped, cancelled and inaccessible checks.
A skipped required check is not success unless active policy explicitly permits it.
Diagnose failures as they appear. Any correction or changed
base integration requires fresh local acceptance and CI for the resulting head.
For an in-scope retry, record the reason and actual head/run and request confirmation
if the operation requires it. Never change settings or dispatch unrelated workflows
merely to obtain missing evidence.

Use bounded observations (at most 60 seconds per blocking wait) and back off when
state is unchanged. Continue in-scope repairs without an arbitrary attempt cap.
Pending checks or elapsed time alone do not complete a run. Honor user
deadlines and host limits. Once current-head gates pass, nothing else is waited for.

## Land within the requested outcome

At a PR-only boundary, preserve the open PR. When the requested outcome includes merge:

1. Refresh head/base, mergeability, known findings, required approvals and all
   expected checks. Confirm the pre-PR review's accepted findings have correction
   evidence and local acceptance/CI cover the current diff. Integrate
   the current default branch normally if needed, repeat local checks and CI, and
   inspect the resulting diff. Do not force-push.
2. Merge with an expected-head-SHA guard and an allowed merge method: use MCP's
   guarded merge or `gh pr merge <pr> --squash --match-head-commit <sha>` when squash
   is allowed. Choose an allowed strategy explicitly; the head guard does not select
   one ([CLI options](https://cli.github.com/manual/gh_pr_merge), checked 2026-10-18).
   Never use an admin bypass. If the head changes or merge is rejected, inspect
   the actual state before retrying; do not route around a policy rejection.
3. Fetch the PR again and verify merged state, target branch and merge commit.
   Confirm the linked issue closed. If GitHub left the issue resolved by this PR
   open, close it as part of finishing that task and verify its resulting state.
   A successful write response alone is not postcondition verification.
4. Preserve the primary checkout and evidence. For cleanup within the task, confirm
   destructive targets, use the matching local or managed-worktree lifecycle, and
   verify outcomes.

Report the pre-PR review's findings with their triage and fixing commits, follow-up
candidates, final head and CI separately, including that the final head's corrections
were verified locally and by current-head CI without a second review.
