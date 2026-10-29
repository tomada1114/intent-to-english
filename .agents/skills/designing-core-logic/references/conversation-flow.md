# The conversation flow

Read when changing the stage machine, an action, `ConversationService`, the session view,
or how a submission is admitted, cancelled, or interrupted. What the app does is
`AGENTS.md`'s Product section and `docs/product/requirements.md` (cited as §n); the screens
and their stage table are `docs/product/ux-flows.md`'s; what each model role writes is
`docs/product/conversation-rules.md`'s. How a model task is called is `calling-models`'; how
the tables store all this is `persisting-data`' [app-schema reference](../../persisting-data/references/app-schema.md).

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
- **No live model call outside the owner's own practice.** Tests, the browser test, and CI
  run the fixed-response adapter or scripted fakes (Non-goals). Rules out: live, recorded, or
  skipped-when-keyless tests.
- **The learner's words survive.** A submission is stored before its model call, so a
  failure, a cancel, a stale tab, or a server stop never loses the text (ux-guidelines §
  Principles, §4). Rules out: holding a pending input only in memory or only in the browser.

## Where each piece lives

Under `backend/src/intent_to_english/`; the model adapters' modules are `calling-models`':

| Domain | Module | Holds |
|---|---|---|
| Session, stage, timeline, submission, model-call record | `core/models.py` | frozen dataclasses and enums, including `Stage` and `Action`; no I/O |
| The stage machine | `core/flow.py` | which action each stage allows, input limits, and the next stage |
| Partner and Coach request and output values | `core/partner.py`, `core/coaching.py` | the ports' value types and each task's output checks |
| Shared text helpers | `core/text.py` | sentence splitting, question counting, Latin and Japanese script detection |
| Ports | `core/ports.py` | `SessionRepository`, `PartnerModel`, `CoachModel`, `Clock`, `IdFactory` |
| Use cases | `core/services.py` | `ConversationService`: start, list, get, act, cancel; the model task runner |
| Domain errors | `core/errors.py` | the `AppError` subclasses (`designing-errors`) |
| Call-log summary | `core/call_log.py` | pure grouped counts, reported tokens, USD cost and nearest-rank latency |
| Call-log read and command | `adapters/sql/call_log.py`, `call_log.py` | `just backend call-log` (`persisting-data`) |
| Storage | `adapters/sql/`, `adapters/memory.py` | the five tables; the in-memory repository for tests and a run without a database URL |
| HTTP | `api/routers/sessions.py`, `api/routers/meta.py`, `api/schemas.py` | the routes in `README.md`'s HTTP table (`building-api-routes`) |
| Wiring | `settings.py`, `composition.py` | the settings and the adapter choice |

What crosses each boundary: the API hands the core an action, an opaque attempt UUID, and the
version the screen showed, and gets a `SessionView` back; the core hands a model port a
request value and gets an output value with its call's usage, or a model error; the
repository stores and returns core values only.

## The stage machine

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
typed copy is not checked and does not count as a retry.

- `practice_again` takes one submission and shows its result; its two entries name the
  practised turn, even after the Partner has opened the next turn. It changes only those
  entries and the version, never the working turn state, finished count, stage, or
  conversation. Its first-submission result is a confirmation or a hint for the blanks
  still off; second-submission pieces are a schema violation and get the same one repair.
- Hints receive every earlier gap/hint pair after the current turn's latest intent.
- A replacement intent keeps the practice target but clears the previous English, hints,
  feedback, readings, retry count, and shown answer from the working context; their old
  entries remain readable in history.
- Both restatement modes use the latest original opener or reply, never a prior
  restatement; restatements stay outside the English conversation and the taking-turns count.
- A side question uses the current feedback's completed-sentence check without advancing
  the turn.
- `end` makes no model call: it stores `ended_at` and sets both status and stage to `ended`
  at once. If a `feedback` entry exists, including feedback with no fix, it leaves `wrap_up`
  null (due); otherwise it stores `WrapUp(items=())`. The separate `wrap_up` action is
  allowed only at `ended` while due; it stores a checked Coach output without reopening the
  session, and a failure leaves the session ended and its wrap-up due.

At `partner_turn` the screen sends `partner_reply` by itself, so the Partner's line follows
the Coach's last block without a click; at `check_in`, `partner_reply` is 「続ける」 and `end`
is 「終わる」.

An action runs at most one model task and its one repair, each call with a 60 s budget, and
each failure names one pane. That is why a due wrap-up is its own action — a failed wrap-up
never reopens or prevents the end — and why the Partner's line after a finished turn is its
own action.

## One action, end to end

1. The screen sends `POST /api/sessions/{id}/actions` with the action, its input, the session
   `version` it shows, and a client-created UUID `attempt_id`. The id exists before the
   request is sent; a transport retry retains it, a new logical submission creates another.
   Internal record ids still come from the injected UUIDv7 factory.
2. One transaction checks that the session exists, then the version (`stale_session`
   otherwise). A live pending submission means `action_in_progress`, except that `end`
   supersedes it. An ended session rejects every action but `wrap_up` (`session_ended`);
   the stage must allow the action (`action_not_allowed`). Only when every check passes
   does the transaction check the attempt: a retained early cancel means
   `action_cancelled`, a previously admitted correlation means `attempt_already_used`.
   Only a new, uncancelled attempt can mark superseded work `cancelled` and store the new
   submission `pending` with the process's boot id. A refused begin cancels nothing.
   Before beginning, `ConversationService` checks the same order against its snapshot,
   then the extra action guards, normalized input limits, and chosen reading. Invalid input
   stores no submission; the transaction repeats the existence, version, pending, ended,
   and stage checks so a concurrent action cannot invalidate the snapshot.
3. When a model task is needed, outside any transaction the service builds its request —
   for the Partner, only the English lines — and runs it through `MODEL_TASKS`, which binds
   each of the ten tasks to its role, port method, and output check (`calling-models`'
   sequence). The service checks that the submission is still pending before a call and
   after each attempt is recorded, so cancelled work cannot start a repair. An empty
   model-produced wrap-up is a schema violation (`_schema_violations`, not
   `coaching.check_wrap_up`) and gets the one repair; an empty stored wrap-up means there
   was nothing to make.
4. A second transaction re-reads the submission. If it is still `pending`, the service
   appends the timeline entries, updates the stage, `turn_state`, and `version`, and marks
   it `completed`, then returns the new `SessionView`. If the learner cancelled meanwhile,
   it discards the output (the call stays recorded) and answers 409 `action_cancelled`,
   which no screen is waiting for.
5. A model failure marks the submission `failed` with its code and answers 502, 503, or
   504; the stage and version stay as they were, and the view offers the text again for
   「もう一度」. Any other exception also marks the submission `failed` before it
   propagates, so a bug never leaves a session stuck.

## Stale, repeated, and cancelled actions

Every action names the version it answers, so a second tab or a reloaded screen gets 409
`stale_session` and reloads the session (§4). The partial unique index on `submissions`
admits one pending or completed submission per version, so a double click is 409
`action_in_progress` and is processed once. `end` supersedes a live pending submission
atomically: the old row becomes `cancelled` before the new pending row is inserted, so
ending never waits for its model call; the late output is discarded and its call log stays.

A cancel names the session, base version, and opaque `attempt_id`. Admission and cancel
hold the same session transition lock. A cancel at the current version records its
identity even if the action has not arrived; admission of that identity is then refused
before a model call. It marks only the matching pending attempt `cancelled`. A repeated
cancel or a cancel for another version changes no submission; a delayed cancel of A cannot
affect a replacement B, even at the same version with identical input. The unique
`(session_id, attempt_id)` constraint keeps one logical attempt from being admitted twice,
including after failure. Legacy rows keep a null correlation and expose their record UUID as
a stable fallback. A completed action is never undone. A request cancelled before admission
creates no submission and the browser keeps its draft; the screen shows the stage as before
with the text back in the composer.

## Interrupted calls

Each process start makes a boot id. A `pending` submission carrying another boot id belongs
to a process that stopped, so reading the session reports it as interrupted: the stage is as
before and the text is offered again (ux-flows F-5). A `pending` submission older than its
150 s call budget (two calls of 60 s, plus a 30 s margin) is reported the same way. A pending
submission of this process within its budget remains `pending` in the view, so a reopened
screen waits for its stored result. A new submission atomically marks an interrupted pending
one `failed` with code `interrupted` before taking its version. A closed tab interrupts
nothing: the server finishes the call and stores the result, which the reopened screen shows.

## The session view

`GET /api/sessions/{id}` and every accepted action return one `SessionView`: id, status,
stage, version, turn index, finished replies, start time, end time (null while in progress),
the actions the stage allows, every timeline entry in order, the last submission when it is
pending, failed, or interrupted (its action, input, and failure code), and the wrap-up. At
`ended`, a null wrap-up is due; an empty item list means there is nothing to make. The
screen derives both panes and the next-action line (ux-flows § Stage table) from it, and
decides no stage itself.

## What the suite proves

- An action is processed at most once and a stale one is rejected: repository contract tests
  (concurrent inserts against the partial unique index) and service tests (double send,
  stale version, cancel during a call, a pending submission from another boot).
- The whole conversation works in the browser: `just e2e` drives F-1, F-2 (a turn with a fix
  and its retry), F-3, and F-5 in the fixed-response mode.
