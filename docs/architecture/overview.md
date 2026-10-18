# Intent to English architecture

How the app is built and why, as it stands. What the app does is in `AGENTS.md`'s Product
section and `docs/product/requirements.md` (cited as §n); the screens and the stage table
are `docs/product/ux-flows.md`'s; app-wide UX rules are `docs/design/ux-guidelines.md`'s;
what each model role writes is `docs/product/conversation-rules.md`'s. `backend/AGENTS.md`'s
"Architecture" section holds the layer rules every backend task needs and points here. A
design change rewrites the sentences it changes here, in the same pull request
(`AGENTS.md`'s "Before changing the architecture").

## Principles

- **The server owns the flow.** A session's stage lives in the database, and only a core
  service moves it, from the stage and the action the learner took (P8, §3.7). A model writes
  the content of a stage and never chooses the next one; the screen renders the stage it is
  given. Rules out: a model routing the conversation or classifying input, and stage logic in
  the browser.
- **Checked before stored or shown.** Every model output passes its code checks before it
  becomes a timeline entry or reaches the screen; a failed check gets one repair call, then
  the failure state (§3.10, §3.11). Rules out: streaming, and storing raw model text.
- **The Partner's context is built, not instructed.** The Partner port's request types hold
  only the English conversation, so the Japanese intent, hints, feedback, and questions to
  the Coach cannot reach it (P7). Rules out: one shared model context with an instruction to
  ignore part of it.
- **The core knows no provider.** The two model roles are ports typed with core values;
  prompts, PydanticAI, and provider quirks live in one adapter package, so Amazon Bedrock is
  an adapter change and a setting (§3.10). Rules out: provider types or prompt text in
  `core/`.
- **No live model call outside the owner's own runs.** Tests, the browser test, and CI run
  the fixed-response adapter or scripted fakes; only the owner's practice and a human-run
  evaluation bill (Non-goals). Rules out: live, recorded, or skipped-when-keyless tests.
- **The learner's words survive.** A submission is stored before its model call, so a
  failure, a cancel, a stale tab, or a server stop never loses the text (ux-guidelines §
  Principles, §4). Rules out: holding a pending input only in memory or only in the browser.

## Shape

The template's layers (`backend/AGENTS.md`'s "Architecture") are kept; the app fills them
like this:

| Domain | Layer | Module (under `backend/src/intent_to_english/`) | Holds |
|---|---|---|---|
| Session, stage, timeline, submission, model-call record | core | `core/models.py` | frozen dataclasses and enums; no I/O |
| The stage machine | core | `core/flow.py` | the stages, the actions, which action each stage allows, and the next stage |
| Partner and Coach request and output values | core | `core/partner.py`, `core/coaching.py` | the port's value types and the output checks for each task |
| Shared text helpers | core | `core/text.py` | sentence splitting, question counting, Latin and Japanese script detection |
| Ports | core | `core/ports.py` | `SessionRepository`, `PartnerModel`, `CoachModel`, `Clock`, `IdFactory` |
| Use cases | core | `core/services.py` | `ConversationService`: start, list, get, act, cancel |
| Domain errors | core | `core/errors.py` | the `AppError` subclasses in § Decisions › The API |
| Storage | adapters | `adapters/sql/`, `adapters/memory.py` | the four tables below; the in-memory repository for tests and a run without a database URL |
| Model roles | adapters | `adapters/models/` | `fixed.py` (the fixed-response mode), `openrouter.py` (PydanticAI agents on OpenRouter), `prompts.py` (the messages each task sends), `schemas.py` (the Pydantic models each task's JSON schema comes from) |
| HTTP | api | `api/routers/sessions.py`, `api/routers/meta.py`, `api/schemas.py` | the routes in § Decisions › The API |
| Evaluation | its own package | `evaluation/` | the harness that runs `backend/evals/cases/` and writes `backend/evals/reports/` |
| Wiring | root | `settings.py`, `composition.py` | the settings in § Decisions › Keys, models, and the mode; the adapter choice |

The screen lives under `frontend/src/`: `routes/index.tsx` (S1), `routes/sessions.$sessionId.tsx`
(S2 and S3), a not-found route (S4), `features/sessions/` (the list), `features/conversation/`
(both panes, the composer, the controls, the feedback card), and the tokens in `styles.css`.

What crosses each boundary: the API hands the core an action and the version the screen
showed, and gets a `SessionView` back; the core hands a model port a request value and gets
an output value with its call's usage, or a model error; the repository stores and returns
core values only.

## Data

SQLite through SQLAlchemy Core and Alembic, as the template ships it (`persisting-data`).
Ids are UUIDv7 from `IdFactory`; times are UTC.

| Table | Columns | Rules |
|---|---|---|
| `sessions` | `id`, `started_at`, `ended_at`, `status` (`in_progress` / `ended`), `stage`, `turn_index`, `turn_state` (JSON), `version`, `finished_replies`, `opener`, `wrap_up` (JSON) | one row per session; `version` goes up by one with every accepted action |
| `timeline_entries` | `id`, `session_id`, `seq`, `turn_index`, `kind`, `payload` (JSON), `created_at` | append-only: never updated or deleted; `(session_id, seq)` unique |
| `submissions` | `id`, `session_id`, `base_version`, `action`, `input` (JSON), `status` (`pending` / `completed` / `failed` / `cancelled`), `failure_code`, `boot_id`, `created_at`, `finished_at` | one row per action the learner sent; a partial unique index on `(session_id, base_version)` where `status` is `pending` or `completed` |
| `model_calls` | `id`, `session_id`, `submission_id`, `turn_index`, `role`, `task`, `attempt` (1, or 2 for the repair), `provider`, `model`, `input_tokens`, `output_tokens`, `cost`, `latency_ms`, `outcome`, `violations` (JSON), `created_at` | one row per request to a model; never the key or the prompt text |

- `turn_state` holds only what the current stage's next action needs: the intent in force,
  the latest English, the feedback in force, retry submissions so far, the two readings at a
  reading check, and the shown answer. Everything else is read from the timeline.
- `outcome` is `ok`, `invalid_output` (failed its checks or did not parse), `repaired` (a
  repair that passed), `timeout`, `rate_limited`, or `provider_error` (§3.12). `cost` is what
  the provider reported, null when it reported none.
- A payload change keeps old rows readable: a new field has a default; anything else ships
  an Alembic data migration in the same pull request.

Timeline entry kinds, each a core value stored as its `payload`:

| Kind | Written by | Payload |
|---|---|---|
| `partner_line` | Partner | the line, whether it asks a question, and `opener`, `reply`, or `restatement` (shorter or simpler) |
| `intent` | learner | the Japanese, and whether it replaces an earlier one |
| `acknowledgment` | Coach | the one line, and the build hint or none |
| `english` | learner | the English, and whether it was sent directly |
| `hint_request` / `gap_hint` | learner / Coach | the named gap and the partial English / the hint |
| `reading_question` / `reading_choice` | Coach / learner | the word and its two readings / the chosen one |
| `feedback` | Coach | the intent line, the fixes (number, 元, 直す, なぜ, tag), the sentence, the template, the request line, and the readings noted |
| `retry` / `retry_result` | learner / Coach | the filled sentence and its attempt number / accepted, or the blanks still off with a bigger hint, or the piece given |
| `answer` / `typed_copy` | Coach / learner | the complete example / the copy typed once |
| `skip` | learner | none; the screen shows the fixed neutral line |
| `turn_done` | service | the turn's final English and how the turn ended (accepted, skipped, answer typed, no fix needed, piece given) |
| `question` / `coach_answer` | learner / Coach | the question / the answer |
| `check_in` / `check_in_answer` | service / learner | none / continue or end |
| `practice` / `practice_result` | learner / Coach | for the finished turn named by `turn_index` |

## Core flows

### The stage machine

| Stage | Means |
|---|---|
| `opening` | the session exists; the Partner's opener is due |
| `intent` | the latest Partner line awaits the learner's Japanese, or English sent directly |
| `english` | the intent is acknowledged; the learner's English (whole or partial) is due |
| `reading_check` | a slip with two readings changes the feedback; the learner picks one |
| `retry` | feedback with blanks is shown; the whole filled sentence is due |
| `answer_shown` | one complete example is shown; the learner types it once or skips |
| `partner_turn` | the learner's turn is done; the Partner's next line is due |
| `check_in` | the 3rd, 6th, 9th… reply is done: continue or end |
| `ended` | read-only |

| Action | Allowed at | Input (limits per ux-guidelines § Forms) | Model task | Next stage |
|---|---|---|---|---|
| `open` | `opening` | — | Partner `open` | `intent` |
| `intent` | `intent` | Japanese, 1–1,000 | Coach `acknowledge` | `english` |
| `english_direct` | `intent` | English, 1–1,000 | Coach `feedback`, without an intent | `retry`, `reading_check`, or done |
| `english` | `english` | English, 1–1,000 | Coach `feedback` | `retry`, `reading_check`, or done |
| `hint` | `english` | the gap, 1–200; partial English, 0–1,000 | Coach `gap_hint` | `english` |
| `reading` | `reading_check` | one of the two readings | Coach `feedback`, with that reading | `retry` or done |
| `retry` | `retry` | the filled sentence, 1–1,000 | Coach `check_retry` | done, or `retry` when a blank is still off on the first submission |
| `show_answer` | `english`, `retry` | — | Coach `show_answer` | `answer_shown` |
| `typed_copy` | `answer_shown` | the copy, 1–1,000 | none | done |
| `skip` | `retry`, `answer_shown` | — | none | done |
| `partner_reply` | `partner_turn`, `check_in` | — | Partner `reply` | `intent` of the next turn |
| `restate` | `intent` through `answer_shown` | `shorter` or `simpler` | Partner `restate` | unchanged |
| `rewrite_intent` | `english`, `reading_check`, `retry`, `answer_shown` | Japanese, 1–1,000 | Coach `acknowledge` | `english` |
| `practice_again` | `check_in`, and `intent` before the learner's first reply of the turn | the filled sentence of the finished turn, 1–1,000 | Coach `check_retry` against that turn's feedback | unchanged |
| `ask` | every stage but `ended` | the question, 1–500 | Coach `answer_question` | unchanged |
| `end` | every stage but `ended` | — | Coach `wrap_up`; none when no feedback exists yet | `ended` |

"Done" means the turn ends: the service appends `turn_done`, adds one to
`finished_replies`, and moves to `check_in` when the count is a multiple of three, else to
`partner_turn`. The turn's final English is the learner's latest English of the turn (the
accepted or last retry, the typed copy, or the English itself), with every reading the
Coach noted applied, so the Partner hears what the learner meant; when the learner skips
after a shown answer without having written any English, it is the shown example. A
second retry that still misses gets the piece and ends the turn (§3.5). A shown answer's
typed copy is not checked and does not count as a retry. `practice_again` takes one
submission and shows its result; it never changes the stage or the conversation. When a
session ends before any feedback exists, no Coach call runs and the wrap-up is empty.

At `partner_turn` the screen sends `partner_reply` by itself, so the Partner's line follows
the Coach's last block without a click; at `check_in`, `partner_reply` is 「続ける」 and `end`
is 「終わる」.

### One action, end to end

1. The screen sends `POST /api/sessions/{id}/actions` with the action, its input, and the
   session `version` it shows.
2. One transaction checks the version (`stale_session` otherwise), that no submission is
   pending (`action_in_progress`), that the session is not ended (`session_ended`), and that
   the stage allows the action (`action_not_allowed`), then stores the submission as
   `pending` with the process's boot id.
3. Outside any transaction the service builds the task's request from the session — for the
   Partner, only the English lines — and calls the port within 60 s. A failed check, or an
   output that does not parse, gets one repair call carrying the violations. Every call is
   recorded in `model_calls`.
4. A second transaction re-reads the submission. If it is still `pending`, the service
   appends the timeline entries, updates the stage, `turn_state`, and `version`, and marks it
   `completed`, then returns the new `SessionView`. If the learner cancelled meanwhile, it
   discards the output (the call stays recorded) and answers 409 `action_cancelled`, which no
   screen is waiting for.
5. A model failure marks the submission `failed` with its code and answers 502, 503, or 504;
   the stage and version stay as they were, and the view offers the text again for
   「もう一度」. Any other exception also marks the submission `failed` before it propagates,
   so a bug never leaves a session stuck.

`POST /api/sessions/{id}/cancel` marks the pending submission `cancelled`; the screen then
shows the stage as before with the text back in the composer.

### Interrupted calls

Each process start makes a boot id. A `pending` submission carrying another boot id belongs
to a process that stopped, so reading the session reports it as interrupted: the stage is as
before and the text is offered again (ux-flows F-5). A `pending` submission older than its
call budget (two calls of 60 s, plus a margin) is reported the same way. A closed tab does not
interrupt anything: the server finishes the call and stores the result, which the reopened
screen shows.

### The session view

`GET /api/sessions/{id}` and every accepted action return one `SessionView`: status, stage,
version, turn index, finished replies, the actions the stage allows, every timeline entry in
order, the last submission when it is pending, failed, or interrupted (its action, input,
and failure code), and the wrap-up. The screen derives both panes and the next-action line
(ux-flows § Stage table) from it, and decides no stage itself.

## Quality targets

| Target | Proved by |
|---|---|
| Every model output passes its checks before it is stored or shown | core tests per check, from conversation-rules' list of checkable rules; a service test where a fake returns an invalid output, then a valid one, and one where both fail (502 `model_output_invalid`) |
| The Partner never receives the intent, hints, feedback, or questions | a test that builds every Partner request from a session full of marked Japanese and Coach text and finds none of the markers in it or in the prompt `prompts.py` renders |
| No live model call in tests or CI | PydanticAI's `ALLOW_MODEL_REQUESTS` set false for the backend suite; the settings isolation fixture removes `OPENROUTER_API_KEY`; the browser test runs with the mode forced to fixed; a composition test pins the fixed adapter without a key |
| An action is processed at most once, and a stale one is rejected | repository contract tests (concurrent inserts against the partial unique index) and service tests (double send, stale version, cancel during a call, a pending submission from another boot) |
| The whole conversation works in the browser | `just e2e` drives F-1, F-2 (a turn with a fix and its retry), F-3, and F-5 in the fixed-response mode |
| Waiting states follow ux-guidelines (300 ms, 10 s, 60 s) | component tests with fake timers |
| Accessibility targets hold (WCAG 2.2 AA + 2.4.13) | component tests for focus after a stage change and the live regions; ux-guidelines' manual verification list |
| Cost, latency, and pass rates are known per model | the evaluation report |

## Decisions

### Models are called through PydanticAI, inside the model adapters

The app depends on `pydantic-ai-slim` with its `openrouter` extra, imported only under
`adapters/models/`: the core's import test and ruff's banned-api rule keep `pydantic_ai` and
`openai` out of `core/`, and review keeps them out of `api/` and the storage adapters. PydanticAI supplies the OpenRouter model and provider, typed structured output,
and test models, and Bedrock later is its Bedrock model with the `bedrock` extra (boto3)
behind the same ports. The app turns off what would hide calls from the core:

- **No automatic retries.** PydanticAI's output retries are 0, and the provider gets an
  `openai.AsyncOpenAI` client with `max_retries=0` (the SDK's default is 2): one request is
  one recorded, billed call, and the 60 s budget per call holds.
- **JSON schema output.** Every task's `output_type` is wrapped in `NativeOutput`, which
  sends a JSON schema `response_format`. PydanticAI's default is a forced tool call, which
  Claude Sonnet 5.5 rejects.
- **Usage per request.** Tokens come from each `ModelResponse.usage`; the provider-reported
  cost from `ModelResponse.provider_details["cost"]`.

Rejected: calling OpenRouter with httpx2 directly — no new package and full control, but the
request, the schema, parsing, retries, and error mapping would all be hand-written, and Bedrock
would be a second adapter written from scratch.

Sources, checked 2026-10-17: https://pypi.org/pypi/pydantic-ai-slim/json (2.57.0 released
2026-10-16, Python ≥3.11, MIT; extras `openrouter` = `openai>=3.26.0`, `bedrock` = `boto3`);
https://github.com/pydantic/pydantic-ai/tree/v2.57.0 (`providers/openrouter.py`: the base URL
`https://openrouter.ai/api/v1` and `openai_client=`; `models/openrouter.py`: OpenRouter's cost
copied into `provider_details`; `profiles/__init__.py`: the default output mode is a tool
call); https://github.com/pydantic/pydantic-ai/blob/main/docs/version-policy.md (no
intentional breaking change in a minor release; the next major at least three months after
2.0.0 of 2026-06-23); https://github.com/openai/openai-python/blob/main/src/openai/_constants.py
(`DEFAULT_MAX_RETRIES = 2`). Claude Sonnet 5.5 returns 400 on a forced `tool_choice`:
https://platform.claude.com/docs/en/about-claude/models/migration-guide (Migrating to Claude
Sonnet 5.5; Anthropic's reference as cached on 2026-10-06). The lock gains about ten packages
(openai, griffelib, opentelemetry-api, genai-prices, pydantic-graph, logfire-api, jiter,
sniffio, and their dependencies), all under MIT, Apache-2.0, BSD-3-Clause, or ISC, with pure
or cp314 wheels (PyPI, checked 2026-10-17).

### Two role ports, shaped by their tasks

`core/ports.py` declares `PartnerModel` (`open`, `reply`, `restate`) and `CoachModel`
(`acknowledge`, `gap_hint`, `feedback`, `check_retry`, `show_answer`, `answer_question`,
`wrap_up`). Each method takes one frozen request dataclass holding what that task needs and
nothing more, plus an optional repair (the previous output's violations), and returns the
output value with its call's usage, or raises a model error. An output that does not parse
comes back as a parse failure with its usage, which the service treats like a failed check. `PartnerModel`'s requests hold
the English lines of the conversation, the previous session's opener, the line to restate,
and whether the taking-turns rule says share — nothing a type could smuggle the intent in.
The `feedback` task returns either feedback or a reading question.

Output types are core dataclasses without schema concerns. The adapter declares one Pydantic
model per output in `schemas.py` for the JSON schema and converts what parses into the core
value; the fixed-response adapter returns core values directly. Rejected: one generic
completion port with prompts built in the core, which would put prompt text and provider
message shapes in `core/`.

### Checks and the one repair live in the core

Each task's checks are pure functions in `core/partner.py` and `core/coaching.py` returning
the violations of an output against its request, implementing conversation-rules' checkable
rules (§3.11). The service runs them on every output, from any adapter, and owns the single
repair, so the fixed-response mode, the evaluation, and live practice behave alike and every
attempt is a row in `model_calls`.

### One action, one model task

An action runs at most one model task, plus its repair, so no request waits on two 60 s
budgets and each failure names one pane. The Partner's line after a finished turn is its own
action (`partner_reply`), which the screen sends at `partner_turn` without a click.

### The session is one row and an append-only timeline

The `sessions` row holds the stage, the current turn's working state, and the version; the
timeline holds every entry as JSON in order; `submissions` holds what the learner sent and
what became of it; `model_calls` holds the log (§ Data). The transcript (S3), the left pane,
and the Partner's context are reads of the timeline. JSON payloads are SQLAlchemy `JSON`
columns, which the template's PostgreSQL contract suite also covers. Rejected: normalized
tables (about ten, and a migration for every new element of a turn) and event sourcing
(folding every event on every read, and versioning the events).

### Stale, repeated, cancelled, and interrupted actions

Every action names the version it answers, so a second tab or a reloaded screen gets 409
`stale_session` and reloads the session (§4). The partial unique index on `submissions`
admits one pending or completed submission per version, so a double click is 409
`action_in_progress` and is processed once. A cancel discards the output that arrives after it;
the boot id marks what a stopped process left pending (§ Core flows).

### Keys, models, and the mode

| Setting | Default | Effect |
|---|---|---|
| `OPENROUTER_API_KEY` | unset | the OpenRouter key, unprefixed (the name OpenRouter documents), read through a validation alias as a secret; unset or blank runs the fixed-response mode |
| `INTENT_TO_ENGLISH_MODEL_MODE` | `auto` | `auto` uses OpenRouter when a key is set; `fixed` forces the fixed-response mode, so the browser test never bills even where a key is exported |
| `INTENT_TO_ENGLISH_COACH_MODEL` | `anthropic/claude-sonnet-5.5` | the Coach's OpenRouter model id |
| `INTENT_TO_ENGLISH_PARTNER_MODEL` | `anthropic/claude-haiku-5.5` | the Partner's OpenRouter model id |

The adapter builds the `openai.AsyncOpenAI` client with the key, OpenRouter's base URL, the
app's attribution header, and `max_retries=0`, and hands it to the provider, so no environment
value reaches a request (`calling-models`' adapter reference). OpenRouter's catalogue is the authority on model ids, so a model id is
only checked to be non-empty. Both default ids are listed in
https://openrouter.ai/api/v1/models (checked 2026-10-17): Sonnet 5.5 at $2 / $10 and Haiku 5.5
at $0.10 / $0.50 per million input / output tokens, Haiku 5.5 at $0.50 / $2.50 above 100,000
prompt tokens; both list `response_format` and `structured_outputs` among their supported
parameters. The fixed-response mode is in `adapters/models/fixed.py`: its outputs are
deterministic functions of the request, pass every check, reach every stage (a reading check
and a blank still off included), and report provider `fixed` with no tokens or cost.

### The API

| Route | Result |
|---|---|
| `POST /api/sessions` | 201 with the new session at `opening` |
| `GET /api/sessions?cursor=&limit=` | one page, newest first, 20 by default: id, start time, status, finished replies, opener |
| `GET /api/sessions/{id}` | the `SessionView` |
| `POST /api/sessions/{id}/actions` | the new `SessionView`; the body is one of the actions above, told apart by `action`, with `version` |
| `POST /api/sessions/{id}/cancel` | 204; the pending submission is cancelled |
| `GET /api/meta` | `{"model_mode": "fixed" \| "openrouter"}`, for the header badge on every screen |

| Error | Status | Code |
|---|---|---|
| unknown session | 404 | `session_not_found` |
| the version moved on | 409 | `stale_session` |
| a submission is pending | 409 | `action_in_progress` |
| the stage does not allow the action | 409 | `action_not_allowed` |
| the session has ended | 409 | `session_ended` |
| the output arrived after a cancel | 409 | `action_cancelled` |
| an input outside its limits | 422 | `invalid_input` |
| the call passed 60 s | 504 | `model_timeout` |
| the provider is rate limiting | 503 | `model_rate_limited` |
| the provider failed or is unreachable | 502 | `model_unavailable` |
| the output failed its checks after the repair | 502 | `model_output_invalid` |

The screen chooses its banner text from the code (ux-guidelines § States). The template's
Problem Details shape, request-id middleware, and `AppError` mapping in `api/app.py` stay.

### Evaluation lives in the repository

Cases are TOML files under `backend/evals/cases/`, one case each, read with the standard
library's `tomllib`: the task, its request, and expectations from a closed set the harness
implements ("flags *refreshing* as ミス", "marks nothing as ミス", "the Partner line does not
mention Sapporo"), so code decides pass or fail (§3.11). The harness (`evaluation/`) runs each
case through the configured adapters and the core checks, and writes a Markdown and a JSON
report to `backend/evals/reports/`, named by date and the two model ids: pass rate per check
and per expectation, for the first attempt and after the repair, cost and latency per task, the models, the date, and the commit. Every
report is committed, and the README's evaluation section shows the latest run's summary table
with a link. The owner runs it with a human-run recipe, since it bills; a backend test runs
the harness over every case in the fixed-response mode, which proves the cases parse and a
report renders without judging quality. Rejected: reports kept local with a hand-written
README summary, and one report overwritten on each run.

### Japanese in the repository

The repository's English-only rule has one exception, worded in `AGENTS.md`: the Japanese the
product speaks — UI copy, prompts, fixed responses and test data, and the quoted copy and
learner inputs in the conversation rules and evaluation cases. Code, identifiers, comments,
commits, pull requests, and document prose stay English.

### What the app keeps from the template

SQLite stays the default store with the PostgreSQL contract suite and its CI job, so a hosted
deployment later starts from portable SQL; the in-memory repository stays as the core tests'
fake and the store of a run without a database URL; the composition root, the `AppError`
mapping, the health route, and the middleware stay. The to-do sample goes in an implementing
issue (`starting-an-app`'s "Remove the sample to-do domain").

## Design lock

Binding for every screen; `docs/design/design-direction.md` is the research record and the
source of every value named here.

- **Direction:** friendly-professional learning UI after Brilliant — white canvas, role tints,
  bold type, tactile controls. Never cool monochrome, never an engineer's tool, never childish.
- **Preserve:** the white canvas (no cream or gray page); role-tinted surfaces with a 1 px
  border in the same hue; bold near-black headings and labels; tactile buttons with a 3 px
  bottom edge that collapses when pressed; a 12 px radius on bubbles, panels, buttons, and
  inputs.
- **Role colors:** lime is the Partner only (bubble, avatar, label); pale yellow is the
  Coach's feedback card and the marker on the parts to rebuild only; green is success only;
  the ミス and 改善 tags keep their own hues and appear nowhere else; ink is primary actions
  and text; blue is the focus ring and links only.
- **Reject:** gamification (streaks, XP, confetti), big pastel color blocks, indigo or violet,
  drop shadows as separators, cards around every block (only the feedback card and the
  bubbles are containers), serif type, illustrations or mascots beyond the Partner's SVG
  avatar, an icon package (a handful of inline SVGs at 20 px, 1.75 px stroke).
- **Type:** system fonts only — `--font-sans` for Japanese, `--font-en` (`ui-rounded` first)
  on every `lang="en"` element; the scale 12 · 13 · 15 · 16 · 17 · 20 · 24 px, body in `rem`.
- **Shape:** Tailwind's 4 px spacing scale; 1 px borders; no elevation except the composer's
  hairline; radius 12 px, 999 px for tags and the badge, 8 px for template slots.
- **Motion:** 150 ms fade with a 4 px rise for a new line or block, 200 ms expand and
  collapse, 100 ms between tabs, 100 ms button press, 600 ms success edge; `transform` and
  `opacity` only; reduced motion drops the rise and makes expand, collapse, and scrolling
  instant. The values are Tailwind duration utilities, not tokens.
- **Tokens:** design-direction's "Tokens (Tailwind CSS 4)" block, in `frontend/src/styles.css`
  after `@import "tailwindcss";`, with `color-scheme: light dark` and `light-dark()` pairs;
  markup uses the semantic utilities only, never a raw palette color.
- **Contrast:** the 49 light and dark pairs in `docs/design/contrast-pairs.json` pass WCAG 2.2
  AA (measured 2026-10-17); a token change re-measures them in the same pull request.

## Open

- Tailwind 4 opacity modifiers on `light-dark()` tokens — the token issue checks it once;
  until then no markup uses an opacity modifier on them (design-direction).
- The unit of OpenRouter's reported cost: its usage accounting page says "credits"
  (https://openrouter.ai/docs/use-cases/usage-accounting, checked 2026-10-17); that a credit
  is one US dollar is unchecked. The report labels the column with the provider's unit until
  it is checked.
- The reasoning effort per role through OpenRouter: both default models think by default, which
  costs output tokens and latency. The evaluation run settles whether either role sets a lower
  effort.
- The tag of a missing nuance that is not a core point — ミス or 改善 (conversation-rules
  §5.3). The owner decides; until then evaluation cases assert no tag for it.
- The Bedrock adapter's output mode: Claude Sonnet 5.5 rejects a forced tool call there too, so
  the adapter must use the JSON schema mode Bedrock's model supports — checked when the
  account's Bedrock quota allows (§2 Later).

## Follow-ups

Code work these decisions imply; each becomes an issue (`planning-tickets`).

- Remove the to-do sample, keeping what `starting-an-app` keeps.
- The design tokens in `styles.css`, and the Tailwind opacity check.
- The core: models, the stage machine, the output checks, the ports, the errors, and the
  service with its repair and submission rules, over the in-memory repository.
- The SQL tables, the migration, and the repository with its contract tests.
- The fixed-response adapter and the composition and settings for the mode.
- The API routes, the contract, and the generated client.
- The screens: S1, S2 below and above 1024 px, S3, S4, the header badge, the waiting states.
- The browser test over F-1, F-2, F-3, and F-5 in the fixed-response mode.
- The PydanticAI dependency, the OpenRouter adapter, its prompts, and its tests.
- The model call log's summary command.
- The evaluation harness, 10–20 cases from conversation-rules' examples and requirements
  §3.11's edge cases, the human-run recipe, and the README's evaluation section.
