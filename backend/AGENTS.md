# Backend Guide

The FastAPI app: a uv workspace member built with
[hatchling](https://hatch.pypa.io/), in a strict `src/` layout with strict type
checking and linting. A framework-free core serves the HTTP API, the read-only
call-log command, and the human-run evaluation command. This file adds the backend's
own rules to the root `AGENTS.md`, which
still applies in full — its approval rules and gates above all.

## Validating a change

Every command here runs from the repository root. Run the narrowest check that
can fail while iterating, then `just verify` before a completion claim.

| What you changed | The narrowest check that can fail |
|---|---|
| A module under `backend/src/intent_to_english/<layer>/` | `uv run --locked --directory backend pytest tests/<layer>/` |
| `settings.py` or `composition.py` | `uv run --locked --directory backend pytest tests/test_settings.py tests/test_composition.py` |
| A repository adapter | `uv run --locked --directory backend pytest tests/adapters/test_session_repository_contract.py` |
| A table in `adapters/sql/tables.py`, or a revision under `migrations/` | `uv run --locked --directory backend pytest tests/adapters/`, then `just backend lint` (`persisting-data`) |
| One backend test | `uv run --locked --directory backend pytest tests/<path>.py::test_<name>` |
| A backend Python file's types | `uv run --locked --directory backend mypy` |
| A backend Python file's lint, or `backend/pyproject.toml`'s ruff, mypy, pytest, or coverage settings | `just backend lint`, then `just backend test` (`changing-gates`) |
| The whole backend, with its 80% branch-coverage floor | `just backend test` |

`just backend dev` is the developer's server, human-run, and migrates the
developer's database (`backend/var/dev.db` by default) before it starts: the root
`AGENTS.md`'s Quick Reference says what to run instead (`running-the-app`).

## Architecture

```
backend/
├── pyproject.toml   # The app's dependencies; its ruff (extending the root's), banned-api, mypy, pytest, and coverage settings
├── justfile         # A just module of the root justfile: `just backend <recipe>`
├── alembic.ini      # Alembic's settings; no database URL (INTENT_TO_ENGLISH_DATABASE_URL supplies it)
├── migrations/      # Alembic: env.py, the revision template, and versions/ (the schema's history)
├── var/             # Gitignored: the development database, dev.db
├── src/intent_to_english/
│   ├── core/            # Framework-free: domain model, ports (Protocols), services, errors
│   ├── adapters/        # Memory/SQL repositories and fixed/OpenRouter model roles
│   ├── api/             # FastAPI: create_app(settings) factory, routers (api/routers/), Pydantic schemas
│   ├── evaluation/      # Strict cases, code expectations, task runner, reports and the billed command
│   ├── call_log.py      # Read-only call-log CLI: SQL records to pure core summaries
│   ├── settings.py      # Prefixed settings and the unprefixed OPENROUTER_API_KEY secret alias
│   └── composition.py   # Composition root: wires adapters into services for the API
└── tests/           # The app's suite, mirroring src/intent_to_english/ (`placing-tests`)
```

- Dependencies point inward: `api/` calls `core/` services and gets
  them only from `composition.build_container`; `adapters/` implement
  `core/ports.py`; `core/` imports nothing outside the stdlib and itself.
  Ruff's `TID251` banned-api rule and `tests/core/test_imports.py` fail the
  build otherwise (`designing-core-logic`).
- The Container owns process-lifetime disposal callbacks through `ResourceClosers`.
  They run on the resource's event loop in a separate Task/Context and never suppress
  body errors. Scope-bound managers stay with their acquiring caller
  (`designing-core-logic`).
- The container supplies the ConversationService. Its SQL session repository owns
  one lazy engine and disposal callback; without a database URL the store is in
  memory. In auto mode with a key both model roles use OpenRouter over one owned client;
  otherwise both use fixed responses. Meta reads that selection from the container.
- `Container.models` holds the same two model ports the conversation service uses.
  Evaluation calls those ports through the shared task runner, with memory storage
  and the same owned cleanup. It neither opens nor writes an application database.
- `call_log.py` invokes a SQL-only reader and the pure `core/call_log.py` summary.
  The reader owns a separate read-only engine and disposes it on the same loop;
  this entry point constructs no service or model (`persisting-data`).
- The OpenRouter adapters have three Partner and seven Coach task agents, all retry-free,
  over one explicitly owned client. Native JSON schemas keep feedback a top-level object. Model
  SDK imports stay under `adapters/models/`; the suite blocks real model requests.
- Domain errors derive from `core.errors.AppError`; the API maps them in one
  place (`api/app.py`), per `designing-errors`.
- Submission attempts carry a client correlation UUID separately from internal UUIDv7
  record IDs. Admission and cancellation serialize on the session; retained cancellation
  identities prevent an early cancel from being lost or a delayed one from affecting
  a same-version replacement.
- The schema belongs to the migrations: the app never creates or alters a table,
  and `just backend db-upgrade` (which `just backend dev` runs first) applies them
  (`persisting-data`).
- The app's own design — the stage machine, the two model roles and their ports, the
  five tables, the API, and the decisions behind them — is
  `docs/architecture/overview.md`; its "Shape" table says which module each new piece
  goes in.
- The model roles are ports in `core/`; `pydantic_ai` and `openai` are imported only by
  the model adapters, and no test makes a live model call (`calling-models`).

## Skills for the backend

The root `AGENTS.md`'s Skills table lists every skill; these are the backend's:

- `designing-core-logic` — a use case, domain rule, port, adapter, or
  `INTENT_TO_ENGLISH_*` setting, or wiring the composition root.
- `building-api-routes` — an HTTP route, request or response model, or API
  dependency, and its TestClient tests.
- `designing-errors` — a failure mode, or the HTTP status a domain error becomes.
- `calling-models` — a model task, a prompt, an output check, the model adapters,
  their settings, or the evaluation harness.
- `persisting-data` — a table, a SQL statement, the engine, or an Alembic
  revision.
- `placing-tests` — where a backend test or fixture goes, running one test, or
  a coverage run below the floor.
