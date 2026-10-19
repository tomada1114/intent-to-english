---
name: running-the-app
description: >
  Covers observing the real app when no test shows the behavior: starting uvicorn with
  the create_app factory on a free port, or an own `just dev` pair (API and Vite) on two
  free ports with a scratch SQLite file, capturing curl output as evidence, and stopping
  it before the turn ends, without touching the developer's own `just dev` (ports 8000
  and 5173). Use when asked to run the app or the screen, try an endpoint by hand, check
  a change against a live server, or put request output in a pull request.
---

# Running the App

**Owns:** how an agent observes the running application — which evidence first, how to
start and stop a server of its own, and what the evidence looks like in a pull request.
**Does not own:** writing a route or its `TestClient` test (`building-api-routes`); the
pull request's mechanics (`create-pr`). The rule this skill carries out is AGENTS.md's "Quick
Reference", under "Long-running — human-run".

## Evidence, cheapest first

Stop at the first tier that shows what the change does.

1. **A test.** `TestClient` exercises the same code as a live process and the result
   outlives the turn. If a lasting assertion would show it, write one.
2. **A server of your own, then `curl`,** for what only a listening process shows: the
   served headers, the startup path through uvicorn's `--factory` call of
   `create_app`, the environment as a user meets it, a request from outside the
   process.
3. **`just e2e`,** for the screen against a real API: Chromium on the built screen, on
   its own free ports and a throwaway database ([references/e2e.md](references/e2e.md)).
4. **A `just dev` pair of your own,** for the rest that needs the screen's origin: Vite's
   dev server and proxy, `just dev` itself.

## The developer's server is not yours

- The developer's `just dev` (API on 8000, Vite on 5173) is theirs: never start, stop,
  or restart it, and never bind 8000 or 5173 — uvicorn's and the recipes' defaults, so
  always pass `--port`, and an own pair always sets `INTENT_TO_ENGLISH_API_PORT` and `VITE_PORT`.
- **Let the OS pick the port** (bind to port 0), then check that nothing accepts
  connections on it. If something does, or the check itself fails, abort: start
  nothing and send nothing. A sibling worktree's server may hold any port.
- **Send requests only to a server you just started** from this checkout, in this
  command, after its log says it is running on that port. Never reuse a server that is
  already answering, even one that looks like this app.
- **Stop only the process you launched** — the `uv` whose pid `$!` gave you, which
  passes the signal on to the server it runs — before the turn ends, including when a
  step failed. Never by name (`pkill -f uvicorn`, `killall python`), and never "whatever
  listens on the port": if a listener remains after your own process has stopped,
  report it and stop; do not kill it.
- **Loopback only.** uvicorn binds `127.0.0.1` (`just backend dev` passes it); never
  pass `--host 0.0.0.0`. Vite binds `localhost`, maybe `::1` alone: check both.

## Set every application setting explicitly

The shell and module-relative `backend/.env` may hold real data or a provider key.
Clear inherited application variables and the unprefixed `OPENROUTER_API_KEY` alias,
including case variants. Set every field explicitly: database URL, CORS origins,
log level/format, key, mode and both model ids. An empty value wins over the file;
empty ids select the defaults. Force `fixed` mode and an empty key for observations.

```bash
env $(env | awk -F= 'toupper($1) ~ /^INTENT_TO_ENGLISH_/ || toupper($1) == "OPENROUTER_API_KEY" {print "-u " $1}') INTENT_TO_ENGLISH_DATABASE_URL="$db" INTENT_TO_ENGLISH_CORS_ORIGINS= INTENT_TO_ENGLISH_LOG_LEVEL= INTENT_TO_ENGLISH_LOG_FORMAT= OPENROUTER_API_KEY= INTENT_TO_ENGLISH_MODEL_MODE=fixed INTENT_TO_ENGLISH_COACH_MODEL= INTENT_TO_ENGLISH_PARTNER_MODEL= uv --no-cache run --locked uvicorn intent_to_english.api.app:create_app --factory --no-access-log --port "$port"
```

Set `INTENT_TO_ENGLISH_DATABASE_URL=` for the in-memory store, or point it at a file in a
directory from `mktemp -d`, outside the checkout
(`db="sqlite+aiosqlite:///$(mktemp -d)/sessions.db"`); a relative path would create the
file in the working directory. Never point it at `backend/var/dev.db`, the developer's
database. The app never creates its schema, so migrate the scratch file first, in the
same shell command (**BACKGROUND:** `persisting-data`):

```bash
env $(env | awk -F= 'toupper($1) ~ /^INTENT_TO_ENGLISH_/ || toupper($1) == "OPENROUTER_API_KEY" {print "-u " $1}') INTENT_TO_ENGLISH_DATABASE_URL="$db" INTENT_TO_ENGLISH_CORS_ORIGINS= INTENT_TO_ENGLISH_LOG_LEVEL= INTENT_TO_ENGLISH_LOG_FORMAT= OPENROUTER_API_KEY= INTENT_TO_ENGLISH_MODEL_MODE=fixed INTENT_TO_ENGLISH_COACH_MODEL= INTENT_TO_ENGLISH_PARTNER_MODEL= uv --no-cache run --locked alembic -c backend/alembic.ini upgrade head
```

Set the variable in the same shell command that starts the server: an agent's shell
does not keep an exported variable from one call to the next, so a server started
later would silently use the developer's environment instead.

## Running a server of your own

Read `X-Request-ID` from the response (`curl -i`) and find that same ID in
application logs and sanitized server diagnostics; Problem Details carries it as
`request_id`, including 500s. The HTTP diagnostic boundary retains frames, exception
classification and identity while excluding original messages, chains, notes and
exception-group members from application and Uvicorn output. A failure after headers
have started terminates the body without sending another response. The real-process
regression in `backend/tests/api/test_server_logging.py` captures all stdout/stderr in
both application formats and verifies owned-process cleanup on success and failure.
Set `INTENT_TO_ENGLISH_LOG_LEVEL=` and `INTENT_TO_ENGLISH_LOG_FORMAT=` explicitly in an isolated
server's environment to retain the sample defaults rather than a developer's
dotenv logging settings. Pass `--no-access-log` to uvicorn to keep one access line.

Run the server's whole life as one foreground shell command — pick a port, check it,
start, wait, request, stop, check again. The `trap` stops the server even when the
command is interrupted part way; do not use `set -e`, so a failed `curl` still reaches
the stop. The script runs under bash and zsh (zsh reserves `status`, hence `rc`).

```bash
probe='import socket, sys; s = socket.socket(); s.settimeout(1); sys.exit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)'
ready='import pathlib, sys, time
log, line = pathlib.Path(sys.argv[1]), f"running on http://127.0.0.1:{sys.argv[2]} "
for _ in range(300):
    text = log.read_text()
    if line in text:
        sys.exit(0)
    if "ERROR" in text:
        sys.exit(1)
    time.sleep(0.1)
sys.exit(1)'
port=$(uv --no-cache run --locked python -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')
log=$(mktemp)
uv --no-cache run --locked python -c "$probe" "$port"; rc=$?
if [ "$rc" = 1 ]; then
  env $(env | awk -F= 'toupper($1) ~ /^INTENT_TO_ENGLISH_/ || toupper($1) == "OPENROUTER_API_KEY" {print "-u " $1}') INTENT_TO_ENGLISH_DATABASE_URL= INTENT_TO_ENGLISH_CORS_ORIGINS= INTENT_TO_ENGLISH_LOG_LEVEL= INTENT_TO_ENGLISH_LOG_FORMAT= OPENROUTER_API_KEY= INTENT_TO_ENGLISH_MODEL_MODE=fixed INTENT_TO_ENGLISH_COACH_MODEL= INTENT_TO_ENGLISH_PARTNER_MODEL= uv --no-cache run --locked uvicorn intent_to_english.api.app:create_app --factory --no-access-log --port "$port" >"$log" 2>&1 &
  pid=$!
  trap 'kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null' EXIT
  if uv --no-cache run --locked python -c "$ready" "$log" "$port" && kill -0 "$pid" 2>/dev/null; then
    curl -sS -i "http://127.0.0.1:$port/healthz"; echo
    curl -sS -i -X POST "http://127.0.0.1:$port/api/sessions"; echo
  else
    echo "the server did not start; nothing was sent"
  fi
  kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null; trap - EXIT
  uv --no-cache run --locked python -c "$probe" "$port"; rc=$?
  case "$rc" in
    1) echo "nothing listening on $port" ;;
    0) echo "something still listens on $port: report it, do not kill it" ;;
    *) echo "could not check port $port (status $rc)" ;;
  esac
  grep -E 'Uvicorn running|Finished server process' "$log"
else
  echo "port $port is taken or could not be checked (status $rc): nothing started"
fi
```

- **The port check** is a Python probe run through `uv`, which the app needs anyway,
  rather than `lsof` or `ss`, which a host may lack. Exit 1 means nothing accepts
  connections; 0 means something does; anything else means the check failed, and only
  exit 1 counts as proof. `lsof` (macOS) or `ss -ltnp` (Linux), where installed, can
  name an unexpected listener for the report — never to pick something to kill.
- **Waiting** reads the server's own log for uvicorn's "running on" line, so no request
  goes out before your server holds the port; it gives up after 30 seconds or on an
  `ERROR` line, such as a failed bind.
- **Stopping.** `$!` is the pid of `uv`, not of the Python process that listens; `uv`
  passes the `SIGTERM` on and uvicorn shuts down cleanly. Observed with this script,
  2026-10-06, including the `trap` stopping a server when the command exited early.
- **A host that runs long commands in the background** follows the same steps; the stop
  and the final check still happen before the turn ends.

The output under bash and zsh, observed 2026-10-19 (the port, the timestamps, and the
generated ids vary):

```console
HTTP/1.1 200 OK
date: Mon, 19 Oct 2026 18:47:29 GMT
server: uvicorn
content-length: 15
content-type: application/json
x-request-id: 01a1557d-7b53-70e2-811b-f2d491febf85

{"status":"ok"}
HTTP/1.1 201 Created
date: Mon, 19 Oct 2026 18:47:29 GMT
server: uvicorn
content-length: 283
content-type: application/json
x-request-id: 01a1557d-7b60-7458-9c09-e4d59fe9f679

{"id":"01a1557d-7b74-7069-bd73-f948d7c0f26c","status":"in_progress","stage":"opening","version":0,"turn_index":1,"finished_replies":0,"started_at":"2026-10-19T18:47:29.396702Z","ended_at":null,"allowed_actions":["open","ask","end"],"entries":[],"last_submission":null,"wrap_up":null}
nothing listening on 61901
INFO:     Uvicorn running on http://127.0.0.1:61901 (Press CTRL+C to quit)
INFO:     Finished server process [8473]
```

The server command is the one `just backend dev` serves with, minus `--reload`, plus `--port`; unlike `just dev`, it migrates nothing and,
with `INTENT_TO_ENGLISH_DATABASE_URL` explicitly empty, keeps sessions in memory even when `backend/.env` sets a URL.
That store starts empty on every start; create what a request needs with a `POST` first.

## Running a `just dev` pair of your own

`INTENT_TO_ENGLISH_API_PORT` moves the API and Vite's proxy target, `VITE_PORT` moves Vite
(`strictPort`: a taken port fails); neither is a setting. Everything above holds, plus:
two free ports checked on both `127.0.0.1` and `::1`; a scratch database file, never an
empty URL, which the recipes turn into the developer's `backend/var/dev.db`; requests
only once both servers log ready; and a stop of only the outer `just` you launched. The
rules in full, the script, and its output: [references/own-dev-pair.md](references/own-dev-pair.md).

## The evidence a pull request carries

Under the pull request's Test Plan, for each behavior observed rather than asserted:

- the exact command or request, as run;
- the lines of output that show the behavior — the status line, the body, the log
  line — not the whole log;
- where it ran: your own uvicorn from this checkout, and the database (in-memory or a
  scratch file).

Redact before pasting: a home directory becomes `~/…`, a temporary path a placeholder,
and no credential or environment value appears.

## Before the turn ends

- [ ] The final port check printed "nothing listening" for every port you used, or you
      reported the listener that remained, untouched.
- [ ] The developer's servers, if any were running, were never touched, and nothing
      was sent to 8000 or 5173.
- [ ] `git status --porcelain` shows only the change: logs and databases live outside
      the checkout.
