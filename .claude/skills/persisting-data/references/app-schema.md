# The app's schema

Read when changing one of the app's five tables, a timeline payload, `turn_state`, how the
SQL repository stores a session, or the call-log command. `tables.py` is the columns'
source of truth; this page holds the rules the columns do not show. Which action writes
what is `designing-core-logic`'s [conversation-flow reference](../../designing-core-logic/references/conversation-flow.md).

## One row and an append-only timeline

The `sessions` row holds the stage, the current turn's working state, and the version; the
timeline holds every entry as JSON in order; `submissions` holds what the learner sent and
what became of it; `model_calls` holds the log. The transcript (S3), the left pane, and the
Partner's context are reads of the timeline. JSON payloads are SQLAlchemy `JSON` columns,
which the PostgreSQL contract suite also covers. Rejected: normalized tables (about ten,
and a migration for every new element of a turn) and event sourcing (folding every event
on every read, and versioning the events).

Ids are UUIDv7 from `IdFactory`; times are UTC. A session has an end time exactly when its
status is ended. Every timeline kind has exactly one payload type; construction rejects a
mismatched pair before it can enter the timeline.

| Table | Rules |
|---|---|
| `sessions` | one row per session; `version` goes up by one with every accepted action |
| `timeline_entries` | append-only: never updated or deleted; `(session_id, seq)` unique |
| `submissions` | one row per action the learner sent; a partial unique index on `(session_id, base_version)` where `status` is `pending` or `completed`; `(session_id, attempt_id)` unique, `attempt_id` null only on legacy rows |
| `submission_cancellations` | primary key on `session_id`, `base_version`, `attempt_id`; retains a cancel even before the action is admitted |
| `model_calls` | one row per request to a model, the repair included (`attempt` 2); never the key or the prompt text |

- `turn_state` holds only what the current stage's next action needs: the intent in force,
  the latest English, the feedback in force, retry submissions so far, the two readings at
  a reading check, the shown answer, and an optional practice target (the finished turn's
  index, intent, and feedback). The practice target survives the next Partner line until
  the learner's next intent or direct English. Everything else is read from the timeline.
- `model_calls.outcome` is `ok`, `invalid_output`, `repaired`, `timeout`, `rate_limited`, or
  `provider_error` (`calling-models`). `cost` is USD from the reported tokens and the
  model's price, null when the model has no price and on a model error's row, which records
  no tokens. `status` is the provider's HTTP status as a nullable integer — never its body.
  Rows recorded under OpenRouter keep their cost: its credits were USD-denominated. A failed
  submission uses failure code `interrupted` when its earlier process or call budget expired.
- Cost is decimal text on both databases, so SQLite never rounds it through a binary float;
  readers restore `Decimal` before summing.
- At `ended`, `sessions.wrap_up` is SQL NULL while a wrap-up is due and `{"items": []}` when
  there is nothing to make; the JSON column stores Python `None` as SQL NULL, apart from the
  empty object. A no-fix `feedback` entry still makes the wrap-up due.
- A payload change keeps old rows readable: a new field has a default; anything else ships
  an Alembic data migration in the same pull request. JSON readers restore core
  constructors and optional defaults.
- No primary key or model-call foreign key changed when attempt correlation arrived; legacy
  submissions keep a null `attempt_id`.

## Timeline entry kinds

Each kind is a core value stored as its `payload`:

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

## Transitions under one lock

The SQL repository serializes transitions under a session-row lock on PostgreSQL. SQLite
uses SQLAlchemy's explicit transaction hooks and `BEGIN IMMEDIATE`, taking the writer lock
before reading so concurrent begins cannot race a read-to-write lock upgrade. Admission,
cancellation, and snapshot reads all take it (`SKILL.md`'s statements section).

## The template's sample table

SQLite is the default store, with the PostgreSQL contract suite and its CI job, so a hosted
deployment later starts from portable SQL. The template's sample domain is not part of the
app at any layer; its table stays in the schema's history only: the first revision creates
it and a later one drops it, because a revision on `main` is never edited and a database
migrated before the drop reaches the same head. Rejected: replacing the first revision,
which would leave such a database unable to upgrade.

## The call-log command

`just backend call-log [--session UUID] [--since YYYY-MM-DD|ISO-datetime]` resolves the
database URL as the migration recipe does, defaulting to `backend/var/dev.db`, and adds the
PostgreSQL extra for that driver. It never migrates, constructs models, or writes (its
reader: `SKILL.md`'s engine section).

- Offsetless dates and datetimes are read as historical local time and converted to UTC;
  an explicit offset is honored. `--since` is inclusive (`created_at >= since`).
- The pure summary sorts by role, model, and task; counts each request, repairs included,
  across all six outcomes, with status counts in an outcome cell when present
  (`4 (400: 2, 503: 1)`); sums reported tokens and USD cost (unknown throughout a group is
  `—`, a recorded zero is zero, mixed known and unknown costs sum the known ones); and uses
  ceiling-ranked 50th/95th percentile latency.
- Only accounting reaches stdout: no prompt, learner text, or key. An empty filtered log
  prints `No model calls recorded.` and returns 0, a table returns 0, invalid UUID or date
  arguments return 2, and a missing or unmigrated database returns 1 with a
  `just backend db-upgrade` instruction.
