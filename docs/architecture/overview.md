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
| Session, stage, timeline, submission, model-call record | core | `core/models.py` | frozen dataclasses and enums, including `Stage` and `Action`; no I/O |
| The stage machine | core | `core/flow.py` | the rules for which action each stage allows, input limits, and the next stage |
| Partner and Coach request and output values | core | `core/partner.py`, `core/coaching.py` | the port's value types and the output checks for each task |
| Shared text helpers | core | `core/text.py` | sentence splitting, question counting, Latin and Japanese script detection |
| Ports | core | `core/ports.py` | `SessionRepository`, `PartnerModel`, `CoachModel`, `Clock`, `IdFactory` |
| Use cases | core | `core/services.py` | `ConversationService`: start, list, get, act, cancel |
| Domain errors | core | `core/errors.py` | the `AppError` subclasses in § Decisions › The API |
| Call-log summary | core | `core/call_log.py` | pure grouped counts, reported tokens, USD cost and nearest-rank latency |
| Call-log read | adapters | `adapters/sql/call_log.py` | one constant query with typed optional filters and an owned read-only connection |
| Call-log command | root | `call_log.py` | `python -m intent_to_english.call_log`, exposed as `just backend call-log` |
| Storage | adapters | `adapters/sql/`, `adapters/memory.py` | the five tables below; the in-memory repository for tests and a run without a database URL |
| Model roles | adapters | `adapters/models/` | `fixed.py` (the fixed-response mode), `agents.py` (the provider-neutral PydanticAI task agents, run wrapper, and usage), `anthropic_provider.py` (everything Anthropic: the client, the PydanticAI model and settings, the failure mapping, refusal detection, and the price table), `prompts.py` (the messages each task sends), `schemas.py` (the Pydantic models each task's JSON schema comes from) |
| HTTP | api | `api/routers/sessions.py`, `api/routers/meta.py`, `api/schemas.py` | the routes in § Decisions › The API |
| Evaluation | its own package | `evaluation/cases.py`, `expectations.py`, `observed.py`, `harness.py`, `reports.py`, `__main__.py` | strict TOML, code expectations, observed task-runner calls, JSON/Markdown reports and `just backend eval` |
| Wiring | root | `settings.py`, `composition.py` | the settings in § Decisions › Keys, models, and the mode; the adapter choice |

The screen lives under `frontend/src/`: `routes/index.tsx` (S1), `routes/sessions.$sessionId.tsx`
(S2 and S3), a not-found route (S4), `features/sessions/` (S1: start, resume, and the list), `features/conversation/`
(both panes, the composer, the controls, the feedback card), `features/transcript/` (S3), and
the tokens in `styles.css`.

What crosses each boundary: the API hands the core an action, an opaque attempt UUID, and the version the screen
showed, and gets a `SessionView` back; the core hands a model port a request value and gets
an output value with its call's usage, or a model error; the repository stores and returns
core values only.

## Data

SQLite through SQLAlchemy Core and Alembic, as the template ships it (`persisting-data`).
Ids are UUIDv7 from `IdFactory`; times are UTC. A session has an end time exactly when
its status is ended. Every timeline kind has exactly one payload type; construction
rejects a mismatched pair before it can enter the append-only timeline.

| Table | Columns | Rules |
|---|---|---|
| `sessions` | `id`, `started_at`, `ended_at`, `status` (`in_progress` / `ended`), `stage`, `turn_index`, `turn_state` (JSON), `version`, `finished_replies`, `opener`, `wrap_up` (JSON) | one row per session; `version` goes up by one with every accepted action |
| `timeline_entries` | `id`, `session_id`, `seq`, `turn_index`, `kind`, `payload` (JSON), `created_at` | append-only: never updated or deleted; `(session_id, seq)` unique |
| `submissions` | `id`, `session_id`, `base_version`, `action`, `input` (JSON), `status` (`pending` / `completed` / `failed` / `cancelled`), `failure_code`, `boot_id`, `created_at`, `finished_at`, `attempt_id` (nullable for legacy rows) | one row per action the learner sent; a partial unique index on `(session_id, base_version)` where `status` is `pending` or `completed` |
| `submission_cancellations` | `session_id`, `base_version`, `attempt_id`, `created_at` | primary key on the three identity fields; retains a cancel even before action admission |
| `model_calls` | `id`, `session_id`, `submission_id`, `turn_index`, `role`, `task`, `attempt` (1, or 2 for the repair), `provider`, `model`, `input_tokens`, `output_tokens`, `cost`, `latency_ms`, `outcome`, `status` (nullable provider HTTP status), `violations` (JSON), `created_at` | one row per request to a model; never the key or the prompt text |

- `turn_state` holds only what the current stage's next action needs: the intent in force,
  the latest English, the feedback in force, retry submissions so far, the two readings at a
  reading check, the shown answer, and an optional practice target (the finished turn's index,
  intent, and feedback). The practice target survives the next Partner line until the learner's
  next intent or direct English. Everything else is read from the timeline.
- `outcome` is `ok`, `invalid_output` (failed its checks or did not parse), `repaired` (a
  repair that passed), `timeout`, `rate_limited`, or `provider_error` (§3.12). `cost` is USD
  computed from the reported tokens and the model's price (§ Keys, models, and the mode), null
  when the model has no price, and on a model error's row, which records no tokens. A failed submission uses `interrupted`
  when its earlier process or call budget has expired.
- At `ended`, `sessions.wrap_up` is null while a wrap-up is due; `{"items": []}` means
  there is nothing to make. A no-fix `feedback` entry still makes the wrap-up due. The empty
  `WrapUp` value is structurally valid; the service rejects an empty model-produced wrap-up.
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
| `ended` | the conversation is read-only; a due wrap-up can still be generated |

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
| `end` | every stage but `ended` | — | none | `ended`, immediately |
| `wrap_up` | `ended`, only while `wrap_up` is null | — | Coach `wrap_up` | `ended` |

"Done" means the turn ends: the service appends `turn_done`, adds one to
`finished_replies`, and moves to `check_in` when the count is a multiple of three, else to
`partner_turn`. The turn's final English is the learner's latest English of the turn (the
accepted or last retry, the typed copy, or the English itself), with every reading the
Coach noted applied, so the Partner hears what the learner meant; when the learner skips
after a shown answer without having written any English, it is the shown example. A
second retry that still misses gets the piece and ends the turn (§3.5). A shown answer's
typed copy is not checked and does not count as a retry. `practice_again` takes one
submission and shows its result; its two entries name the practised turn, even after the
Partner has opened the next turn. It changes only those entries and the version, never
the working turn state, finished count, stage or conversation. Its first-submission result
is a confirmation or a hint for the blanks still off; second-submission pieces are a schema
violation and get the same one repair. Hints receive every earlier
gap/hint pair after the current turn's latest intent. A replacement intent keeps the
practice target but clears the previous English, hints, feedback, readings, retry count
and shown answer from the working context; their old entries remain readable in history.
Both restatement modes use the latest original opener/reply, never a prior restatement;
restatements stay outside the English conversation and taking-turns count. A side question
uses the current feedback's completed-sentence check without advancing the turn. When a
session ends, `end` makes no model call: it stores `ended_at` and sets both status and stage
to `ended` at once. If a `feedback` entry exists, including feedback with no fix, it leaves
`wrap_up` null (due); otherwise it stores `WrapUp(items=())`. The separate `wrap_up` action
is allowed only at `ended` while due. It stores a checked Coach output without reopening the
session; a failure leaves the session ended and its wrap-up due.

At `partner_turn` the screen sends `partner_reply` by itself, so the Partner's line follows
the Coach's last block without a click; at `check_in`, `partner_reply` is 「続ける」 and `end`
is 「終わる」.

### One action, end to end

1. The screen sends `POST /api/sessions/{id}/actions` with the action, its input, and the
   session `version` it shows and a client-created UUID `attempt_id`. The ID exists
   before the request is sent; a transport retry retains it, a new logical submission
   creates another. Internal record IDs still come from the injected UUIDv7 factory.
2. One transaction checks that the session exists, then the version (`stale_session`
   otherwise). A live pending submission means `action_in_progress`, except that `end`
   supersedes it. An ended session rejects every action but `wrap_up` (`session_ended`);
   the stage must allow the action (`action_not_allowed`). Only when every check passes
   does the transaction check the attempt: a retained early cancel means
   `action_cancelled`, a previously admitted correlation means `attempt_already_used`.
   Only a new, uncancelled attempt can mark superseded work `cancelled` and store
   the new submission `pending` with the process's boot id. A refused begin cancels nothing.
   Before beginning, `ConversationService` checks the same order against its snapshot,
   then the extra action guards, normalized input limits and chosen reading. Invalid input
   stores no submission; the transaction repeats the existence, version, pending, ended
   and stage checks so a concurrent action cannot invalidate the snapshot.
3. When a model task is needed, outside any transaction the service builds its request — for the
   Partner, only the English lines — and calls the port within 60 s. A failed check, or an
   output that does not parse, gets one repair call carrying the violations. The standalone
   task runner binds each of the ten tasks to its role, port method and output check; the
   evaluation can use that same table without a session. Every attempt is recorded in
   `model_calls` as soon as it ends, before any repair starts. Model failures end the task
   without a retry. The service checks that the submission is still pending before a call
   and after each attempt is recorded, so cancelled work cannot start a repair. An empty
   model-produced wrap-up is a schema violation and gets the one
   repair; an empty stored wrap-up means there was nothing to make.
4. A second transaction re-reads the submission. If it is still `pending`, the service
   appends the timeline entries, updates the stage, `turn_state`, and `version`, and marks it
   `completed`, then returns the new `SessionView`. If the learner cancelled meanwhile, it
   discards the output (the call stays recorded) and answers 409 `action_cancelled`, which no
   screen is waiting for.
5. A model failure marks the submission `failed` with its code and answers 502, 503, or 504;
   the stage and version stay as they were, and the view offers the text again for
   「もう一度」. Any other exception also marks the submission `failed` before it propagates,
   so a bug never leaves a session stuck.

A cancel names the session, base version and opaque `attempt_id`. Admission and cancel
hold the same session transition lock (a row lock on PostgreSQL, `BEGIN IMMEDIATE` on
SQLite). A cancel at the current version records its identity even if the action has
not arrived; admission of that identity is then refused before a model call. It marks
only the matching pending attempt `cancelled`. A repeated cancel or a cancel for another
version changes no submission; a delayed cancel of A cannot affect a replacement B,
even at the same version with identical input. A completed action is never undone.
The screen then shows the stage as before with the text back in the composer. `end` also supersedes a live pending submission atomically, so
ending never waits for its model call; the late output is discarded and its call log stays.

### Interrupted calls

Each process start makes a boot id. A `pending` submission carrying another boot id belongs
to a process that stopped, so reading the session reports it as interrupted: the stage is as
before and the text is offered again (ux-flows F-5). A `pending` submission older than its
150 s call budget (two calls of 60 s, plus a 30 s margin) is reported the same way. A pending submission
of this process within its budget remains `pending` in the view, so a reopened screen waits
for its stored result. A new submission atomically marks an interrupted pending one
`failed` with code `interrupted` before taking its version. A closed tab does not interrupt
anything: the server finishes the call and stores the result, which the reopened screen
shows.

### The session view

`GET /api/sessions/{id}` and every accepted action return one `SessionView`: id, status, stage,
version, turn index, finished replies, start time, end time (null while in progress), the
actions the stage allows, every timeline entry in order, the last submission when it is pending, failed, or interrupted (its action, input,
and failure code), and the wrap-up. At `ended`, a null wrap-up is due; an empty item list
means there is nothing to make. The screen derives both panes and the next-action line
(ux-flows § Stage table) from it, and decides no stage itself.

## Quality targets

| Target | Proved by |
|---|---|
| Every model output passes its checks before it is stored or shown | core tests per check, from conversation-rules' list of checkable rules; a service test where a fake returns an invalid output, then a valid one, and one where both fail (502 `model_output_invalid`) |
| The Partner never receives the intent, hints, feedback, or questions | a test that builds every Partner request from a session full of marked Japanese and Coach text and finds none of the markers in it or in the prompt `prompts.py` renders |
| No live model call in tests or CI | PydanticAI's `ALLOW_MODEL_REQUESTS` set false for the backend suite; the settings isolation fixture removes `ANTHROPIC_API_KEY`; the browser test runs with the mode forced to fixed; a composition test pins the fixed adapter without a key |
| An action is processed at most once, and a stale one is rejected | repository contract tests (concurrent inserts against the partial unique index) and service tests (double send, stale version, cancel during a call, a pending submission from another boot) |
| The whole conversation works in the browser | `just e2e` drives F-1, F-2 (a turn with a fix and its retry), F-3, and F-5 in the fixed-response mode |
| Waiting states follow ux-guidelines (300 ms, 10 s, 60 s) | component tests with fake timers |
| Accessibility targets hold (WCAG 2.2 AA + 2.4.13) | component tests for focus after a stage change and the live regions; ux-guidelines' manual verification list |
| Cost, latency, and pass rates are known per model | the evaluation report |

## Decisions

### Models are called through PydanticAI, inside the model adapters

The app calls Claude through Anthropic's API with an Anthropic API key, through PydanticAI's
Anthropic model: it locks `pydantic-ai-slim[anthropic]` 2.55.0 and declares `anthropic`
(`>=1.17.0,<2`, from the release its client options were checked against) itself, because the
adapter builds the SDK client, under the seven-day dependency window. Both are imported only under `adapters/models/`: the core's import
test and ruff's banned-api rule keep `pydantic_ai`, `anthropic`, and `openai` out of `core/`,
and review keeps them out of `api/` and the storage adapters. The SDK stays below 2 because
pydantic-ai-slim 2.55.0 builds message parameters with `BetaMessageParam(...)`, which
anthropic 2.0.0 made a `Union` alias, so every request raised `TypeError` (`_map_message` in
`pydantic_ai/models/anthropic.py`, run against both versions on 2026-10-28); the cap lifts
with a PydanticAI release that supports anthropic 2. PydanticAI supplies the Anthropic model and
provider, typed structured output, and test models. The app turns off what would hide calls
from the core:

- **No automatic retries and no fallback.** PydanticAI's output retries are 0, and the provider
  gets an `anthropic.AsyncAnthropic` client with `max_retries=0` (the SDK's default is 2): one
  request is one recorded, billed call, and the 60 s budget per call holds. No fallback model
  or server-side refusal fallback is configured, for the same reason.
- **JSON schema output.** Each task's `output_type` is wrapped in `NativeOutput`, which
  PydanticAI's Anthropic model sends as `output_config.format = {"type": "json_schema",
  "schema": ...}`, and its `prepare_request` forces the schema strict (it refuses
  `strict=False`) — `_build_output_config` and `prepare_request` in
  `pydantic_ai/models/anthropic.py`, pydantic-ai-slim 2.55.0, read in the locked install and
  confirmed on the wire by the adapter tests, 2026-10-28. PydanticAI's default is a forced
  tool call, which Claude Sonnet 5.5 rejects.
- **Bounded output, sent in one response.** Every call sends `max_tokens` 16,000: room for
  adaptive thinking at medium effort plus the JSON answer. Without it PydanticAI sends the
  model's maximum output (128K) and, above its 21,333-token non-streaming cap, streams the
  request behind the scenes (`_default_max_tokens` and `_messages_create`, same file and
  version).
- **Usage per request, priced here.** Tokens come from each response's usage (`input_tokens`,
  and `output_tokens`, which include thinking); Anthropic reports no cost, so the provider
  module prices them from its own table (§ Keys, models, and the mode).

The adapter is split so another provider replaces one module. `agents.py` holds what does not
depend on the provider: the Partner's three and the Coach's seven task agents, built once over
their role models, the run wrapper (the 60 s scope, parse failures, refusals), and usage
handling. It reaches the provider only through a small `ProviderCalls` value: its name, its
settings, its failure mapping, its refusal check, and its cost. `anthropic_provider.py` holds
everything Anthropic: the client, `AnthropicModel` and `AnthropicProvider`,
`AnthropicModelSettings` (`timeout` 60, `max_tokens`, and `anthropic_effort`), the SDK error
mapping, the `refusal` stop reason, and the price table. Moving to Amazon Bedrock means one new
provider module and the selection in `composition.py`, nothing under `core/`, `api/`, or the
prompts. The owner expects that move once the account's Bedrock quota allows it, by either of
two routes: the Anthropic SDK's Bedrock client (`AsyncAnthropicBedrock`) behind PydanticAI's
same Anthropic provider and model, or PydanticAI's Bedrock model with the `bedrock` extra.

Both models share one provider and one client with one registered close callback. The client
builder passes the key and the base URL `https://api.anthropic.com` explicitly, so
`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_PROFILE`,
`ANTHROPIC_CONFIG_DIR`, and the Workload Identity Federation variables change no request (an
explicit credential skips the SDK's credential chain; anthropic 1.17.0 `_client.py`). The SDK
still merges `ANTHROPIC_CUSTOM_HEADERS` into every request with no option to turn it off, so the
builder resets the client's private `_custom_headers` to empty right after construction; it sets
no headers of its own. It passes `open_telemetry={"traces": False, "propagation": False}`, so
the SDK's own spans and trace propagation stay off, as PydanticAI's are: the per-agent
`instrument = False` overrides global instrumentation. A test sets each of those variables and
finds the request unchanged. The SDK reads `ANTHROPIC_LOG` at import and, at `debug`, would log
every request's options, the learner's text included, so the provider module holds the
`anthropic` and `httpx2` loggers at WARNING. The standard proxy and TLS variables
(`HTTPS_PROXY`, `SSL_CERT_FILE`, and the like) still apply to the SDK's HTTP client on purpose:
they choose the network path, not the request, and ignoring them would break a machine that
needs a proxy or its own CA. A 60-second scope also bounds the complete run, not only SDK
socket waits. Parse failures retain response usage, while provider failures carry only safe
core errors, latency, and the provider's HTTP status when it answered with one: an integer that
tells a rejected request (400) from an outage (529) without carrying the provider's text.

A response whose stop reason is `refusal` is not a parse failure and gets no repair: re-asking
would only repeat the refused request. PydanticAI raises `ContentFilterError` (a subclass of
`UnexpectedModelBehavior`) when a refusal carries no usable text, and validates whatever text it
does carry, so the run wrapper asks the provider module whether the last response was a refusal
before it treats any outcome as a parse failure or a success. A refusal becomes
`model_unavailable` (HTTP 502) and its `model_calls` row the outcome `provider_error`, with no
status; like every model error's row, it records no tokens or cost.

Coach feedback uses one top-level JSON object with a `kind` discriminator and exactly one
matching feedback or reading-question payload. Retry results use a kind-tagged payload inside a
top-level object too, so every task supports native structured output. The schemas stay inside
what Anthropic's structured output accepts, because anything else is a 400 that the adapter
reports as unavailable (https://platform.claude.com/docs/en/build-with-claude/structured-outputs,
"JSON Schema limitations", observed 2026-10-28): unions are `anyOf` (a pydantic discriminator
would emit `oneOf`, which the supported keywords do not include), objects close with
`additionalProperties: false`, and arrays carry no length beyond `minItems` 0 or 1, so the two
readings are checked when the output converts. A test walks the schema each task sends on the
wire against that list.

Rejected: calling Anthropic's API with httpx2 directly — no new package and full control, but
the request, the schema, parsing, retries, and error mapping would all be hand-written, and
Bedrock would be a second adapter written from scratch. Rejected: Strands Agents — its
structured output is a tool call that retries on a validation failure and forces `tool_choice`
on that retry, and its default retry strategy repeats throttled calls up to six times, both of
which break "one request is one recorded, billed call".

Sources: https://github.com/pydantic/pydantic-ai/releases/tag/v2.55.0 (released 2026-10-09,
Python ≥3.11, MIT; extra `anthropic` requires `anthropic>=1.12.1`);
https://github.com/pydantic/pydantic-ai/blob/main/docs/version-policy.md (no intentional
breaking change in a minor release; the next major at least three months after 2.0.0 of
2026-06-23). Claude Sonnet 5.5 returns 400 on a forced `tool_choice`:
https://platform.claude.com/docs/en/about-claude/models/migration-guide (Migrating to Claude
Sonnet 5.5; Anthropic's reference as cached on 2026-10-06).

The model stack's lock holds ten packages: pydantic-ai-slim, pydantic-graph, anthropic,
docstring-parser, griffelib, opentelemetry-api, genai-prices, logfire-api, jiter and sniffio.
Of those, the `anthropic` extra is what brings anthropic 1.17.0 (MIT, one `py3-none-any`
wheel, Python ≥3.10) and docstring-parser 0.18.0 (MIT, pure Python); anthropic's other
requirements (anyio, httpx2, jiter, opentelemetry-api, pydantic, sniffio, typing-extensions)
are shared with the rest of the lock, and no `openai` package is locked. OSV's version-specific query returned no advisories
for anthropic 1.17.0 or docstring-parser 0.18.0 on 2026-10-28; Dependency Review and OSV CI
remain gates. anthropic 2.x is Apache-2.0, also on the license allow-list, should the cap lift.

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

An action runs at most one model task and its one repair. Each call has a 60 s budget,
so the task and repair together can take two 60 s calls; each failure names one pane.
`end` ends the session without a model call. A due wrap-up is its own `wrap_up` action at
`ended`, so a failed wrap-up never reopens or prevents the end. The Partner's line after a
finished turn is its own action (`partner_reply`), which the screen sends at `partner_turn`
without a click.

### The session is one row and an append-only timeline

The `sessions` row holds the stage, the current turn's working state, and the version; the
timeline holds every entry as JSON in order; `submissions` holds what the learner sent and
what became of it; `model_calls` holds the log (§ Data). The transcript (S3), the left pane,
and the Partner's context are reads of the timeline. JSON payloads are SQLAlchemy `JSON`
columns, which the template's PostgreSQL contract suite also covers. Rejected: normalized
tables (about ten, and a migration for every new element of a turn) and event sourcing
(folding every event on every read, and versioning the events).

The SQL repository serializes transitions under a session-row lock on PostgreSQL. SQLite
uses SQLAlchemy's explicit transaction hooks and `BEGIN IMMEDIATE`, taking the writer lock
before reading so concurrent begins cannot race a read-to-write lock upgrade. Snapshot
reads take the same lock for a consistent session, timeline and latest submission. The
wrap-up JSON column stores Python `None` as SQL NULL, separately from `{"items": []}`.
Provider cost is decimal text on both databases so SQLite never rounds it through a
binary float; the log reader restores `Decimal` before summing. JSON readers restore core
constructors and optional defaults, keeping older payloads readable.

### The call log has a read-only command

Each model error retains its reported HTTP status as a nullable integer on the call
attempt and in `model_calls`. Historical calls and failures without an HTTP response
keep null. Outcome cells in the existing role/model/task summary show status counts
when present, such as `4 (400: 2, 503: 1)`; the total still includes unreported statuses.
Only the integer is retained, never a provider response body or diagnostic text.

`just backend call-log [--session UUID] [--since YYYY-MM-DD|ISO-datetime]` resolves
the database URL as the migration recipe does, defaulting to `backend/var/dev.db`
and adding the PostgreSQL extra for that driver. It never migrates, constructs
models, or writes. Its SQL reader owns a separate read-only engine, rather than
the application's SQLite writer-lock transaction hooks: SQLite uses `mode=ro`
and `query_only`, PostgreSQL a serializable read-only transaction. A missing SQLite
file is rejected before driver startup, and read-only mode still prevents creation
if it disappears after that check; missing or unmigrated databases return 1 with a
`just backend db-upgrade` instruction. The reader restores core records on its own
connection and always disposes its engine.

The CLI converts offsetless dates/datetimes from historical local time to UTC;
an explicit offset is honored. The constant query combines optional session and
inclusive `created_at >= since` filters. Pure summaries sort by role, model and
task, count each request including repairs and all six outcomes, sum reported
tokens and USD cost (unknown throughout a group is `—`, a recorded zero is zero),
and use the ceiling-ranked 50th/95th percentiles. The shared core cost helper
preserves recorded decimals; mixed known/unknown costs sum only the reported
values, as this command's contract requires. This differs from evaluation's
complete-task-cost display. Only accounting appears on stdout; no prompt, learner
text or key. An empty filtered log prints `No model calls recorded.` and returns
0, a successful table returns 0, and invalid UUID/date arguments return 2.

### Stale, repeated, cancelled, and interrupted actions

Every action names the version it answers, so a second tab or a reloaded screen gets 409
`stale_session` and reloads the session (§4). The partial unique index on `submissions`
admits one pending or completed submission per version, so a double click is 409
`action_in_progress` and is processed once. `end` supersedes a live pending submission:
the transaction changes the old row to `cancelled` before inserting the new pending row,
so the partial index admits it; a refused begin changes nothing. Cancellation matches
the base version and attempt UUID, so the slot can be reused without changing what an
old cancellation names. A retained cancellation also prevents admission if cancel
arrives first. The unique `(session_id, attempt_id)` constraint prevents one logical
attempt from being admitted twice, including after failure. Legacy rows retain null
correlation and expose their existing record UUID as a stable fallback. No primary or
model-call foreign key changes during migration. Cancelled input and call history are
retained; a request cancelled before admission creates no submission and the browser
keeps its draft. Calls from cancelled work stay in `model_calls`. The next begin marks an interrupted pending row `failed` before storing a
replacement, using the boot id and cutoff to recognize it (§ Core flows).

### Keys, models, and the mode

| Setting | Default | Effect |
|---|---|---|
| `ANTHROPIC_API_KEY` | unset | the Anthropic API key, unprefixed (the name Anthropic documents), read through a validation alias as a secret; unset or blank runs the fixed-response mode |
| `INTENT_TO_ENGLISH_MODEL_MODE` | `auto` | `auto` with a key selects the Anthropic adapters for both roles; `fixed` explicitly pins offline responses |
| `INTENT_TO_ENGLISH_COACH_MODEL` | `claude-sonnet-5-5` | the Coach's Anthropic model id |
| `INTENT_TO_ENGLISH_PARTNER_MODEL` | `claude-haiku-5-5` | the Partner's Anthropic model id |
| `INTENT_TO_ENGLISH_COACH_REASONING_EFFORT` | `medium` | the Coach's `output_config.effort`: `low`, `medium`, `high`, `xhigh`, or `max` |
| `INTENT_TO_ENGLISH_PARTNER_REASONING_EFFORT` | `medium` | the Partner's, read the same way |

The composition root selects both Anthropic adapters when auto mode has a key,
otherwise both fixed adapters, and exposes the selection through `Container.model_mode`.
Only composition unwraps the secret for the shared-client builder. The provider-key alias
is a `SecretStr`,
omitted from settings repr; a blank key is none. Empty model ids keep their defaults,
while whitespace-only ids fail at startup naming their variables. Each role's reasoning
effort is its own setting, because the Coach is nearly all of a run's cost and the slow
side of a turn while the Partner is neither, so the two are tuned apart. Every call sends
its role's effort as `anthropic_effort`; empty keeps `medium`, the levels are
case-insensitive, and any other value (`minimal` and `none` included) fails at
startup naming its variable. The adapter sets no `thinking`: both models think adaptively by
default, and Sonnet 5.5 rejects disabled thinking. One boot id is made
per container build, independently of entity ids. With SQL selected, the two repository
ports share one lazy engine and one disposal callback. This keeps the full HTTP flow
usable without a key and lets fixed mode prevent billing even with one set.
`Container.models` holds those same role ports in a frozen `ModelPorts` value. The
evaluation uses the same container and selected mode with memory storage explicitly
selected, so it shares model choice and owned cleanup without opening a database.

The defaults follow the owner's rule: the cheap model where it holds quality, a stronger one
only where it does not, and Sonnet is the ceiling — no Opus or Fable default; whether the
Coach can move to Haiku is the evaluation's call. Anthropic's model list is the authority on
model ids, so a model id is only checked to be non-empty.

Cost is recorded in USD, computed from each response's reported tokens and the configured
model's price in `anthropic_provider.py`'s table; a model without a price there records a
null cost. The table holds the base input / output prices per million tokens from
https://platform.claude.com/docs/en/about-claude/pricing (observed 2026-10-28): Sonnet 5.5 at
$2 / $10, Haiku 5.5 at $0.10 / $0.50 for a prompt of up to 100,000 tokens and $0.50 / $2.50 for
a prompt over that. The prompt length counts every input token including cache reads and
writes; the adapter sends no cache control, so the reported input tokens are the prompt.
Thinking is billed as output and is inside the reported output tokens. Rows recorded under
OpenRouter keep their cost: OpenRouter's credits are USD-denominated, so the column's unit is
unchanged. The fixed-response mode is in `adapters/models/fixed.py`: its outputs are
deterministic functions of the request, pass every check, reach every stage (a reading check
and a blank still off included), and report provider `fixed` with no tokens or cost.

### The API

| Route | Result |
|---|---|
| `POST /api/sessions` | 201 with the new session at `opening`, version 0; no model call |
| `GET /api/sessions?cursor=&limit=` | one page, newest first, 20 by default: id, start time, status, finished replies, opener |
| `GET /api/sessions/{id}` | the `SessionView` |
| `POST /api/sessions/{id}/actions` | the new `SessionView`; 17 body models discriminated by `action`, each with required `version` and UUID `attempt_id`; text actions use `text`, hints use `gap` and `partial_english`, readings use `reading`, restatements use `mode`, and model-free actions carry no input fields |
| `POST /api/sessions/{id}/cancel` | body `{"version": <int>, "attempt_id": "<uuid>"}`; 204 for the exact attempt, including an early/repeated cancel, 404 for an unknown session, and 422 for missing/invalid fields; the session version does not move |
| `GET /api/meta` | `{"model_mode": "fixed" \| "anthropic"}`, for the header badge on every screen |

| Error | Status | Code |
|---|---|---|
| unknown session | 404 | `session_not_found` |
| the version moved on | 409 | `stale_session` |
| a submission is pending | 409 | `action_in_progress` |
| a correlation ID was already admitted | 409 | `attempt_already_used` |
| the stage does not allow the action | 409 | `action_not_allowed` |
| the session has ended | 409 | `session_ended` |
| the output arrived after a cancel | 409 | `action_cancelled` |
| an input outside its limits | 422 | `invalid_input` |
| a forged listing cursor | 422 | `invalid_cursor` |
| a page limit outside 1–100 | 422 | `invalid_page_limit` |
| a body or path that does not parse | 422 | `request_invalid` |
| the call passed 60 s | 504 | `model_timeout` |
| the provider is rate limiting | 503 | `model_rate_limited` |
| the provider failed or is unreachable | 502 | `model_unavailable` |
| the output failed its checks after the repair | 502 | `model_output_invalid` |

The screen chooses its banner text from the code (ux-guidelines § States). The template's
Problem Details shape, request-id middleware, and `AppError` mapping in `api/app.py` stay.
The wire models are separate Pydantic values: every timeline entry has one of 21
`kind` discriminators, and the public view includes both start/end times. The core
owns text limits, so those failures keep `invalid_input` instead of parser errors.
`end` runs without a model and returns the ended view immediately; feedback makes a
null wrap-up due and permits only `wrap_up`. With no feedback, `WrapUp(items=())`
is already complete. The separate `wrap_up` action returns the new ended view.

### Evaluation lives in the repository

The 16 TOML cases under `backend/evals/cases/` are read with `tomllib`: `task` as
`role.method`, `source`, the exact request dataclass fields in `[request]`, optional
`[context]` notes and `[[expect]]` values. Required nullable fields use the explicit
`{ none = true }` marker; empty strings remain strings, nested defaults follow their
dataclasses, and unknown or missing required fields fail with the filename and key.
Context never reaches a model, including the Sapporo intent kept outside its Partner
request. A set may hold 10–20 cases, with no fixed sixteen-case limit in the loader.

The closed expectation set is `tagged`, `not_tagged`, `no_tag`, `no_fix`, `max_fixes`,
`missing_point`, `fix_to`, `reading_question`, `accepted`, `reading_noted`, `absent`,
`no_question` and `differs_from`. Each has strict arguments and task applicability;
missing-point expectations assert no tag. Code decides pass or fail without a model
grader or candidate checks (§3.11).

`just backend eval` is billed and human-run. It uses `Container.models` through the
shared task runner and one repair, observes each actual return without another call,
and holds attempt records only in memory. A provider error is recorded and the next
case still runs. Fixed mode refuses before calls or writes, naming the key and mode
variables. Auto mode with a key runs the selected Anthropic roles. Both report paths and
exactly one ordered README marker pair are checked before calls. Existing reports
are never overwritten; exclusive writes also guard against a concurrent writer.
Publication stages the README and replaces it only after both reports close
successfully. A failure removes only artifacts exclusively created by that run,
leaving the original README and any concurrent writer's files intact.

The Markdown and JSON reports under `backend/evals/reports/` use
`<UTC-date>_<coach-id>_<partner-id>`, replacing `/` with `-` in model ids, followed by
`_coach-effort-<level>` and `_partner-effort-<level>` for each effort other than the default
`medium`, so a run at another effort is its own report pair beside the default run of the
same day. They include both configured ids and both efforts, the UTC date, commit and dirty
state passed by the recipe, first-attempt and final rates per check and expectation, all
outcomes per task, the recorded cost in USD (`cost_usd`), and nearest-rank p50/p95 latency. Repairs count as
separate calls. A task's cost is empty if any attempt has no reported cost; known
costs are summed without rounding provider decimals through the shared core helper.
Provider failures and unparsed content are
N/A in quality denominators, with schema failures still counted for schema. Each
case retains its safe decisions and outcomes. When at least one final expectation
fails, the JSON case also retains the final parsed model output as `final_output`,
so the owner can inspect that failure without another billed run. Passing and
unobserved expectations retain no output; a failed first attempt repaired to a pass
also retains none. Raw provider responses and diagnostics are never retained. Each
case includes its error code with the HTTP status beside it (`error_status` in JSON, `model_unavailable
(HTTP 400)` in the Markdown Error column) when the provider returned one.

Both reports are committed. The README summary between `eval-summary:start` and
`eval-summary:end` links the latest report and uses its generated task table; before
the first owner-run evaluation it says no run exists. The command rereads README
after calls and preserves outside edits. Fixed-port tests render the full seed set
and rewrite a temporary README without judging any pass rate. A completed report
returns 0 even with failed expectations; refusals/failures return 1 and usage errors
2. Rejected: local-only reports, a hand-written summary and overwriting a prior run.

### Japanese in the repository

The repository's English-only rule has one exception, worded in `AGENTS.md`: the Japanese the
product speaks — UI copy, prompts, fixed responses and test data, and the quoted copy and
learner inputs in the conversation rules and evaluation cases. Code, identifiers, comments,
commits, pull requests, and document prose stay English.

### What the app keeps from the template

SQLite is the default store, with the PostgreSQL contract suite and its CI job, so a hosted
deployment later starts from portable SQL; the in-memory repository is the core tests' fake
and the store of a run without a database URL; the composition root, the `AppError` mapping,
the health route, the middleware, and the opaque page cursor come from the template. The
template's sample domain is not part of the app at any layer. Its table stays in the schema's
history only: the first revision creates it and a later one drops it, because a revision on
`main` is never edited and a database migrated before the drop reaches the same head. Rejected:
replacing the first revision, which would leave such a database unable to upgrade.

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
  Opacity modifiers on these tokens are allowed with tailwindcss 4.3.3 (checked
  2026-10-18). The production build rewrites the ink token as
  `--color-ink:var(--lightningcss-light,#1c1f24)var(--lightningcss-dark,#eceef1)`;
  the root's fallback variables swap their initial/empty values in
  `@media (prefers-color-scheme:dark)`. The `bg-ink/50` probe emits
  `background-color:var(--lightningcss-light,#1c1f2480)var(--lightningcss-dark,#eceef180)`
  and, inside its color-mix support query,
  `background-color:color-mix(in oklab, var(--color-ink) 50%, transparent)`.
  Both forms follow the OS scheme; the probe is absent from the source.
- **Contrast:** the 53 light and dark pairs in `docs/design/contrast-pairs.json` pass WCAG 2.2
  AA (measured 2026-10-28); a token change re-measures them in the same pull request.

## Open

- Whether either role should default to another effort than `medium`: effort trades output
  tokens and latency for quality. The per-role setting exists; the owner's evaluation runs
  settle whether a default changes (#91).
- The tag of a missing nuance that is not a core point — ミス or 改善 (conversation-rules
  §5.3). The owner decides; until then evaluation cases assert no tag for it.
- A one-word reply: its fill-in template is a single blank, so the blank's 直す is the whole
  completed sentence, which the completed-sentence check refuses in the feedback and in a retry
  result that gives the piece (conversation-rules §5.3, §5.4, §6). The owner decides how such a
  reply is coached; until then the checks apply as written and the fixed-response mode answers a
  one-word reply with no fix.
- The Bedrock provider module's output mode: Claude Sonnet 5.5 rejects a forced tool call there
  too, so the module must use the JSON schema mode its route supports — checked when the
  account's Bedrock quota allows (§2 Later).
