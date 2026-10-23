# The OpenRouter adapter

Read when writing or changing `adapters/models/openrouter.py`, its tests, or a provider
beside it. `SKILL.md` holds the port contract and the service's sequence these rules
serve. The reasons and their sources are `docs/architecture/overview.md`'s § Decisions ›
"Models are called through PydanticAI, inside the model adapters" and "Keys, models, and
the mode"; the external facts below that the overview does not state carry their own.

## Building it

- `composition.py` builds the adapter only when it chooses OpenRouter, passing the key
  from `Settings`, one `OpenRouterRole` per role (its model id and optional reasoning
  effort), and a monotonic clock for latency. The key is
  unwrapped from its secret type here and nowhere else.
- `build_openrouter_models` builds one `openai.AsyncOpenAI`, with `base_url`
  `https://openrouter.ai/api/v1`, `api_key` the string unwrapped by composition, `max_retries=0`, and the app's
  name as `X-OpenRouter-Title` in `default_headers`. It hands that client to
  `OpenRouterProvider(openai_client=...)` and gives the provider nothing else.
- Everything goes on the client because the provider ignores its own `api_key`,
  `app_url`, and `app_title` once it is given a client, and on that path it still reads
  `OPENROUTER_API_KEY`, `OPENROUTER_APP_URL`, and `OPENROUTER_APP_TITLE` from the
  environment without using them. So no environment value reaches a request
  (`providers/openrouter.py` at https://github.com/pydantic/pydantic-ai/tree/v2.55.0,
  checked 2026-10-18).
- `app_title` is explicit, supplied with the API's `APP_TITLE` (`Intent to English`).
  OpenRouter documents `X-OpenRouter-Title` as the current name (`X-Title` remains
  compatible); a title alone creates no public app page. No app URL is configured,
  so the builder sends no invented `HTTP-Referer`
  (https://openrouter.ai/docs/app-attribution, checked 2026-10-18).
- Each role gets an `OpenRouterModel` for its model id over that one provider. Each task
  gets one `Agent`, built once, with `output_type=NativeOutput(<the task's schema
  model>)`, `retries=0`, and no tools. At the resolved 2.55.0 tag, the explicit
  per-agent switch is `agent.instrument = False`, which overrides a global
  `Agent.instrument_all()` default (`agent/__init__.py` at the tag above).
- The client holds connections, so the builder registers `client.close` with
  `ResourceClosers`. **REQUIRED:** `designing-core-logic` (its adding-a-port reference,
  "An adapter that holds a resource").
- A role's reasoning effort is sent only when its setting is set: the role's calls then
  carry `OpenRouterModelSettings(openrouter_reasoning={"effort": ...})`, which PydanticAI
  sends as OpenRouter's `reasoning` object. Unset sends no `reasoning` key, so the
  provider's default thinking applies. Instrumentation stays off.

## One call

1. `prompts.py` renders the request (and its repair, when there is one) into the
   instructions and messages. The adapter passes them through unchanged.
2. The run gets `ModelSettings` with `timeout` 60. The SDK's timeout bounds the client's
   waits rather than the whole call (httpx times out on inactivity:
   https://github.com/encode/httpx/blob/master/docs/advanced/timeouts.md, checked
   2026-10-17), so the adapter also runs the call inside a 60 s `asyncio.timeout`.
3. The run happens inside `capture_run_messages()`, so the `ModelResponse` stays
   readable when parsing fails.
4. Usage is read from that response: tokens from `usage`, cost from
   `provider_details["cost"]` (none when absent), the model from the setting, the
   provider `openrouter`, and latency from the injected clock around the run.
5. What parses is converted by `schemas.py` into the core output value and returned
   with that usage.

## Mapping failures

PydanticAI turns an `openai.APIStatusError` with a status of 400 or more into
`ModelHTTPError` (carrying `status_code`), and an `openai.APIConnectionError` into
`ModelAPIError`, chaining the original with `from`; an error OpenRouter returns inside a
200 body with a numeric error code becomes `ModelHTTPError`; null choices without an
error envelope become `ModelAPIError`. An invalid envelope missing its required code
is a schema failure instead. `openai.APITimeoutError` is a
subclass of `APIConnectionError`, so a client timeout arrives as a plain
`ModelAPIError` whose `__cause__` is the timeout. A schema that does not validate ends
the run with `UnexpectedModelBehavior` when output retries are 0
(`models/openai.py`'s `_map_api_errors`, `models/openrouter.py`, and `_agent_graph.py` at
https://github.com/pydantic/pydantic-ai/tree/v2.55.0;
https://github.com/openai/openai-python/blob/v3.29.0/src/openai/_exceptions.py;
checked against the installed locked sources, 2026-10-18).

Test the timeout before the connection error, or every timeout becomes unavailable:

| What the run raises | The core's error | `model_calls.outcome` |
|---|---|---|
| `TimeoutError` from the 60 s scope, or `ModelAPIError` caused by `openai.APITimeoutError` | `model_timeout` | `timeout` |
| `ModelHTTPError` with status 429 | `model_rate_limited` | `rate_limited` |
| `ModelHTTPError` with any other status | `model_unavailable` | `provider_error` |
| any other `ModelAPIError` (a refused connection, an error with no status) | `model_unavailable` | `provider_error` |
| `UnexpectedModelBehavior` from output validation, or a value `schemas.py` cannot convert | the parse failure with its usage (`SKILL.md`'s port contract) | `invalid_output`, then the repair |

Each row is pinned by its own adapter test, so an upgrade that wraps errors differently
fails a test instead of shipping. Any other exception is a bug and propagates.
**BACKGROUND:** `designing-errors`' "Two kinds of failure".

## What never leaves the adapter

- The key, a prompt, the learner's text, a model's output, and the provider's error
  text are never logged and never put in an error message: a provider's error text can
  echo the prompt. An error's message names only what failed (a timeout, a status).
- No PydanticAI or `openai` type crosses into the core; the core sees its own values
  and errors only.

## Testing it

- **Outputs and prompts:** the same agents run on PydanticAI's `FunctionModel`, whose
  function returns the JSON text a `NativeOutput` run parses and records the messages
  it was sent. One test per task proves a valid answer converts to the right core
  value, an invalid one becomes the parse failure, and the messages hold what
  `prompts.py` rendered.
- **Error mapping:** the real `OpenRouterModel` over an `AsyncOpenAI` whose `httpx2` client
  has a mocked transport that answers each case (a 429, a 500, a timeout, a refused
  connection, a response without cost). `ALLOW_MODEL_REQUESTS` blocks a real model
  class, so only these tests lift it, with
  `pydantic_ai.models.override_allow_model_requests(True)` around a client whose
  transport cannot reach the network.
- **Wiring:** a test proves the client was built with `max_retries=0` and the
  OpenRouter base URL, and that an `OPENROUTER_API_KEY` set in the environment is not
  the key a request sends.
