---
name: calling-models
description: >
  Covers calling the Partner and Coach models: the PartnerModel and CoachModel ports,
  their request, output, and usage values, the output checks and the one repair in the
  core, model_calls outcomes, prompts.py and schemas.py, the PydanticAI adapter on the
  Anthropic API, the fixed-response mode, and ANTHROPIC_API_KEY and the model settings.
  Use when adding or changing a model task, a prompt, an output check, the Anthropic
  adapter, the fixed-response mode, a model setting, a test that touches a model, or a
  new provider.
---

# Calling Models

**Owns:** how the app calls its two model roles — the ports and their values, the output
checks and the repair, the adapters, the model settings, and the tests that touch a
model. **Does not own:** what each output says (`docs/product/conversation-rules.md`);
which action runs which task (`designing-core-logic`'s conversation-flow reference); ports, settings, and the composition root in general
(`designing-core-logic`); the error classes and their statuses (`designing-errors`); the
`model_calls` table (`persisting-data`); adding a package or an extra
(`managing-dependencies`).

## Where each piece lives

Under `backend/src/intent_to_english/`:

| Piece | Module |
|---|---|
| The Partner's and the Coach's request and output values, and each task's checks | `core/partner.py`, `core/coaching.py` |
| Sentence splitting, question counting, Latin and Japanese script detection | `core/text.py` |
| The usage, violation, and repair values shared by both roles | `core/models.py` (the model-call record) |
| `PartnerModel`, `CoachModel` | `core/ports.py` |
| The call sequence below | `core/services.py` (`ConversationService`) |
| `model_timeout`, `model_rate_limited`, `model_unavailable`, `model_output_invalid` | `core/errors.py` |
| The fixed-response mode | `adapters/models/fixed.py` |
| The provider-neutral task agents, run wrapper, and usage | `adapters/models/agents.py` |
| Everything Anthropic: client, model, settings, failure mapping, refusals, prices | `adapters/models/anthropic_provider.py` |
| The instructions and messages each task sends | `adapters/models/prompts.py` |
| One Pydantic model per output, and its conversion to the core value | `adapters/models/schemas.py` |
| The key, the mode, the model ids; the adapter choice | `settings.py`; `composition.py` |

In `src/`, `pydantic_ai` and `anthropic` are imported only under
`adapters/models/`. Ruff's banned-api rule names them (and `openai`), but `api/**` and `adapters/**`
are exempt from it, so review keeps them out of those layers; tests may import them.

## The port contract

`PartnerModel` has `open`, `reply`, and `restate`; `CoachModel` has `acknowledge`,
`gap_hint`, `feedback`, `check_retry`, `show_answer`, `answer_question`, and `wrap_up`.
Rejected: one generic completion port with prompts built in the core, which would put
prompt text and provider message shapes in `core/`.

- **One frozen request dataclass per method,** holding what that task and its checks
  need and nothing more, plus an optional repair carrying the previous output's
  violations.
- **It returns the output value with its call's usage:** provider, model, input and
  output tokens, the cost in USD or none, and latency. Output values are
  core dataclasses with no schema concerns; `feedback` returns either feedback or a
  reading question.
- **It raises a model error** for a timeout, rate limiting, an unavailable or
  unreachable provider, or a refusal (`model_unavailable`, outcome `provider_error`, never
  repaired), carrying the provider, model, and latency the call's row needs, plus the HTTP
  status when the provider answered with one — an integer, never its body.
- **An output that does not parse is reported, not raised as a model error:** the
  service gets the parse failure with the call's usage and treats it like a failed
  check.
- **The Partner's requests hold only English:** the English lines of the conversation
  (each turn's final English and the Partner's own lines), the previous session's
  opener, the line to restate with shorter or simpler, and whether taking turns says
  share. No field can carry the intent, hints, feedback, or questions to the Coach (P7).
  A test builds every Partner request from a session full of marked Japanese and Coach
  text and finds no marker in the request or in the prompt `prompts.py` renders from it.

## The service's sequence for every model task

Checks and the repair live in the core, so the fixed-response mode and live practice
behave alike, whatever adapter answered.

1. Build the task's request from the session (the conversation-flow reference's "One
   action, end to end").
2. Call the port; each call has 60 s.
3. Run the task's checks on what parsed. A parse failure is the violation of "The output
   matches its schema".
4. No violation: done. A violation: exactly one repair call, the same request with the
   violations as its repair, checked the same way.
5. The repair still failing raises `model_output_invalid`. A model error at either
   attempt ends the action at once with that error; there is no repair and no retry.
6. Every attempt is a `model_calls` row, written as soon as it ends: attempt 1 or 2, its
   usage, its violations, and its outcome — `ok`, `invalid_output` (failed its checks or
   did not parse), `repaired` (a repair that passed), `timeout`, `rate_limited`, or
   `provider_error`. Never the key or the prompt text.

## Adding or changing a model task

1. **The values.** The request and output dataclasses in `core/partner.py` or
   `core/coaching.py`, frozen, with invariants in `__post_init__`. **REQUIRED:**
   `designing-core-logic`.
2. **The checks.** One pure function per checkable rule — each row of conversation-rules
   § 6's required table that applies to the task — returning the output's violations
   against its request. A candidate rule becomes a check only when its issue asks for
   one. Shared text logic goes in `core/text.py`.
3. **The port method** on `PartnerModel` or `CoachModel`, its docstring stating what it
   returns and raises. A Partner request takes no new field that is not English the
   Partner said or heard.
4. **The schema.** A Pydantic model in `schemas.py` for the JSON schema, and its
   conversion to the core value. A value the schema accepts but the core value refuses
   is a parse failure.
5. **The prompt** in `prompts.py`: instructions in English, quoting the Japanese the
   product speaks (the exception in `AGENTS.md`'s "Overview"). It
   renders the repair's violations when there is one.
6. **The fixed response** in `fixed.py`: a deterministic function of the request that
   passes every check, reports provider `fixed` with no tokens or cost, and still
   reaches every stage the task can lead to.
7. **The agent** for the task in `agents.py`. **REQUIRED:**
   [references/anthropic-adapter.md](references/anthropic-adapter.md).
8. **The service call,** through the sequence above.
9. **Tests,** as below.
10. A rule or an output shape that changes what a model writes changes
    conversation-rules first; a change to the design rewrites this skill or its reference
    in the same pull request (`AGENTS.md`'s "Before changing the architecture").

## Settings and the mode

| Setting | Read as |
|---|---|
| `ANTHROPIC_API_KEY` | unprefixed, through a validation alias, as a secret; unset or blank means no key |
| `INTENT_TO_ENGLISH_MODEL_MODE` | `auto` with a key selects the Anthropic adapters for both roles; `fixed` always selects fixed adapters |
| `INTENT_TO_ENGLISH_COACH_MODEL`, `INTENT_TO_ENGLISH_PARTNER_MODEL` | Anthropic model ids, checked only to be non-empty; defaults `claude-sonnet-5-5` and `claude-haiku-5-5` |
| `INTENT_TO_ENGLISH_COACH_REASONING_EFFORT`, `INTENT_TO_ENGLISH_PARTNER_REASONING_EFFORT` | one of Anthropic's effort levels (`low`, `medium`, `high`, `xhigh`, `max`), case-insensitive; unset or blank keeps `medium`; anything else fails at startup naming its variable |

The defaults follow the owner's rule: the cheap model where it holds quality, a stronger
one only where it does not, and Sonnet as the ceiling — no Opus or Fable default. Each
role's effort is its own setting because the Coach is nearly all of a run's cost and the
slow side of a turn while the Partner is neither. `composition.py`
selects both Anthropic roles in auto with a key, otherwise both fixed roles;
`GET /api/meta` reports that selection. The README's configuration table
lists all six (**REQUIRED:** `updating-docs`). How a setting is validated and isolated
in tests: **REQUIRED:** `designing-core-logic`'s "Settings are read once, at the boundary".

## Testing without a live call

- `pydantic_ai.models.ALLOW_MODEL_REQUESTS = False` for the whole backend suite, set in
  `backend/tests/conftest.py`, so a test that reaches a real model fails instead of
  billing. Only the adapter's error-mapping tests lift it, over a mocked transport.
- **Core and service tests** use scripted fakes of the two ports: each returns a queued
  output or error and records the requests it got. The repair has a test where an
  invalid output is followed by a valid one, and one where both fail (502
  `model_output_invalid`).
- **Each check** has core tests from conversation-rules' wording and worked examples:
  an output that passes, and one per way it can fail.
- **Adapter tests** drive PydanticAI's `FunctionModel`, and a mocked transport for the
  error mapping (the reference's "Testing it").
- **API, screen, and browser tests** run the fixed-response mode; the browser test
  (`just e2e`) runs with the mode forced to `fixed`, so it never bills even where a key
  is exported. A composition test
  pins the fixed adapter without a key and with the mode `fixed`.
- **No test is skipped for lack of a key,** and none is live or recorded. Live calls
  happen only in the owner's practice.

Where each file goes is **REQUIRED:** `placing-tests`; how each is written,
**REQUIRED:** `writing-tests`.

## Adding a provider

Amazon Bedrock is the next one, once the account's Bedrock quota allows calls.

1. Its package or extra through **REQUIRED:** `managing-dependencies`, imported under
   `adapters/models/` only: the Anthropic SDK's Bedrock client (`AsyncAnthropicBedrock`)
   behind PydanticAI's same Anthropic provider and model, or PydanticAI's Bedrock model
   with the `bedrock` extra.
2. A provider module beside `anthropic_provider.py` that builds the model and its own
   `ProviderCalls` — settings, failure mapping to the same core errors, refusal check, and
   prices — behind the same agents, prompts, and schemas in `agents.py`.
3. Its own output-mode check: Claude Sonnet 5.5 rejects a forced tool call on Bedrock
   too, so the module uses the JSON schema mode its route supports, checked on the wire.
4. A setting choosing it, read in `composition.py`, and its tests as above.

Nothing in `core/` changes.
