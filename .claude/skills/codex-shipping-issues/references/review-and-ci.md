# Review rounds, current-head CI and landing

## Record reviewed and current revisions separately

Record repository, issue, PR URL/number, each review round's ID and reviewed commit,
current head SHA, base SHA/ref, correction commits and check/run evidence. Record
local reviewers, scope, findings and dispositions too. Refresh head/base when
checking CI or landing. Never present a review as cloud review of a
commit it did not read. A changed diff invalidates old CI and local acceptance
evidence, but each completed review remains recorded for this PR.

The Codex integration reviews the PR when it opens and, depending on the change, may
review again after a correction push. The owner's policy handles at most **three
review rounds** per PR:

| Round | Fix in this PR | Accepted but not fixed here |
| --- | --- | --- |
| 1 (opening review) | every accepted finding, whatever its badge | — |
| 2 and 3 (reviews of correction heads) | accepted `P0`, `P1` and `P2` findings | accepted `P3`: a reported follow-up candidate |

After pushing round 3's corrections, do not wait for a fourth review; land on local
verification and current-head CI. Never request a review to fill a round. This does
not remove repository-required approvals, checks or unresolved correctness decisions.

## Wait for the opening review

Discover GitHub MCP actions and inspect review submissions, inline threads, the PR
conversation and review-task metadata. Follow pagination, another MCP action or
`gh api` when normalized responses omit data. Report required evidence that neither
MCP nor CLI can provide. Preserve the same review criteria on both paths.

Open a regular PR. Record the opening event and the automatic review's trusted
integration identity, state and reviewed commit. Wait through its queue/start delay
and running state. Do not post `@codex review`, `@codex fix`, change review settings,
or close/reopen the PR to start another run. If it fails, is unavailable or stalls,
record the missing cloud evidence and use the local fallback below. No additional
permission or manual review trigger is needed for this fallback.

| Review state | Action |
| --- | --- |
| Not started / queued | Observe for up to 300 seconds; then use the local fallback. |
| Running | Observe in bounded waits; after 15 minutes without observable progress, use the local fallback. |
| Completed, findings | Read all findings and address accepted in-scope ones. |
| Completed, no findings | Record terminal state and the reviewed commit. |
| Failed / unavailable | Record the failure and use the local fallback. |

Completion must be terminal and come from the trusted Codex integration, associated
with this PR and its reviewed commit. A display name, acknowledgement, reaction,
green CI or silence alone is insufficient. A trusted terminal summary with matching
commit metadata, a no-findings signal and empty findings/threads can establish a
clean review. Completion alone does not mean there were no findings.

## Local fallback for an integration failure

The owner authorizes local review when the cloud integration fails, cannot be used,
or reaches the observation limits above. Record the trigger, timestamps, trusted
integration state and affected SHA. Silence or elapsed time establishes only the
fallback trigger, never a clean cloud review. Do not retry manual triggers, change
settings, reopen the PR or create an empty commit to obtain a review.

1. Review the complete current diff against the latest issue acceptance and base,
   including tests, errors, resource ownership, security and documentation. This is
   a deliberate review pass, separate from implementation and routine self-checks.
2. When the host supports it, obtain an independent read-only sub-agent review of
   that diff with the acceptance criteria and exact head/base. AGENTS.md authorizes
   this delegation. The reviewer must not edit, mutate Git or write to GitHub.
   If unavailable, state that limit and perform the full local pass yourself.
3. Record each reviewer's identity, reviewed SHA/base, scope and concrete findings,
   including an explicit no-actionable-findings result when applicable. Classify
   findings and fix the ones the round requires using the same criteria below.
   Re-review correction diffs and repeat affected checks; changed source requires
   fresh verification and CI on the resulting head. Share findings already observed
   from the cloud run too; the fallback cannot discard them.
4. Refresh live findings before landing. Required unresolved correctness findings,
   owner decisions, server-required approvals and checks still block merge. A local
   pass plus current-head CI satisfies this workflow's review gate; never call it a
   completed cloud review. A late cloud run need not delay a completed fallback,
   but any findings already posted must be triaged before merging.

Use at most three finding-bearing or clean review rounds across cloud and local
passes; a failed attempt with no published findings supplies no review result.
Correction re-review remains required without inventing another cloud round.

Classify each finding as accepted, rejected or out of scope with a reason judged
against the code, not the badge. Fix what the round's row above allows, inspect the
complete correction diff, run affected checks and `just verify`, commit with normal
hooks and push. Record which commits address which findings in which round. An
unresolved owner decision or correctness finding blocks landing; CI success cannot
dismiss it. Follow `AGENTS.md`'s "Task scope and confirmations" for comments and
thread changes. Report accepted `P3` findings from rounds 2–3 and out-of-scope
findings as follow-up candidates; use `triaging-issues` when the requested workflow
includes filing follow-ups.

## Wait briefly for the next round

After each correction push in rounds 1 and 2, observe the PR for up to **300 seconds**
for a trusted review that starts on the new head (observed: 12 seconds to about 2.5
minutes after the push, and some pushes start none). If one starts, wait for it to complete and handle it as the
next round. If none starts within that grace, the latest completed review stands:
land on local verification and current-head CI. Observe this alongside CI; CI takes about
3 minutes, so the grace adds at most about 2 minutes.

If a review appears after round 3's corrections, do not wait for its completion and
do not start a fourth correction round. Triage any `P0` or `P1` finding it has
already posted: an accepted one blocks landing and is reported for the owner.

## Verify CI on the current head

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
Diagnose failures while a review is pending. Any correction or changed
base integration requires fresh local acceptance and CI for the resulting head.
For an in-scope retry, record the reason and actual head/run and request confirmation
if the operation requires it. Never change settings or dispatch unrelated workflows
merely to obtain missing evidence.

Use bounded observations (at most 60 seconds per blocking wait) and back off when
state is unchanged. Continue in-scope repairs without an arbitrary attempt cap.
Pending checks or elapsed time alone do not complete a run. Use the documented
local fallback for a failed, unavailable or stalled review. Honor user
deadlines and host limits. Once the latest review round is complete, the findings it
requires are addressed, the next-round grace has passed without a new review (or the
round cap is reached), and current-head gates pass, no further review wait is required.

## Land within the requested outcome

At a PR-only boundary, preserve the open PR. When the requested outcome includes merge:

1. Refresh head/base, mergeability, known findings, required approvals and all
   expected checks. Confirm every qualifying review round completed through cloud
   review or the documented local fallback, required findings have correction
   evidence, and local acceptance/CI cover the current diff. Without a completed
   fallback, wait for a started cloud review within the round cap. Integrate
   the current default branch normally if needed, repeat local checks and CI, and
   inspect the resulting diff. Do not request another review or force-push.
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

Report each review round's reviewed commit and addressed findings, follow-up
candidates, final head and CI separately, including whether the final head's
corrections were locally verified without a further cloud review.
