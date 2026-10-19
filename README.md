# Intent to English

[![CI](https://github.com/tomada1114/intent-to-english/actions/workflows/ci.yml/badge.svg)](https://github.com/tomada1114/intent-to-english/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/tomada1114/intent-to-english/blob/main/LICENSE)

Practice English small talk: say it in Japanese first, build the English yourself, then rebuild it from fill-in feedback.

## Quickstart

Prerequisites (CONTRIBUTING.md's "Prerequisites" has the links and the details):

- [uv](https://docs.astral.sh/uv/getting-started/installation/) 0.11.8 or later; it
  installs Python 3.14 when none is found
- [Just](https://just.systems/man/en/installation.html) 1.42.3 or later
- [Node.js 24](https://nodejs.org/en/download) (`.node-version`)
- [pnpm](https://pnpm.io/installation), through `corepack enable` (Corepack ships
  with Node.js 24); `package.json` pins the version
- no Docker

Then:

1. Install the dependencies and the git hooks, then start the app:

   ```bash
   just install   # the Python and JavaScript dependencies, and the git hooks
   just dev       # migrate backend/var/dev.db, then serve the screen and the API, reloading on source changes (Ctrl-C stops both)
   ```

2. Open <http://localhost:5173>: the to-do screen. The API answers on
   <http://127.0.0.1:8000>, with `/healthz` and the interactive docs at `/docs`.

`just dev` is the developer's own server and runs until stopped; an agent runs
its own pair on free ports instead (the `running-the-app` skill). Without Just,
CONTRIBUTING.md's "Without Just" note says where each recipe's commands are.

The request flow under `just dev`:

```text
browser
  -> Vite dev server, http://localhost:5173 (VITE_PORT); proxies /api and /healthz
  -> FastAPI router, http://127.0.0.1:8000 (INTENT_TO_ENGLISH_API_PORT)
  -> service in backend/src/intent_to_english/core/
  -> repository port
  -> SQL adapter (SQLAlchemy asyncio Core)
  -> SQLite file, backend/var/dev.db
```

With the server running, from another terminal:

```bash
curl http://127.0.0.1:8000/healthz   # {"status":"ok"}
curl -X POST http://127.0.0.1:8000/api/todos \
  -H 'Content-Type: application/json' -d '{"title": "buy milk"}'
curl http://127.0.0.1:8000/api/todos
```

The interactive API docs are at <http://127.0.0.1:8000/docs>.

| HTTP | Result |
|---|---|
| `GET /healthz` | 200 `{"status": "ok"}` |
| `POST /api/todos` `{"title": "..."}` | 201 with the new to-do, `{"id": "<uuid>", "title": "...", "completed": false, "created_at": "..."}` |
| `GET /api/todos?cursor=<cursor>&limit=<n>` | 200 with one page, oldest first: `{"items": [<to-do>, ...], "next_cursor": "<cursor>" \| null}` |
| `POST /api/todos/{id}/complete` | 200 with the completed to-do; 404 `todo_not_found` when unknown |
| `DELETE /api/todos/{id}` | 204; 404 `todo_not_found` when unknown |
| `POST /api/sessions` | 201 with the new session at `opening`, version 0; no model call |
| `GET /api/sessions?cursor=<cursor>&limit=<n>` | 200 with one page, newest first; default 20, maximum 100 |
| `GET /api/sessions/{id}` | 200 with the complete session view; 404 `session_not_found` when unknown |
| `POST /api/sessions/{id}/actions` | 200 with the new view; a body discriminated by `action`, with `version` and that action's fields |
| `POST /api/sessions/{id}/cancel` `{"version": 0}` | 204 whether or not that version has pending work; 404 for an unknown session; a missing version is 422 |
| `GET /api/meta` | 200 with the container's selected `model_mode`; currently `{"model_mode": "fixed"}` |

A to-do's `id` is a UUID (version 7) the application generates, so ids sort in
creation order. `GET /api/todos` returns at most `limit` to-dos (default 50, at most
100) and pages by cursor: pass a page's `next_cursor` back as `cursor` to fetch
the next page; `next_cursor` is `null` on the last one. `GET /api/todos` with no
parameters is the first page, `{"items": [], "next_cursor": null}` when empty.

A session view includes its stage, version, allowed actions, ordered timeline,
start/end times, recoverable input and wrap-up. Action bodies use flat input
fields: `{"action": "intent", "version": 1, "text": "..."}`, or `gap` and
`partial_english` for a hint, `reading` for a reading choice, and `mode` for a
restatement. Actions such as `open`, `end` and `wrap_up` need only action/version.
`end` returns immediately without calling a model. An ended session with feedback
has `wrap_up: null` and allows `wrap_up`; that separate action creates the summary.
An empty `{"items": []}` means no summary is needed. Cancellation affects only
pending work at the supplied version and does not advance the session.

Every error uses RFC 9457 `application/problem+json`: `type: "about:blank"`,
`title` (the status phrase), numeric `status`, client-safe `detail`, and a stable
`code`. Clients branch on `code` and ignore unknown extensions.

An unknown to-do is 404 `todo_not_found`. An invalid title, cursor, or page limit
is 422 `invalid_todo`, `invalid_cursor`, or `invalid_page_limit`. An unmapped
domain error falls back to 400 with its own code (`AppError` uses `app_error`).
Session conflicts are 409 `stale_session`, `action_in_progress`, `action_not_allowed`,
`session_ended` or `action_cancelled`. Core text limits return 422 `invalid_input`.
Model failures return 504 `model_timeout`, 503 `model_rate_limited`, or 502
`model_unavailable` / `model_output_invalid`; failed input stays recoverable in the view.
A request that does not parse is 422 `request_invalid`, detail `Request validation
failed`, and `errors: [{"loc": [...], "message": "...", "type": "..."}]`;
raw input and server context are omitted. Domain errors have no `errors`.

Unknown routes are 404 `not_found`; unsupported methods are 405
`method_not_allowed` with the `Allow` header. Other HTTP exceptions use
`http_error` and keep protocol headers; body type, length, and encoding describe
the new representation. Unregistered codes use title `Unknown Status`,
and statuses forbidding a body remain empty.
Rejected CORS preflights are 400 `http_error` Problem Details and retain the
CORS policy headers; allowed preflights remain 200 with body `OK`.
Unexpected exceptions return 500 `internal_error` with detail `An unexpected
error occurred`, while the traceback is logged on `intent_to_english.api.errors`.

## Configuration

Settings read `INTENT_TO_ENGLISH_` variables and the unprefixed `OPENROUTER_API_KEY`
alias, then optional UTF-8
`backend/.env`. The file's path is resolved from the module, so changing the
working directory does not change which file is read. A missing file is fine.

To start with a local copy (gitignored):

```bash
cp backend/.env.example backend/.env
```

The sample lists every setting with an empty value and its default. Environment
values take precedence over the file, including an explicit empty value: blanks
mean unset/default. Whitespace-only model ids fail at startup, naming the variable.
Quoted file values are supported. Unknown `INTENT_TO_ENGLISH_` keys in
the file fail at startup (Pydantic names the normalized field); unrelated,
unprefixed keys other than the declared provider-key alias are ignored.

| Variable | Default | Effect |
|---|---|---|
| `INTENT_TO_ENGLISH_LOG_LEVEL` | `INFO` | Case-insensitive `DEBUG`, `INFO`, `WARNING`, or `ERROR`; blank keeps the default. |
| `INTENT_TO_ENGLISH_LOG_FORMAT` | `text` | `text` or one JSON object per line with timestamp, level, logger, message, request ID, access fields, and exception type/traceback when present; blank keeps text. |
| `INTENT_TO_ENGLISH_CORS_ORIGINS` | empty (CORS disabled) | Comma-separated HTTP(S) origins, e.g. `http://localhost:5173,https://app.example.com`. Spaces and empty items are removed, hosts use lowercase/punycode, default ports are removed, and duplicates kept once. Paths, queries, fragments, user info, invalid ports, trailing slashes, wildcards, and origins without an HTTP(S) scheme are rejected at startup. JSON requests from listed origins are allowed without credentials. |
| `INTENT_TO_ENGLISH_DATABASE_URL` | unset (`just dev`: `sqlite+aiosqlite:///./var/dev.db`) | Unset (or empty) keeps to-dos and sessions in memory, so they vanish when the process exits. `sqlite+aiosqlite:///<path>` stores them in a SQLite file at `<path>`, relative to the working directory (an absolute path adds a fourth slash: `sqlite+aiosqlite:////var/lib/todos.db`). `postgresql+asyncpg://<user>:<password>@<host>/<database>` names a PostgreSQL database; include the optional `postgres` extra in workspace commands (`uv run --locked --directory backend --extra postgres ...`) or install the built app with that extra. Anything else is rejected at startup, naming the fix: a URL without the async driver (`sqlite:` or `postgresql:` alone), an in-memory SQLite target (including `:memory:` with options and native URI memory mode), an empty target, and a directory target ending in `/`, even when query options follow. File options are preserved; migrations and the app use separate engine/process lifetimes, so in-memory SQL cannot retain the separately migrated schema. |
| `OPENROUTER_API_KEY` | unset | Unprefixed secret; unset or whitespace-only means no key. It is omitted from settings repr and never returned by the API. |
| `INTENT_TO_ENGLISH_MODEL_MODE` | `auto` | `auto` or `fixed`; empty keeps auto. Composition currently uses fixed responses in both modes, including when a key is set. |
| `INTENT_TO_ENGLISH_COACH_MODEL` | `anthropic/claude-sonnet-5.5` | The configured Coach model id; empty keeps the default, whitespace-only is rejected. |
| `INTENT_TO_ENGLISH_PARTNER_MODEL` | `anthropic/claude-haiku-5.5` | The configured Partner model id; empty keeps the default, whitespace-only is rejected. |

Both roles currently use the offline adapters. The live composition branch is a
separate implementation; `GET /api/meta` reports the selected mode. Every browser-test
process explicitly selects fixed mode with an empty key and the default model ids,
and removes inherited application settings and provider-key aliases first.

The development servers read a second set of variables from the process
environment. They are not `Settings` fields, so they never go in `backend/.env`,
which rejects unknown `INTENT_TO_ENGLISH_` keys at startup:

| Variable | Default | Read by | Effect |
|---|---|---|---|
| `INTENT_TO_ENGLISH_API_PORT` | `8000` | `just dev`, `just backend dev`, and the Vite proxy | The API's port, and the port Vite proxies `/api` and `/healthz` to. |
| `VITE_PORT` | `5173` | `just dev`, `just frontend dev` | The screen's port; Vite fails rather than moving to another port when it is taken. |
| `E2E_API_PORT`, `E2E_WEB_PORT` | a free port each | `just e2e` | The browser test's own API and screen ports; never 8000 or 5173. |

The database recipes automatically select the `postgres` extra for PostgreSQL
URLs and keep the default environment for SQLite.

Every HTTP response carries `X-Request-ID`. Send 1–128 ASCII letters, digits,
dots, underscores or hyphens to retain your own ID; other values receive a UUIDv7.
Problem Details includes the same `request_id`, including 500 and CORS failures.
Application logs carry that ID; the access record contains method, path, status,
and duration, without query strings or request bodies. Paths escape control
characters and Unicode to preserve one physical access line. `just backend dev` disables
uvicorn's duplicate access log.

The database must be migrated before the API uses it: the app never creates or
alters a table. `just backend db-upgrade` migrates the database
the environment or `backend/.env` selects to the newest revision, and `just dev`
runs it first (see AGENTS.md's Quick Reference for `db-revision`, which writes
a new one).
The database recipes resolve the URL once using `Settings` and give that same
URL to both migration and server. If the result is unset or empty, they use
`sqlite+aiosqlite:///./var/dev.db`, including when `.env` is a copy of the sample.
A direct API factory or uvicorn run with no resolved URL uses the in-memory store.

> [!NOTE]
> `just dev` keeps to-dos in `backend/var/dev.db` (gitignored) unless
> `INTENT_TO_ENGLISH_DATABASE_URL` in the environment or `backend/.env` selects another file,
> so they survive the restart on every source change. A direct server run with
> `INTENT_TO_ENGLISH_DATABASE_URL=` overrides the file and forgets its to-dos when it stops.

> [!WARNING]
> A database file the app's earlier stdlib-`sqlite3` store wrote is not
> migrated: its table predates the migrations, so `just backend db-upgrade`
> fails on it. Delete the file, or point `INTENT_TO_ENGLISH_DATABASE_URL` at a new one.
> A database nobody migrated answers every to-do request with a 500.

## Architecture

```text
backend/    # The FastAPI app (uv workspace member): core, adapters, API, settings, Alembic migrations
frontend/   # The React app (Vite, TypeScript; pnpm workspace member) and its typed API client
e2e/        # The Playwright test from the screen to the database (just e2e)
```

`backend/AGENTS.md` holds the backend's architecture: the core imports neither
the API nor any framework or driver, the API only translates between HTTP and
the core, and `composition.py` is the one place adapters are wired in.
`docs/architecture/overview.md` holds the app's own design: the stage machine, the
Partner and Coach model roles behind ports, the four tables, the API, and the
decisions behind them. `frontend/AGENTS.md` holds the frontend's toolchain. The schema lives in
`backend/src/intent_to_english/adapters/sql/tables.py` and its history in Alembic revisions
under `backend/migrations/` (the `persisting-data` skill).

## Evaluation

The owner runs `just backend eval` to evaluate the configured models; it bills.
The command currently refuses in every mode until the live composition branch is
implemented. It refuses before any call or write when the selected mode is fixed,
when either target report already exists, or when the summary markers are invalid.
To verify refusal without billing, explicitly override both variables:

```bash
INTENT_TO_ENGLISH_MODEL_MODE=fixed OPENROUTER_API_KEY= just backend eval
```

The 16 TOML cases in `backend/evals/cases/` contain `task`, `source`, `[request]`,
optional `[context]` notes and `[[expect]]` values from a closed vocabulary. Required
nullable fields use `{ none = true }`; unknown or missing request fields are errors.
Context notes never enter a model request. Tests run the complete set on fixed ports,
render reports and update a temporary README without requiring a quality pass rate.

Reports are new `.md` and `.json` files under `backend/evals/reports/`, named
`<UTC-date>_<coach-id>_<partner-id>` with `/` replaced by `-`. They record the source
commit and dirty state, first/final check and expectation rates, outcomes, reported
cost in credits and nearest-rank p50/p95 latency per task. Missing cost stays empty.
Commit both reports after an owner-run evaluation; the summary below links the latest.

<!-- eval-summary:start -->
No evaluation run yet.
<!-- eval-summary:end -->

## Development

See [CONTRIBUTING.md](https://github.com/tomada1114/intent-to-english/blob/main/CONTRIBUTING.md)
for the prerequisites, the workflow, and the pull request process; AGENTS.md's
Quick Reference indexes every recipe.

```bash
just install   # dependencies + git hooks, then checks the hooks are in place
just dev       # migrate backend/var/dev.db, then the screen on http://localhost:5173 and the API on http://127.0.0.1:8000
just verify    # the non-mutating gate a pull request must pass
```

Each area has its own recipes: `just backend <recipe>` (for example
`just backend test`, `just backend db-upgrade`) and `just frontend <recipe>`
(for example `just frontend test`); `just contract` regenerates the typed API
client from the backend's OpenAPI contract, and `just e2e` runs the browser test.

`just dev` runs `just backend dev` (uvicorn with auto-reload on
http://127.0.0.1:8000) and `just frontend dev` (Vite on http://localhost:5173)
together in one terminal. Open http://localhost:5173: Vite proxies `/api` and
`/healthz` to the API, so the browser sees one origin and needs no CORS.
Ctrl-C stops both; when either one exits, `just dev` stops the other and exits
with that one's status. `INTENT_TO_ENGLISH_API_PORT` and `VITE_PORT` (the development-server
table under "Configuration") move the ports when the defaults are taken:

```bash
INTENT_TO_ENGLISH_API_PORT=8001 VITE_PORT=5174 just dev
```

The git hooks are not optional: they carry the secret gate that refuses a
commit staging a secret, for every author. `just install` installs the
dependencies and the hooks `.pre-commit-config.yaml`'s
`default_install_hook_types` lists (`pre-commit` and `pre-merge-commit`), then
fails if any of them is missing. `ALLOW_MISSING_GIT_HOOKS=1 just install` still tries
to install them but only warns when that fails (`CI=true` does the same).
Outside a Git repository — a "Use this template" copy before `git init` — it
skips the hooks. A failed `pnpm install` still lets the hooks install, then
fails the run. Without Just, run `uv sync --all-groups --locked`,
`pnpm install --frozen-lockfile`, and then
`uv run --locked pre-commit install --install-hooks`.

## License

[MIT](https://github.com/tomada1114/intent-to-english/blob/main/LICENSE)
