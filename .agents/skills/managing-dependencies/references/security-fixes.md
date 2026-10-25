# The Security Fixes workflow

Read when a Security Fixes pull request or run needs attention, when setting the
workflow up, or before changing `.github/workflows/security-fixes.yml` or
`scripts/security_fixes.py` (`changing-gates`, `writing-repo-scripts`). `SKILL.md`'s
"Security fixes and the one-package exception" holds the policy; this file holds the
mechanics.

## One run

Daily at 04:23 UTC, on a manual dispatch, and as a dry run on a pull request that
changes the workflow or its script:

1. **`Plan security fixes`** (read-only: `contents`, `pull-requests`, and
   `vulnerability-alerts: read`) runs `scripts/security_fixes.py`. It stops at once
   while an earlier run's pull request (`automation/security-fixes/<run id>`) is open,
   so two runs never contend for a lockfile. Otherwise it reads the open alerts with
   `GITHUB_TOKEN`, drops expired exceptions, adds the ones a fix inside the window
   needs, and relocks:
   - `uv`: `uv lock --upgrade-package=<package>`; dropping an exception reruns
     `uv lock`, and every locked version must stay put.
   - pnpm: `pnpm update --recursive --lockfile-only --no-save <package>`, so ranges in
     `package.json` stay as they are; dropping an exception must leave
     `pnpm install --frozen-lockfile --lockfile-only` passing. Each entry is the exact
     `"<name>@<version>"`, which pnpm accepts since 10.19.0.

   Then every version the lock newly holds is looked up in the GitHub Advisory
   Database (`GET /advisories?ecosystem=<pip|npm>&affects=<name>@<version>`). A
   Dependabot alert only describes the versions locked before, so the newest release
   the window admits can carry an advisory no alert names yet: virtualenv 21.14.11,
   picked to close `< 21.14.9`, was itself inside GHSA-cx6f-vjhg-g3cc
   (`>= 21.14.9, < 21.14.13`), and Dependency Review refused the PR (observed
   2026-10-25). Such an advisory raises its package's target — with an exception if
   that version is inside the window — or adds the package, and the lock is redone, up
   to three rounds; one with no patched version fails that lockfile.

   The step summary shows the planned title, body, and diff, which the job hands on as
   an output. No dependency cache is used.
2. **`Open the pull request`** runs only on `main`, never for a pull request or a dry
   run. It runs no project code: it applies the diff, refusing one that touches any
   file but `pyproject.toml`, `uv.lock`, `pnpm-workspace.yaml`, or `pnpm-lock.yaml`,
   then commits as the App's bot, pushes, and opens the pull request with the App
   token. The commit runs no hooks; CI on the pull request runs every check. A pull
   request opened with `GITHUB_TOKEN` would start no workflow, so its required checks
   would never report ("events triggered by the `GITHUB_TOKEN` ... will not create a
   new workflow run", https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow,
   checked 2026-10-25). Reading alerts needs no App:
   `vulnerability-alerts: read` "permits an action to list Dependabot alerts"
   (https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax,
   checked 2026-10-25).

3. **`Result`** fails the run when planning recorded a failure or a job did not succeed,
   after any pull request is open. A failure in one lockfile leaves that lockfile as
   it was and still proposes the other's change, listed under "Failed in this run".

GitHub disables a public repository's scheduled workflows after 60 days without
repository activity ("scheduled workflows are automatically disabled when no
repository activity has occurred in 60 days",
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows,
checked 2026-10-25). Its pull requests count as activity only while they arrive; after
a quiet spell, check Actions → Security Fixes and enable it again.

## The owner's one-time setup

An agent never does these; they create credentials and change repository settings.

1. **Create a GitHub App** owned by the repository's owner (Settings → Developer
   settings → GitHub Apps → New GitHub App): any name and homepage URL, the webhook
   off, repository permissions **Contents: Read and write** and **Pull requests: Read
   and write** (Metadata stays read-only), no events, installable only on this
   account. Note its **Client ID**, then generate a **private key** (`.pem`).
2. **Install the App** on this repository only.
3. **Create the `security-fixes` environment** (Settings → Environments): deployment
   branches limited to `main`. Add the environment variable
   `SECURITY_FIXES_APP_CLIENT_ID` (the Client ID) and the environment secret
   `SECURITY_FIXES_APP_PRIVATE_KEY` (the whole `.pem`). Adding required reviewers there
   makes every run that opens a pull request wait for an approval.
4. **Keep Dependabot alerts on and Dependabot security updates off** (Settings → Code
   security). With security updates on, a fix older than the window can arrive twice;
   land one and close the other.

## A manual run

Actions → Security Fixes → Run workflow, from `main`, with **dry-run** ticked (the
default): the `Plan security fixes` step summary shows what would change, and nothing
is pushed. Untick it to open the pull request. From a terminal, the same with
`gh workflow run security-fixes.yml --ref main -f dry-run=true` (or `false`), then
`gh run watch`. A dispatch is a write to GitHub: the owner's, or an agent's only when
asked.

## Reading a red run

The plan step's stderr names the failure; the alert stays open until a person acts.

| Code | Means | Next |
|---|---|---|
| `ERR_FIXES_UNRESOLVED` | A locked version still matches an alert after relocking | A dependent's range holds the package back: an `overrides` entry or a parent upgrade, the owner's call |
| `ERR_FIXES_LOCK` | `uv lock` or `pnpm update` failed | Usually the fix needs another package younger than the window; read the quoted output |
| `ERR_FIXES_EXPIRY` | Dropping an expired exception would move the lock or fail an install | Compare the entry with the release's upload or publish time by hand |
| `ERR_FIXES_VERSION` | A version or range is not plain digits and dots | Fix that package by hand; the script does not guess an order |
| `ERR_FIXES_FILE` | The exception table or list is not in the shape the script edits | Restore the shape the comments above it describe |
| `ERR_FIXES_GH`, `ERR_FIXES_REGISTRY`, `ERR_FIXES_TOOL` | GitHub, PyPI, npm, or a tool was unreachable | Rerun; if it persists, check the permission the message names |

`Open the pull request` failing at the token step means the setup above is missing or
the App lost its installation.

An alert with no patched version, or on a manifest neither lockfile owns, is listed
under "note:" in the log and under "Alerts not handled here" in a pull request body.
