# Roadmap

This page records the project's direction: the outcomes it is working toward now, the
ones that come next, and the ones only intended for later. It sits between two other
homes and repeats neither:

- `AGENTS.md`'s "Product" says what the project is, for whom, and its non-goals.
  Nothing here contradicts a non-goal; moving one is the owner's call, made
  in that section first.
- The issue tracker holds the units of work, their priority tiers, and their `blocked:`
  and `on hold` labels (`triaging-issues`). This page links issues by number and never
  copies their bodies.

It records direction and authorizes nothing. An issue is implemented because it is
filed, tiered, and picked, never because a line here names it. It is not a design document
either: a design a line depends on is described in its present state in `AGENTS.md`,
`docs/architecture/overview.md`, `backend/AGENTS.md`'s "Architecture" section, or the
skill that owns it, and linked from here. Merged pull requests and closed
issues record what has shipped; `git log` shows the local history.

The owner decides what the page says; an agent proposes a change to it in a pull
request, and the change lands only once the owner has approved it.

- **Last reviewed:** 2026-10-17, when the first issues were filed

## Now

The outcomes being worked on, one to three of them. Each has its issues filed.

- **The whole conversation runs in the browser on fixed responses** — the core
  interaction is the product, so it must work end to end before any model bills.
  Issues: #9 and its sub-issues. Done when: `just e2e` drives a session through start, a turn with a
  fix and its retry, the check-in, the end, and a resume after reload (ux-flows F-1,
  F-2, F-3, F-5) with `INTENT_TO_ENGLISH_MODEL_MODE=fixed`.
- **Practice runs on real models, every output checked before it is shown** — the turn
  only teaches when the Coach's feedback is real. Issues: #10 and its sub-issues. Done when: with
  `ANTHROPIC_API_KEY` set, the owner finishes one session in the browser, and every
  call of it has a `model_calls` row with its tokens, cost, latency, and outcome.
- **The evaluation set runs against the configured models and its report is
  committed** — the quality evidence the portfolio needs, and what decides whether the
  Coach can move to Haiku. Issues: #11 and its sub-issues. Done when: the human-run evaluation recipe
  writes a report for 10–20 cases under `backend/evals/reports/`, and the README's
  evaluation section shows its summary.

## Next

The outcomes that follow once Now's are done. An issue may already exist for one, often
parked as `on hold`; none is required.

- **The OWASP Top 10 for LLM Applications attack tests** — Prompt Injection and the
  other relevant risks as evaluation cases, with a threat model and the results in the
  README; the first item after the MVP. Before it moves up: Now's evaluation outcome
  lands, since the attacks run on the same harness.
- **Moving from the Anthropic API to Amazon Bedrock** — the provider the app moves to
  before it is hosted, as one new provider module beside `anthropic_provider.py` and the
  selection in `composition.py`. Before it moves up: the account's Bedrock quota allows
  calls (re-application around 2026-11-02), and the module's output mode is checked against
  Claude Sonnet 5.5 (`docs/architecture/overview.md` § Open).

## Later

Direction the project intends to take but has not ordered. No issue is filed for a line
here, apart from a parked one that a line names.

- **Hosting with sign-in, so the app works from a phone** — waits for Bedrock; brings
  authentication, a protected billed endpoint, and abuse limits into scope.
- **Reading the Partner's line aloud** — undecided since the prototype.
- **Review of what the learner could not say** — expressions from feedback turned into
  later questions or spaced review.
- **A Partner who remembers past sessions** — retrieval over saved sessions.
- **Adjustable support and lengths** — fewer or more hints, a longer or shorter Partner,
  narrowing the intent by picking which points to keep.
- **Streaming replies** — only with a way to take back a line that fails its checks.
- **A model grading outputs in the evaluation** — once its agreement with the owner's own
  judgments is measured.
- **Turning a saved turn into an evaluation case.**
- **Deleting a session from the screen.**
