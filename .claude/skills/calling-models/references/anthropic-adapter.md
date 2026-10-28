# The Anthropic adapter

Read when writing or changing `adapters/models/agents.py` or
`adapters/models/anthropic_provider.py`, their tests, or a provider module beside them.
`SKILL.md` holds the port contract and the service's sequence these rules serve. The
reasons and their sources are `docs/architecture/overview.md`'s § Decisions › "Models are
called through PydanticAI, inside the model adapters" and "Keys, models, and the mode"; the
external facts below that the overview does not state carry their own.

## Two modules, one seam

- `agents.py` is provider-neutral: the Partner's three and the Coach's seven task agents,
  the run wrapper (the 60 s scope, parse failures, refusals), and usage. It imports
  `pydantic_ai` but no provider SDK, and reaches the provider only through a
  `ProviderCalls` value: `name`, `settings`, `failure(error)`, `refused(response)`, and
  `cost(usage)`.
- `anthropic_provider.py` is everything Anthropic: the `anthropic.AsyncAnthropic` client,
  `AnthropicProvider` and one `AnthropicModel` per role, `AnthropicCalls` (the role's
  `ProviderCalls`), the price table, and `build_anthropic_models`. Never name it
  `anthropic.py`: it would shadow the SDK.
- A new provider (Amazon Bedrock next) is a module beside it that builds its own model and
  its own `ProviderCalls`, and a branch in `composition.py`; `agents.py`, the prompts, the
  schemas, and `core/` stay as they are.

## Building it

- `composition.py` builds the adapter only when it chooses Anthropic, passing the key from
  `Settings` and one `AnthropicRole` per role (its model id and effort). The key is
  unwrapped from its secret type there and nowhere else.
- `build_anthropic_models` builds one `AsyncAnthropic` with `api_key` the unwrapped key,
  `base_url` `https://api.anthropic.com`, `max_retries=0`, and
  `open_telemetry={"traces": False, "propagation": False}`, hands it to
  `AnthropicProvider(anthropic_client=...)`, and gives the provider nothing else.
- The explicit key makes the SDK skip its credential chain (`ANTHROPIC_API_KEY`,
  `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_PROFILE` and `ANTHROPIC_CONFIG_DIR` profiles, Workload
  Identity Federation), and the explicit base URL beats `ANTHROPIC_BASE_URL`. A complete
  telemetry option skips the `ANTHROPIC_OPEN_TELEMETRY_*` variables (anthropic 1.17.0
  `_client.py` and `_tracing.py`, read in the locked install, 2026-10-28).
- The SDK merges `ANTHROPIC_CUSTOM_HEADERS` into the client's headers even then, and
  `copy()` / `with_options()` re-read it; nothing in PydanticAI calls either. So the builder
  resets the client's private `_custom_headers` to `{}` right after construction, with a
  `noqa: SLF001` that gives the reason. Setting a default header of our own would mean
  putting it back after that reset.
- The SDK reads `ANTHROPIC_LOG` when imported and, at `debug`, logs every request's options,
  the prompt included (`_utils/_logs.py`, `_base_client.py`). The provider module sets the
  `anthropic` and `httpx2` loggers to WARNING right after importing the SDK, whatever the
  environment asks.
- The proxy and TLS variables (`HTTPS_PROXY`, `SSL_CERT_FILE`, and the like) still reach the
  SDK's HTTP client, which trusts the environment: they choose the network path, not the
  request, and a machine behind a proxy or with its own CA needs them.
- Each task gets one agent, built once, with `output_type=NativeOutput(<the task's schema
  model>)`, `retries=0`, no tools, and `agent.instrument = False`, which overrides a global
  `Agent.instrument_all()` default (`agent/__init__.py` at pydantic-ai v2.55.0).
- The client holds connections, so the builder registers `client.close` with
  `ResourceClosers`. **REQUIRED:** `designing-core-logic` (its adding-a-port reference,
  "An adapter that holds a resource").
- Every call of a role sends `AnthropicModelSettings(timeout=60, max_tokens=16_000,
  anthropic_effort=<the role's effort>)`, which PydanticAI sends as `max_tokens` and
  `output_config.effort`. Never set `thinking`: both default models think adaptively, and
  Sonnet 5.5 rejects disabled thinking. Without `max_tokens` PydanticAI sends the model's
  maximum output and streams the request behind the scenes.

## One call

1. `prompts.py` renders the request (and its repair, when there is one) into the
   instructions and messages. The adapter passes them through unchanged.
2. The run gets the role's settings, `timeout` 60 among them. The SDK's timeout bounds the
   client's waits rather than the whole call, so `agents.py` also runs the call inside a
   60 s `asyncio.timeout`.
3. The run happens inside `capture_run_messages()`, so the `ModelResponse` stays readable
   when parsing fails or the model refuses.
4. A refusal is checked before anything else is made of the response (below).
5. Usage is read from that response: tokens from `usage`, cost from `ProviderCalls.cost`
   (the configured model's USD price over those tokens; none for a model without a price),
   the model from the setting, the provider `anthropic`, and latency from the injected
   clock around the run.
6. What parses is converted by `schemas.py` into the core output value and returned with
   that usage.

## Pricing

`PRICES` in `anthropic_provider.py` maps a model id to its base input and output price per
million tokens, in USD, with the source URL and the date it was observed beside it. A tier
with `up_to_input_tokens` covers prompts up to that many input tokens (Haiku 5.5's 100,000);
a prompt over it takes the next tier. Changing a price or adding a model updates the table,
its comment, the overview's paragraph, and the cost test in the same pull request. Cost is
exact `Decimal` arithmetic; nothing rounds it.

## Mapping failures

PydanticAI turns an `anthropic.APIStatusError` into `ModelHTTPError` (carrying
`status_code`), and an `anthropic.APIConnectionError` into a plain `ModelAPIError`, chaining
the original with `from`. `anthropic.APITimeoutError` is a subclass of
`APIConnectionError`, so a client timeout arrives as a plain `ModelAPIError` whose
`__cause__` is the timeout. A schema that does not validate ends the run with
`UnexpectedModelBehavior` when output retries are 0. A response whose stop reason is
`refusal` maps to finish reason `content_filter`, keeps `"refusal"` in
`provider_details["finish_reason"]`, and raises `ContentFilterError` — a subclass of
`UnexpectedModelBehavior` — only when it carries no usable text; refused text that is
present goes to validation like any other (`_map_api_errors`, `_process_response`, and
`_FINISH_REASON_MAP` in `models/anthropic.py`, and `_agent_graph.py`, pydantic-ai-slim
2.55.0 with anthropic 1.17.0, run over a mocked transport on 2026-10-28).

Test the timeout before the connection error, or every timeout becomes unavailable, and
the refusal before the parse failure, or a refusal gets a repair:

| What the run raises or returns | The core's error | `model_calls.outcome` |
|---|---|---|
| `TimeoutError` from the 60 s scope, or `ModelAPIError` caused by `anthropic.APITimeoutError` | `model_timeout` | `timeout` |
| `ModelHTTPError` with status 429 | `model_rate_limited` | `rate_limited` |
| `ModelHTTPError` with any other status, 529 overloaded included | `model_unavailable`, with the status | `provider_error` |
| any other `ModelAPIError` (a refused connection) | `model_unavailable` | `provider_error` |
| a last response with stop reason `refusal`, whether the run raised `ContentFilterError`, failed validation, or parsed | `model_unavailable`, no status, no repair | `provider_error` |
| `UnexpectedModelBehavior` from output validation, or a value `schemas.py` cannot convert | the parse failure with its usage (`SKILL.md`'s port contract) | `invalid_output`, then the repair |

Each row is pinned by its own adapter test over a mocked transport, so an upgrade that wraps
errors differently fails a test instead of shipping. Any other exception is a bug and
propagates. A model error's row records no tokens or cost, a refusal's included.
**BACKGROUND:** `designing-errors`' "Two kinds of failure".

## What never leaves the adapter

- The key, a prompt, the learner's text, a model's output, and the provider's error
  text are never logged and never put in an error message: a provider's error text can
  echo the prompt. An error's message names only what failed (a timeout, a status).
- No PydanticAI or `anthropic` type crosses into the core; the core sees its own values
  and errors only.

## Testing it

- **Outputs, prompts, and the run wrapper** (`tests/adapters/models/test_agents.py`): the
  same agents run on PydanticAI's `FunctionModel` with a fake `ProviderCalls`, whose
  function returns the JSON text a `NativeOutput` run parses and records the messages it
  was sent. One test per task proves a valid answer converts to the right core value, an
  invalid one becomes the parse failure, and the messages hold what `prompts.py`
  rendered; others prove the wrapper raises the error `failure` names and never repairs a
  refusal.
- **The provider** (`tests/adapters/models/test_anthropic_provider.py`): the real
  `AnthropicModel` over an `AsyncAnthropic` whose `http_client` is
  `anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(...))` — the SDK uses
  `httpx2`, not `httpx` — answering each case: a 400, 429, 500, and 529, a timeout, a
  refused connection, a refusal with no text, with partial text, and with parsed text, and
  invalid JSON. `ALLOW_MODEL_REQUESTS` blocks a real model class, so only these tests lift
  it, with `pydantic_ai.models.override_allow_model_requests(True)` around a client whose
  transport cannot reach the network.
- **Wiring:** tests prove one client is built with the explicit key, base URL,
  `max_retries=0`, and telemetry off, shared by both roles and closed once; that the body
  carries `max_tokens`, `output_config.format` and `effort`, and no `thinking`, tools, or
  cache control; that every task's wire schema stays inside Anthropic's structured-output
  keywords; that setting every credential, endpoint, header, and telemetry variable
  `AsyncAnthropic` reads leaves the request (URL, headers, and body) identical to a clean
  environment's; and that `ANTHROPIC_LOG=debug` leaves the SDK's loggers off.
- **Cost:** the price table at known token counts, both sides of Haiku's 100,000-token tier,
  and an unknown model's null.
