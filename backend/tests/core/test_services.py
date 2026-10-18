from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import anyio
import pytest

from intent_to_english.adapters.memory import InMemoryTodoRepository
from intent_to_english.core import coaching, partner, services
from intent_to_english.core import errors as e
from intent_to_english.core import models as m
from intent_to_english.core.errors import (
    InvalidPageLimitError,
    InvalidTodoError,
    ModelOutputInvalidError,
    ModelRateLimitedError,
    ModelTimeoutError,
    ModelUnavailableError,
    TodoNotFoundError,
)
from intent_to_english.core.models import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    CallAttempt,
    CallOutcome,
    CheckId,
    ModelRole,
    ModelTask,
    Page,
    Parsed,
    ParseFailure,
    Repair,
    RestateMode,
    Stage,
    Todo,
    Usage,
)
from intent_to_english.core.services import TodoService

pytestmark = pytest.mark.anyio

UNKNOWN_ID = UUID("01900000-0000-7000-8000-0000000003e7")


@pytest.fixture
def service(fixed_clock, new_id):
    """A service over the in-memory repository, the core's fake."""
    return TodoService(InMemoryTodoRepository(), fixed_clock, new_id)


@pytest.fixture
def create_many(service):
    """Create ``count`` to-dos through the service, oldest first."""

    async def _create(count: int) -> list[Todo]:
        return [await service.create(f"todo {n}") for n in range(count)]

    return _create


async def test_create_valid_title_stores_open_todo_with_new_id_and_clock_time(
    service, nth_id, fixed_now
):
    todo = await service.create("  buy milk ")

    assert todo == Todo(id=nth_id(1), title="buy milk", created_at=fixed_now)
    assert await service.list_page() == Page(items=(todo,), next_cursor=None)


async def test_create_several_todos_gives_each_the_next_id(service, nth_id):
    first = await service.create("first")
    second = await service.create("second")

    assert (first.id, second.id) == (nth_id(1), nth_id(2))


async def test_create_empty_title_raises_and_stores_nothing(service):
    with pytest.raises(InvalidTodoError, match=r"got 0$"):
        await service.create("   ")

    assert await service.list_page() == Page(items=(), next_cursor=None)


async def test_list_page_empty_store_returns_empty_last_page(service):
    assert await service.list_page() == Page(items=(), next_cursor=None)


async def test_list_page_several_todos_returns_oldest_first(service, create_many):
    created = await create_many(3)

    page = await service.list_page()

    assert page == Page(items=tuple(created), next_cursor=None)


async def test_list_page_default_limit_returns_a_full_page_and_a_cursor(
    service, create_many
):
    created = await create_many(DEFAULT_PAGE_LIMIT + 1)

    page = await service.list_page()

    assert page.items == tuple(created[:DEFAULT_PAGE_LIMIT])
    assert page.next_cursor is not None


async def test_list_page_following_cursors_returns_every_todo_once(
    service, create_many
):
    created = await create_many(5)

    first = await service.list_page(limit=2)
    second = await service.list_page(first.next_cursor, 2)
    third = await service.list_page(second.next_cursor, 2)

    assert first.items + second.items + third.items == tuple(created)
    assert third.next_cursor is None


@pytest.mark.parametrize(
    ("limit", "expected_count"),
    [
        pytest.param(1, 1, id="min"),
        pytest.param(MAX_PAGE_LIMIT, MAX_PAGE_LIMIT, id="max"),
    ],
)
async def test_list_page_limit_at_a_bound_returns_that_many_and_a_cursor(
    service, create_many, limit, expected_count
):
    await create_many(MAX_PAGE_LIMIT + 1)

    page = await service.list_page(limit=limit)

    assert len(page.items) == expected_count
    assert page.next_cursor is not None


@pytest.mark.parametrize(
    "limit",
    [
        pytest.param(0, id="zero"),
        pytest.param(-1, id="negative"),
        pytest.param(MAX_PAGE_LIMIT + 1, id="above-max"),
    ],
)
async def test_list_page_limit_out_of_range_raises_invalid_page_limit_error(
    service, limit
):
    with pytest.raises(
        InvalidPageLimitError, match=rf"^Page limit must be 1-100, got {limit}$"
    ):
        await service.list_page(limit=limit)


async def test_complete_open_todo_marks_it_completed(service):
    todo = await service.create("buy milk")

    completed = await service.complete(todo.id)

    assert completed.is_completed is True
    assert (await service.list_page()).items == (completed,)


async def test_complete_completed_todo_returns_it_unchanged(service):
    todo = await service.create("buy milk")
    first = await service.complete(todo.id)

    second = await service.complete(todo.id)

    assert second == first


async def test_complete_unknown_id_raises_todo_not_found_error(service):
    with pytest.raises(TodoNotFoundError, match=rf"^To-do {UNKNOWN_ID} not found$"):
        await service.complete(UNKNOWN_ID)


async def test_delete_existing_todo_removes_only_that_todo(service):
    kept = await service.create("keep")
    dropped = await service.create("drop")

    await service.delete(dropped.id)

    assert (await service.list_page()).items == (kept,)


async def test_delete_unknown_id_raises_todo_not_found_error(service):
    with pytest.raises(TodoNotFoundError, match=rf"^To-do {UNKNOWN_ID} not found$"):
        await service.delete(UNKNOWN_ID)


@pytest.mark.parametrize(
    ("outputs", "outcomes", "error"),
    [
        pytest.param(("valid",), (CallOutcome.OK,), None, id="first-valid"),
        pytest.param(
            ("invalid", "valid"),
            (CallOutcome.INVALID_OUTPUT, CallOutcome.REPAIRED),
            None,
            id="repair-valid",
        ),
        pytest.param(
            ("parse", "valid"),
            (CallOutcome.INVALID_OUTPUT, CallOutcome.REPAIRED),
            None,
            id="parse-repaired",
        ),
        pytest.param(
            ("invalid", "invalid"),
            (CallOutcome.INVALID_OUTPUT, CallOutcome.INVALID_OUTPUT),
            ModelOutputInvalidError,
            id="repair-invalid",
        ),
        pytest.param(
            ("parse", "parse"),
            (CallOutcome.INVALID_OUTPUT, CallOutcome.INVALID_OUTPUT),
            ModelOutputInvalidError,
            id="parse-twice",
        ),
        pytest.param(
            ("timeout",), (CallOutcome.TIMEOUT,), ModelTimeoutError, id="timeout"
        ),
        pytest.param(
            ("rate",),
            (CallOutcome.RATE_LIMITED,),
            ModelRateLimitedError,
            id="rate-limit",
        ),
        pytest.param(
            ("provider",),
            (CallOutcome.PROVIDER_ERROR,),
            ModelUnavailableError,
            id="provider",
        ),
        pytest.param(
            ("invalid", "timeout"),
            (CallOutcome.INVALID_OUTPUT, CallOutcome.TIMEOUT),
            ModelTimeoutError,
            id="repair-timeout",
        ),
        pytest.param(
            ("invalid", "rate"),
            (CallOutcome.INVALID_OUTPUT, CallOutcome.RATE_LIMITED),
            ModelRateLimitedError,
            id="repair-rate-limit",
        ),
        pytest.param(
            ("invalid", "provider"),
            (CallOutcome.INVALID_OUTPUT, CallOutcome.PROVIDER_ERROR),
            ModelUnavailableError,
            id="repair-provider",
        ),
    ],
)
async def test_run_model_task_accounts_for_every_outcome_and_only_one_repair(
    outputs, outcomes, error
):
    usage = Usage("test", "model", 10, 5, None, 7)
    values = {
        "valid": Parsed(partner.PartnerLine("Hey! How's it going?"), usage),
        "invalid": Parsed(partner.PartnerLine("Why? What?"), usage),
        "parse": ParseFailure(usage, "Output did not match its schema"),
        "timeout": ModelTimeoutError("test", "model", 60000),
        "rate": ModelRateLimitedError("test", "model", 9),
        "provider": ModelUnavailableError("test", "model", 11),
    }
    queued = [values[key] for key in outputs]
    repairs: list[Repair | None] = []
    recorded: list[CallAttempt] = []
    request = partner.OpenRequest(None)

    async def call(got, repair):
        assert got == request
        assert len(recorded) == len(repairs)
        repairs.append(repair)
        value = queued.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    async def record(attempt):
        recorded.append(attempt)

    result = await services.run_model_task(
        ModelTask.OPEN, call, partner.check_open, request, record=record
    )

    assert tuple(attempt.outcome for attempt in result.attempts) == outcomes
    assert result.attempts == tuple(recorded)
    assert tuple(attempt.attempt for attempt in result.attempts) == tuple(
        range(1, len(outcomes) + 1)
    )
    assert repairs[0] is None
    assert queued == []
    assert repairs[1:] == [Repair(result.attempts[0].violations)] * (len(outputs) - 1)
    expected_error = error or type(None)
    assert type(result.error) is expected_error
    expected_outputs: dict[type[Exception] | type[None], partner.PartnerLine | None] = {
        type(None): partner.PartnerLine("Hey! How's it going?"),
        ModelOutputInvalidError: None,
        ModelTimeoutError: None,
        ModelRateLimitedError: None,
        ModelUnavailableError: None,
    }
    assert result.output == expected_outputs[expected_error]


async def test_run_model_task_does_not_repair_or_hide_an_unknown_exception():
    async def call(_request, _repair):
        message = "internal bug"
        raise ValueError(message)

    with pytest.raises(ValueError, match="internal bug"):
        await services.run_model_task(
            ModelTask.OPEN, call, partner.check_open, partner.OpenRequest(None)
        )


@pytest.mark.parametrize(
    ("task", "metadata", "task_request", "output"),
    [
        pytest.param(
            ModelTask.OPEN,
            (ModelRole.PARTNER, "open", partner.check_open),
            partner.OpenRequest(None),
            partner.PartnerLine("Hey! How's it going?"),
            id="open",
        ),
        pytest.param(
            ModelTask.REPLY,
            (ModelRole.PARTNER, "reply", partner.check_reply),
            partner.ReplyRequest((), True),
            partner.PartnerLine("I made coffee."),
            id="reply",
        ),
        pytest.param(
            ModelTask.RESTATE,
            (ModelRole.PARTNER, "restate", partner.check_restate),
            partner.RestateRequest((), "How was your day?", RestateMode.SIMPLER),
            partner.PartnerLine("How are you?"),
            id="restate",
        ),
        pytest.param(
            ModelTask.ACKNOWLEDGE,
            (ModelRole.COACH, "acknowledge", coaching.check_acknowledgment),
            coaching.AcknowledgeRequest("意図", ()),
            coaching.Acknowledgment("いいですね"),
            id="acknowledge",
        ),
        pytest.param(
            ModelTask.GAP_HINT,
            (ModelRole.COACH, "gap_hint", coaching.check_gap_hint),
            coaching.GapHintRequest("意図", "gap", "", (), ()),
            coaching.GapHint("hint"),
            id="gap-hint",
        ),
        pytest.param(
            ModelTask.FEEDBACK,
            (ModelRole.COACH, "feedback", coaching.check_feedback),
            coaching.FeedbackRequest(None, "I stayed home.", None, (), ()),
            coaching.Feedback("いいですね"),
            id="feedback",
        ),
        pytest.param(
            ModelTask.CHECK_RETRY,
            (ModelRole.COACH, "check_retry", coaching.check_retry_result),
            coaching.CheckRetryRequest(
                None, coaching.Feedback("いいですね"), "I stayed home.", 1, ()
            ),
            coaching.RetryAccepted("いいですね"),
            id="check-retry",
        ),
        pytest.param(
            ModelTask.SHOW_ANSWER,
            (ModelRole.COACH, "show_answer", coaching.check_show_answer),
            coaching.ShowAnswerRequest(Stage.ENGLISH, None, None, None, ()),
            coaching.Answer("I stayed home."),
            id="show-answer",
        ),
        pytest.param(
            ModelTask.ANSWER_QUESTION,
            (ModelRole.COACH, "answer_question", coaching.check_answer_question),
            coaching.AnswerQuestionRequest("質問", Stage.OPENING, None, None, None, ()),
            coaching.CoachAnswer("答え"),
            id="answer-question",
        ),
        pytest.param(
            ModelTask.WRAP_UP,
            (ModelRole.COACH, "wrap_up", coaching.check_wrap_up),
            coaching.WrapUpRequest((), ()),
            coaching.WrapUp(
                (
                    coaching.WrapUpItem("stayed home", "家で過ごした"),
                    coaching.WrapUpItem("made coffee", "コーヒーをいれた"),
                )
            ),
            id="wrap-up",
        ),
    ],
)
async def test_run_model_task_registry_runs_every_task_without_a_session(
    task, metadata, task_request, output
):
    role, method, check = metadata
    calls = []

    class Model:
        def __init__(self, role):
            self.role = role

        def __getattr__(self, method):
            async def call(request, repair=None):
                calls.append((self.role, method, request, repair))
                return Parsed(output, Usage("test", "model", 1, 2, None, 3))

            return call

    definition = services.MODEL_TASKS[task]
    assert definition.role is role
    assert definition.method == method
    assert definition.check is check
    assert definition.request_type is type(task_request)
    result = await definition.run(
        Model(ModelRole.PARTNER), Model(ModelRole.COACH), task_request
    )
    assert result.output == output
    assert result.error is None
    assert calls == [(role, method, task_request, None)]


async def test_run_model_task_empty_model_wrap_up_gets_one_schema_repair():
    repairs = []
    outputs = [coaching.WrapUp(()), coaching.WrapUp(())]

    async def call(_request, repair):
        repairs.append(repair)
        return Parsed(outputs.pop(0), Usage("test", "model", 1, 2, None, 3))

    result = await services.run_model_task(
        ModelTask.WRAP_UP, call, coaching.check_wrap_up, coaching.WrapUpRequest((), ())
    )
    assert isinstance(result.error, ModelOutputInvalidError)
    assert len(repairs) == 2
    assert tuple(v.check for v in repairs[1].violations) == (CheckId.SCHEMA,)
    assert result.output is None


@pytest.fixture
def turn_feedback():
    return coaching.Feedback(
        "COACH-MARKER",
        (coaching.Fix(1, "refreshing", "refreshed", "COACH-MARKER", m.FixTag.MISS),),
        "I feel refreshing today.",
        "I feel (①) ____ today.",
        "COACH-MARKER",
    )


def _parsed(output):
    return Parsed(output, Usage("test", "scripted", 10, 5, None, 7))


async def test_conversation_start_get_and_newest_first_list(
    make_conversation, fixed_now
):
    h = make_conversation()
    first = await h.service.start()
    second = await h.service.start()
    assert (first.stage, first.version, first.turn_index, first.finished_replies) == (
        m.Stage.OPENING,
        0,
        1,
        0,
    )
    assert first.allowed_actions == (m.Action.OPEN, m.Action.ASK, m.Action.END)
    assert first.started_at == fixed_now
    assert first.ended_at is None
    assert await h.service.get(first.id) == first
    assert tuple(s.id for s in (await h.service.list_page()).items) == (
        second.id,
        first.id,
    )
    with pytest.raises(e.InvalidPageLimitError, match="1-100"):
        await h.service.list_page(limit=101)


async def test_conversation_core_turn_preserves_entries_and_final_english(
    make_conversation, turn_feedback
):
    h = make_conversation()
    h.partner.open_call.outputs.append(
        _parsed(partner.PartnerLine("Hey! How's it going?"))
    )
    h.coach.acknowledge_call.outputs.append(
        _parsed(coaching.Acknowledgment("COACH-MARKER"))
    )
    h.coach.feedback_call.outputs.append(_parsed(turn_feedback))
    h.coach.check_retry_call.outputs.append(
        _parsed(coaching.RetryAccepted("COACH-MARKER"))
    )
    h.partner.reply_call.outputs.append(
        _parsed(partner.PartnerLine("Nice! What did you study?"))
    )
    view = await h.service.start()
    steps: tuple[tuple[m.Action, m.ActionInput], ...] = (
        (m.Action.OPEN, m.NoInput()),
        (m.Action.INTENT, m.TextInput("札幌マーカー\uff1a今日は気分がいい")),
        (m.Action.ENGLISH, m.TextInput("I feel refreshing today.")),
        (m.Action.RETRY, m.TextInput("I feel refreshed today.")),
    )
    for action, value in steps:
        view = await h.service.act(
            view.id, m.ActionRequest(action, view.version, value)
        )
    assert (view.stage, view.version, view.finished_replies) == (
        m.Stage.PARTNER_TURN,
        4,
        1,
    )
    assert view.entries[-1].payload == m.TurnDonePayload(
        "I feel refreshed today.", m.TurnEnd.ACCEPTED
    )
    assert (
        await h.repository.get(view.id)
    ).session.turn_state.practice == m.PracticeTarget(
        1, "札幌マーカー\uff1a今日は気分がいい", turn_feedback
    )
    assert tuple(entry.kind for entry in view.entries) == (
        m.EntryKind.PARTNER_LINE,
        m.EntryKind.INTENT,
        m.EntryKind.ACKNOWLEDGMENT,
        m.EntryKind.ENGLISH,
        m.EntryKind.FEEDBACK,
        m.EntryKind.RETRY,
        m.EntryKind.RETRY_RESULT,
        m.EntryKind.TURN_DONE,
    )
    view = await h.service.act(
        view.id, m.ActionRequest(m.Action.PARTNER_REPLY, view.version)
    )
    assert (view.stage, view.turn_index, view.version) == (m.Stage.INTENT, 2, 5)
    request, repair = h.partner.reply_call.requests[0]
    assert request.conversation == (
        m.ConversationLine(m.Speaker.PARTNER, "Hey! How's it going?"),
        m.ConversationLine(m.Speaker.LEARNER, "I feel refreshed today."),
    )
    assert request.share is False
    assert repair is None
    assert "札幌マーカー" not in repr(request)
    assert "COACH-MARKER" not in repr(request)
    assert tuple(entry.seq for entry in view.entries) == tuple(range(1, 10))
    assert len(await h.repository.model_calls(view.id)) == 5


@pytest.mark.parametrize(
    ("reading_case", "english"),
    [
        pytest.param(
            ("leave", "leave", ("leave", "live")),
            "I want to leave in Canada.",
            id="written",
        ),
        pytest.param(
            ("live", "live", ("leave", "live")),
            "I want to live in Canada.",
            id="corrected-reading",
        ),
        pytest.param(
            (" live ", "live", ("leave", " live ")),
            "I want to live in Canada.",
            id="offered-reading-whitespace",
        ),
    ],
)
async def test_conversation_reading_choice_is_used_by_feedback_and_final_english(
    make_conversation, reading_case, english, nth_id
):
    choice, normalized_choice, offered = reading_case
    h = make_conversation()
    session = m.Session(nth_id(50), h.clock.now, stage=m.Stage.INTENT)
    await h.repository.create(session)
    h.coach.feedback_call.outputs.extend(
        [
            _parsed(coaching.ReadingQuestion("leave", offered)),
            _parsed(coaching.Feedback("いいですね")),
        ]
    )
    view = await h.service.act(
        session.id,
        m.ActionRequest(
            m.Action.ENGLISH_DIRECT, 0, m.TextInput("I want to leave in Canada.")
        ),
    )
    assert view.stage is m.Stage.READING_CHECK
    snapshot = await h.repository.get(session.id)
    with pytest.raises(e.InvalidInputError, match="reading"):
        await h.service.act(
            session.id,
            m.ActionRequest(m.Action.READING, view.version, m.ReadingInput("lived")),
        )
    assert await h.repository.get(session.id) == snapshot
    view = await h.service.act(
        session.id,
        m.ActionRequest(m.Action.READING, view.version, m.ReadingInput(choice)),
    )
    assert view.stage is m.Stage.PARTNER_TURN
    assert view.entries[-1].payload == m.TurnDonePayload(
        english, m.TurnEnd.NO_FIX_NEEDED
    )
    assert h.coach.feedback_call.requests[-1][0].reading == coaching.ReadingChoice(
        "leave", normalized_choice
    )
    assert h.coach.feedback_call.requests[-1][0].intent is None


async def test_conversation_second_blank_off_finishes_the_turn(
    make_conversation, turn_feedback, nth_id
):
    h = make_conversation()
    session = m.Session(
        nth_id(50),
        h.clock.now,
        stage=m.Stage.RETRY,
        turn_state=m.TurnState(
            intent="意図", english="I feel refreshing today.", feedback=turn_feedback
        ),
    )
    await h.repository.create(session)
    h.coach.check_retry_call.outputs.extend(
        [
            _parsed(coaching.BlankOff((1,), "形を考えましょう")),
            _parsed(coaching.BlankOff((1,), "形を考えましょう")),
        ]
    )
    first = await h.service.act(
        session.id,
        m.ActionRequest(m.Action.RETRY, 0, m.TextInput("I feel refresh today.")),
    )
    assert first.stage is m.Stage.RETRY
    second = await h.service.act(
        session.id,
        m.ActionRequest(m.Action.RETRY, 1, m.TextInput("I feel fresh today.")),
    )
    assert second.entries[-1].payload == m.TurnDonePayload(
        "I feel fresh today.", m.TurnEnd.PIECE_GIVEN
    )
    assert second.stage is m.Stage.PARTNER_TURN
    assert tuple(r.submission_number for r, _ in h.coach.check_retry_call.requests) == (
        1,
        2,
    )


async def test_conversation_third_no_fix_reply_appends_check_in(
    make_conversation, nth_id
):
    h = make_conversation()
    session = m.Session(
        nth_id(50),
        h.clock.now,
        stage=m.Stage.ENGLISH,
        turn_index=3,
        finished_replies=2,
        turn_state=m.TurnState(intent="意図"),
    )
    await h.repository.create(session)
    h.coach.feedback_call.outputs.append(_parsed(coaching.Feedback("いいですね")))
    view = await h.service.act(
        session.id, m.ActionRequest(m.Action.ENGLISH, 0, m.TextInput("I stayed home."))
    )
    assert (view.finished_replies, view.stage) == (3, m.Stage.CHECK_IN)
    assert tuple(entry.kind for entry in view.entries) == (
        m.EntryKind.ENGLISH,
        m.EntryKind.FEEDBACK,
        m.EntryKind.TURN_DONE,
        m.EntryKind.CHECK_IN,
    )
    h.partner.reply_call.outputs.append(
        _parsed(partner.PartnerLine("That sounds nice."))
    )
    continued = await h.service.act(
        session.id, m.ActionRequest(m.Action.PARTNER_REPLY, view.version)
    )
    assert continued.entries[-2].payload == m.CheckInAnswerPayload(
        m.CheckInAnswer.CONTINUE
    )
    assert (continued.stage, continued.turn_index) == (m.Stage.INTENT, 4)


async def test_conversation_end_without_feedback_never_calls_a_model(make_conversation):
    h = make_conversation()
    view = await h.service.start()
    ended = await h.service.act(view.id, m.ActionRequest(m.Action.END, 0))
    assert (ended.status, ended.stage, ended.version) == (
        m.SessionStatus.ENDED,
        m.Stage.ENDED,
        1,
    )
    assert ended.ended_at == h.clock.now
    assert ended.wrap_up == coaching.WrapUp(())
    assert ended.entries == ()
    assert ended.allowed_actions == ()
    assert await h.repository.model_calls(view.id) == ()
    with pytest.raises(e.SessionEndedError, match="ended"):
        await h.service.act(view.id, m.ActionRequest(m.Action.END, 1))
    with pytest.raises(e.ActionNotAllowedError, match="not allowed"):
        await h.service.act(view.id, m.ActionRequest(m.Action.WRAP_UP, 1))


async def test_conversation_no_fix_feedback_still_makes_a_separate_wrap_up_due(
    make_conversation, nth_id
):
    h = make_conversation()
    session = m.Session(nth_id(50), h.clock.now, stage=m.Stage.INTENT)
    await h.repository.create(session)
    h.coach.feedback_call.outputs.append(_parsed(coaching.Feedback("いいですね")))
    view = await h.service.act(
        session.id,
        m.ActionRequest(m.Action.ENGLISH_DIRECT, 0, m.TextInput("I stayed home.")),
    )
    ended = await h.service.act(session.id, m.ActionRequest(m.Action.END, view.version))
    assert ended.wrap_up is None
    assert ended.allowed_actions == (m.Action.WRAP_UP,)
    assert h.coach.wrap_up_call.requests == []
    expected = coaching.WrapUp(
        (
            coaching.WrapUpItem("stayed home", "家で過ごした"),
            coaching.WrapUpItem("today", "今日"),
        )
    )
    h.coach.wrap_up_call.outputs.extend(
        [_parsed(coaching.WrapUp(())), _parsed(expected)]
    )
    wrapped = await h.service.act(
        session.id, m.ActionRequest(m.Action.WRAP_UP, ended.version)
    )
    assert wrapped.wrap_up == expected
    assert wrapped.status is m.SessionStatus.ENDED
    assert wrapped.entries == ended.entries
    assert wrapped.version == ended.version + 1
    assert tuple(v.check for v in h.coach.wrap_up_call.requests[-1][1].violations) == (
        m.CheckId.SCHEMA,
    )


@pytest.mark.parametrize(
    "action",
    [
        m.Action.HINT,
        m.Action.SHOW_ANSWER,
        m.Action.TYPED_COPY,
        m.Action.RESTATE,
        m.Action.REWRITE_INTENT,
        m.Action.PRACTICE_AGAIN,
        m.Action.ASK,
    ],
    ids=lambda a: a.value,
)
async def test_controls_read_session_before_state_or_input_checks(
    make_conversation, action
):
    h = make_conversation()
    with pytest.raises(e.SessionNotFoundError, match="not found"):
        await h.service.act(UNKNOWN_ID, m.ActionRequest(action, 0))


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (e.ModelTimeoutError("test", "model", 60000), "model_timeout"),
        (e.ModelRateLimitedError("test", "model", 1), "model_rate_limited"),
        (e.ModelUnavailableError("test", "model", 1), "model_unavailable"),
        (ValueError("bug"), "internal_error"),
    ],
    ids=["timeout", "rate-limit", "provider", "bug"],
)
async def test_conversation_failed_call_retains_input_and_marks_submission_failed(
    make_conversation, failure, code
):
    h = make_conversation()
    h.partner.open_call.outputs.append(failure)
    view = await h.service.start()
    with pytest.raises(type(failure), match=str(failure)):
        await h.service.act(view.id, m.ActionRequest(m.Action.OPEN, 0))
    failed = await h.service.get(view.id)
    assert (failed.stage, failed.version, failed.entries) == (m.Stage.OPENING, 0, ())
    assert failed.last_submission.state is m.LastSubmissionState.FAILED
    assert failed.last_submission.action is m.Action.OPEN
    assert failed.last_submission.input == m.NoInput()
    assert failed.last_submission.failure_code == code


async def _cancel_pending(
    service: services.ConversationService, session_id: UUID
) -> None:
    await service.cancel(session_id, 0)


async def _end_pending(service: services.ConversationService, session_id: UUID) -> None:
    await service.act(session_id, m.ActionRequest(m.Action.END, 0))


@pytest.mark.parametrize(
    ("terminate", "expected_state"),
    [
        pytest.param(_cancel_pending, (m.Stage.OPENING, 0), id="versioned-cancel"),
        pytest.param(_end_pending, (m.Stage.ENDED, 1), id="immediate-end"),
    ],
)
@pytest.mark.parametrize(
    ("model_output", "expected_outcome"),
    [
        pytest.param(
            Parsed(
                partner.PartnerLine("Hey! How's it going?"),
                Usage("test", "scripted", 10, 5, None, 7),
            ),
            m.CallOutcome.OK,
            id="late-output",
        ),
        pytest.param(
            e.ModelTimeoutError("test", "model", 60000),
            m.CallOutcome.TIMEOUT,
            id="late-model-error",
        ),
        pytest.param(
            Parsed(
                partner.PartnerLine("Why? What?"),
                Usage("test", "scripted", 10, 5, None, 7),
            ),
            m.CallOutcome.INVALID_OUTPUT,
            id="late-invalid-output",
        ),
        pytest.param(
            ParseFailure(Usage("test", "scripted", 10, 5, None, 7), "Invalid schema"),
            m.CallOutcome.INVALID_OUTPUT,
            id="late-parse-failure",
        ),
    ],
)
async def test_conversation_cancel_or_end_discards_late_output_and_keeps_call_log(
    make_conversation, terminate, expected_state, model_output, expected_outcome
):
    h = make_conversation()
    view = await h.service.start()
    h.partner.open_call.outputs.append(model_output)
    h.partner.open_call.started = anyio.Event()
    h.partner.open_call.release = anyio.Event()
    results = []

    async def open_session():
        with pytest.raises(e.ActionCancelledError, match="cancelled"):
            await h.service.act(view.id, m.ActionRequest(m.Action.OPEN, 0))
        results.append("cancelled")

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(open_session)
        await h.partner.open_call.started.wait()
        pending = await h.service.get(view.id)
        assert pending.last_submission.state is m.LastSubmissionState.PENDING
        with pytest.raises(e.ActionInProgressError, match="progress"):
            await h.service.act(view.id, m.ActionRequest(m.Action.OPEN, 0))
        await h.service.cancel(view.id, 99)
        assert (
            await h.service.get(view.id)
        ).last_submission.state is m.LastSubmissionState.PENDING
        with pytest.raises(e.InvalidInputError, match="kind"):
            await h.service.act(
                view.id, m.ActionRequest(m.Action.END, 0, m.TextInput("invalid kind"))
            )
        assert (
            await h.service.get(view.id)
        ).last_submission.state is m.LastSubmissionState.PENDING
        await terminate(h.service, view.id)
        h.partner.open_call.release.set()
    assert results == ["cancelled"]
    finished = await h.service.get(view.id)
    assert finished.entries == ()
    assert (finished.stage, finished.version) == expected_state
    calls = await h.repository.model_calls(view.id)
    assert len(calls) == 1
    assert calls[0].call.outcome is expected_outcome
    assert len(h.partner.open_call.requests) == 1


async def test_run_model_task_registry_rejects_a_wrong_request_before_binding_ports(
    make_conversation,
):
    h = make_conversation()
    with pytest.raises(TypeError, match="Wrong request type"):
        await services.MODEL_TASKS[m.ModelTask.OPEN].run(
            h.partner, h.coach, "wrong request"
        )
    assert h.partner.open_call.requests == []


async def test_conversation_unknown_and_stale_errors_precede_input_and_pending(
    make_conversation, nth_id
):
    h = make_conversation()
    with pytest.raises(e.SessionNotFoundError, match="not found"):
        await h.service.act(UNKNOWN_ID, m.ActionRequest(m.Action.OPEN, 0))
    session = m.Session(nth_id(50), h.clock.now, version=5)
    await h.repository.create(session)
    pending = m.Submission(
        nth_id(0), session.id, 5, m.Action.OPEN, m.NoInput(), h.boot_id, h.clock.now
    )
    await h.repository.begin_submission(
        pending, frozenset({m.Stage.OPENING}), h.clock.now
    )
    before = await h.repository.get(session.id)
    with pytest.raises(e.StaleSessionError, match="version"):
        await h.service.act(
            session.id, m.ActionRequest(m.Action.ENGLISH, 4, m.NoInput())
        )
    assert await h.repository.get(session.id) == before
    assert h.partner.open_call.requests == []
    assert await h.repository.model_calls(session.id) == ()


async def test_conversation_pending_error_precedes_ended_but_end_refusal_preserves_pending(
    make_conversation, nth_id
):
    h = make_conversation()
    session = m.Session(
        nth_id(50),
        h.clock.now,
        status=m.SessionStatus.ENDED,
        stage=m.Stage.ENDED,
        ended_at=h.clock.now,
    )
    await h.repository.create(session)
    pending = m.Submission(
        nth_id(0), session.id, 0, m.Action.WRAP_UP, m.NoInput(), h.boot_id, h.clock.now
    )
    await h.repository.begin_submission(
        pending, frozenset({m.Stage.ENDED}), h.clock.now
    )
    before = await h.repository.get(session.id)
    with pytest.raises(e.ActionInProgressError, match="progress"):
        await h.service.act(
            session.id, m.ActionRequest(m.Action.OPEN, 0, m.TextInput("private"))
        )
    with pytest.raises(e.SessionEndedError, match="ended"):
        await h.service.act(session.id, m.ActionRequest(m.Action.END, 0))
    assert await h.repository.get(session.id) == before
    await h.service.cancel(session.id, 0)
    with pytest.raises(e.SessionEndedError, match="ended"):
        await h.service.act(
            session.id, m.ActionRequest(m.Action.OPEN, 0, m.TextInput("private"))
        )
    assert await h.repository.model_calls(session.id) == ()


@pytest.mark.parametrize(
    ("action", "failure"),
    [(m.Action.OPEN, e.ActionNotAllowedError), (m.Action.ENGLISH, e.InvalidInputError)],
    ids=["stage-before-input", "invalid-input"],
)
async def test_conversation_preflight_refusals_write_nothing(
    make_conversation, nth_id, action, failure
):
    h = make_conversation()
    session = m.Session(nth_id(50), h.clock.now, stage=m.Stage.ENGLISH)
    await h.repository.create(session)
    before = await h.repository.get(session.id)
    with pytest.raises(failure, match=r"not allowed|Invalid"):
        await h.service.act(session.id, m.ActionRequest(action, 0, m.NoInput()))
    assert await h.repository.get(session.id) == before
    assert h.coach.feedback_call.requests == []


async def test_conversation_pending_at_exactly_150_seconds_is_still_live(
    make_conversation, nth_id
):
    h = make_conversation()
    session = m.Session(nth_id(50), h.clock.now)
    await h.repository.create(session)
    created = h.clock.now - timedelta(seconds=150)
    pending = m.Submission(
        nth_id(0), session.id, 0, m.Action.OPEN, m.NoInput(), h.boot_id, created
    )
    await h.repository.begin_submission(pending, frozenset({m.Stage.OPENING}), created)
    assert (
        await h.service.get(session.id)
    ).last_submission.state is m.LastSubmissionState.PENDING
    with pytest.raises(e.ActionInProgressError, match="progress"):
        await h.service.act(session.id, m.ActionRequest(m.Action.OPEN, 0))
    assert h.partner.open_call.requests == []


@pytest.mark.parametrize(
    ("seconds", "boot_offset"),
    [(151, 0), (0, 1)],
    ids=["expired-151-seconds", "another-boot"],
)
async def test_conversation_interrupted_submission_can_be_sent_again(
    make_conversation, nth_id, seconds, boot_offset
):
    h = make_conversation()
    session = m.Session(nth_id(50), h.clock.now)
    await h.repository.create(session)
    created = h.clock.now - timedelta(seconds=seconds)
    pending = m.Submission(
        nth_id(0),
        session.id,
        0,
        m.Action.OPEN,
        m.NoInput(),
        nth_id(9999 + boot_offset),
        created,
    )
    await h.repository.begin_submission(pending, frozenset({m.Stage.OPENING}), created)
    view = await h.service.get(session.id)
    assert view.last_submission.state is m.LastSubmissionState.INTERRUPTED
    assert view.last_submission.failure_code == "interrupted"
    assert (
        await h.repository.get(session.id)
    ).last_submission.status is m.SubmissionStatus.PENDING
    h.partner.open_call.outputs.append(
        _parsed(partner.PartnerLine("Hey! How's it going?"))
    )
    resumed = await h.service.act(session.id, m.ActionRequest(m.Action.OPEN, 0))
    assert (resumed.stage, resumed.version, resumed.last_submission) == (
        m.Stage.INTENT,
        1,
        None,
    )
    with pytest.raises(e.ActionCancelledError, match="cancelled"):
        await h.repository.finish_submission(
            pending.id, replace(session, version=1), (), h.clock.now
        )


async def test_conversation_invalid_output_records_both_attempts_and_failure(
    make_conversation,
):
    h = make_conversation()
    view = await h.service.start()
    h.partner.open_call.outputs.extend(
        [
            _parsed(partner.PartnerLine("Why? What?")),
            _parsed(partner.PartnerLine("Why? What?")),
        ]
    )
    with pytest.raises(e.ModelOutputInvalidError, match="failed its checks"):
        await h.service.act(view.id, m.ActionRequest(m.Action.OPEN, 0))
    failed = await h.service.get(view.id)
    assert (failed.stage, failed.version, failed.entries) == (m.Stage.OPENING, 0, ())
    assert failed.last_submission.failure_code == "model_output_invalid"
    calls = await h.repository.model_calls(view.id)
    assert tuple(call.call.outcome for call in calls) == (
        m.CallOutcome.INVALID_OUTPUT,
        m.CallOutcome.INVALID_OUTPUT,
    )
    stored = await h.repository.get(view.id)
    assert all(call.submission_id == stored.last_submission.id for call in calls)


async def test_conversation_wrap_up_failure_leaves_ended_session_and_due_wrap_up(
    make_conversation, nth_id
):
    h = make_conversation()
    session = m.Session(
        nth_id(50),
        h.clock.now,
        status=m.SessionStatus.ENDED,
        stage=m.Stage.ENDED,
        ended_at=h.clock.now,
    )
    await h.repository.create(session)
    h.coach.wrap_up_call.outputs.append(e.ModelTimeoutError("test", "model", 60000))
    with pytest.raises(e.ModelTimeoutError, match="timeout"):
        await h.service.act(session.id, m.ActionRequest(m.Action.WRAP_UP, 0))
    failed = await h.service.get(session.id)
    assert (failed.status, failed.stage, failed.version, failed.wrap_up) == (
        m.SessionStatus.ENDED,
        m.Stage.ENDED,
        0,
        None,
    )
    assert failed.last_submission.failure_code == "model_timeout"
    assert failed.allowed_actions == (m.Action.WRAP_UP,)


async def test_partner_requests_never_hold_intent_or_coach_text(
    make_conversation, turn_feedback
):
    h = make_conversation()
    h.partner.open_call.outputs.append(
        _parsed(partner.PartnerLine("Hey! How's it going?"))
    )
    h.partner.reply_call.outputs.extend(
        [
            _parsed(partner.PartnerLine("Nice! What else did you do?")),
            _parsed(partner.PartnerLine("I stayed home too.")),
        ]
    )
    h.coach.acknowledge_call.outputs.extend(
        [
            _parsed(coaching.Acknowledgment("COACH-MARKER")),
            _parsed(coaching.Acknowledgment("COACH-MARKER")),
        ]
    )
    h.coach.feedback_call.outputs.extend(
        [
            _parsed(
                replace(
                    turn_feedback,
                    sentence="I stayed home.",
                    template="(①) ____ stayed home.",
                    fixes=(
                        coaching.Fix(
                            1, "I", "Actually I", "COACH-MARKER", m.FixTag.IMPROVEMENT
                        ),
                    ),
                )
            ),
            _parsed(coaching.Feedback("COACH-MARKER")),
        ]
    )
    h.partner.restate_call.outputs.extend(
        [
            _parsed(partner.PartnerLine("How are you?")),
            _parsed(partner.PartnerLine("What did you do?")),
        ]
    )
    h.coach.gap_hint_call.outputs.extend(
        [
            _parsed(coaching.GapHint("COACH-MARKER")),
            _parsed(coaching.GapHint("COACH-MARKER")),
        ]
    )
    h.coach.answer_question_call.outputs.extend(
        [
            _parsed(coaching.CoachAnswer("COACH-MARKER")),
            _parsed(coaching.CoachAnswer("COACH-MARKER")),
        ]
    )
    h.coach.show_answer_call.outputs.append(_parsed(coaching.Answer("COACH-MARKER")))
    view = await h.service.start()
    view = await h.service.act(view.id, m.ActionRequest(m.Action.OPEN, view.version))
    steps: tuple[tuple[m.Action, m.ActionInput], ...] = (
        (m.Action.INTENT, m.TextInput("札幌マーカー")),
        (m.Action.HINT, m.HintInput("gap")),
        (m.Action.ASK, m.TextInput("質問マーカー")),
        (m.Action.RESTATE, m.RestateInput(m.RestateMode.SHORTER)),
        (m.Action.ENGLISH, m.TextInput("I stayed home.")),
        (m.Action.SHOW_ANSWER, m.NoInput()),
        (m.Action.TYPED_COPY, m.TextInput("I stayed home.")),
        (m.Action.PARTNER_REPLY, m.NoInput()),
        (m.Action.INTENT, m.TextInput("札幌マーカー")),
        (m.Action.HINT, m.HintInput("gap")),
        (m.Action.ASK, m.TextInput("質問マーカー")),
        (m.Action.RESTATE, m.RestateInput(m.RestateMode.SIMPLER)),
        (m.Action.ENGLISH, m.TextInput("I stayed home.")),
        (m.Action.PARTNER_REPLY, m.NoInput()),
    )
    for action, value in steps:
        view = await h.service.act(
            view.id, m.ActionRequest(action, view.version, value)
        )
    requests = (
        [r for r, _ in h.partner.open_call.requests]
        + [r for r, _ in h.partner.reply_call.requests]
        + [r for r, _ in h.partner.restate_call.requests]
    )
    assert all(
        "札幌マーカー" not in repr(request)
        and "COACH-MARKER" not in repr(request)
        and "質問マーカー" not in repr(request)
        for request in requests
    )
    assert tuple(request.share for request, _ in h.partner.reply_call.requests) == (
        False,
        True,
    )
    assert h.coach.feedback_call.requests[-1][0].earlier_english == ("I stayed home.",)


async def test_conversation_final_english_applies_readings_in_order_on_whole_case_sensitive_words(
    make_conversation, nth_id
):
    h = make_conversation()
    english = "I am starting, not startingly. Starting was hard."
    feedback = coaching.Feedback(
        "意図は伝わっています",
        (coaching.Fix(1, "starting", "learning", "説明", m.FixTag.IMPROVEMENT),),
        english,
        "I am (①) ____, not startingly. Starting was hard.",
        "穴を埋めてください",
        (coaching.ReadingNote("starting", "studying"),),
    )
    session = m.Session(nth_id(50), h.clock.now, stage=m.Stage.INTENT)
    await h.repository.create(session)
    h.coach.feedback_call.outputs.append(_parsed(feedback))
    h.coach.check_retry_call.outputs.append(
        _parsed(
            coaching.RetryAccepted(
                "いいですね", (coaching.ReadingNote("studying", "learning"),)
            )
        )
    )
    view = await h.service.act(
        session.id, m.ActionRequest(m.Action.ENGLISH_DIRECT, 0, m.TextInput(english))
    )
    view = await h.service.act(
        session.id, m.ActionRequest(m.Action.RETRY, view.version, m.TextInput(english))
    )
    assert view.entries[-1].payload == m.TurnDonePayload(
        "I am learning, not startingly. Starting was hard.", m.TurnEnd.ACCEPTED
    )


async def test_conversation_skip_ends_without_a_model_and_sets_practice(
    make_conversation, turn_feedback, nth_id
):
    h = make_conversation()
    session = m.Session(
        nth_id(50),
        h.clock.now,
        stage=m.Stage.RETRY,
        turn_state=m.TurnState(
            intent="意図", english="I feel refreshing today.", feedback=turn_feedback
        ),
    )
    await h.repository.create(session)
    view = await h.service.act(session.id, m.ActionRequest(m.Action.SKIP, 0))
    assert view.entries[-1].payload == m.TurnDonePayload(
        "I feel refreshing today.", m.TurnEnd.SKIPPED
    )
    assert tuple(entry.kind for entry in view.entries) == (
        m.EntryKind.SKIP,
        m.EntryKind.TURN_DONE,
    )
    assert (
        await h.repository.get(session.id)
    ).session.turn_state.practice == m.PracticeTarget(1, "意図", turn_feedback)
    assert await h.repository.model_calls(session.id) == ()


async def test_hint_passes_all_earlier_pairs_and_preserves_turn_state(
    make_conversation, nth_id
):
    h = make_conversation()
    session = m.Session(
        nth_id(50),
        h.clock.now,
        stage=m.Stage.ENGLISH,
        turn_state=m.TurnState(intent="久しぶりに映画を見た"),
    )
    await h.repository.create(session)
    h.coach.gap_hint_call.outputs.extend(
        [
            _parsed(coaching.GapHint("for the first time")),
            _parsed(coaching.GapHint("for the first time in a long time")),
        ]
    )
    first = await h.service.act(
        session.id,
        m.ActionRequest(m.Action.HINT, 0, m.HintInput("久しぶり", "I watched")),
    )
    second = await h.service.act(
        session.id,
        m.ActionRequest(m.Action.HINT, 1, m.HintInput("久しぶり", "I watched")),
    )
    assert first.stage is m.Stage.ENGLISH
    assert second.version == 2
    assert (await h.repository.get(session.id)).session.turn_state == session.turn_state
    request, _ = h.coach.gap_hint_call.requests[-1]
    assert request.earlier == (coaching.EarlierHint("久しぶり", "for the first time"),)
    assert request.partial_english == "I watched"
    assert tuple(entry.kind for entry in second.entries) == (
        m.EntryKind.HINT_REQUEST,
        m.EntryKind.GAP_HINT,
        m.EntryKind.HINT_REQUEST,
        m.EntryKind.GAP_HINT,
    )


async def test_show_answer_then_typed_copy_keeps_retry_count_and_uses_the_copy(
    make_conversation, turn_feedback, nth_id
):
    h = make_conversation()
    state = m.TurnState(
        intent="意図",
        english="I feel refreshing today.",
        feedback=turn_feedback,
        retry_count=1,
    )
    session = m.Session(nth_id(50), h.clock.now, stage=m.Stage.RETRY, turn_state=state)
    await h.repository.create(session)
    h.coach.show_answer_call.outputs.append(
        _parsed(coaching.Answer("I feel refreshed today."))
    )
    shown = await h.service.act(session.id, m.ActionRequest(m.Action.SHOW_ANSWER, 0))
    assert shown.stage is m.Stage.ANSWER_SHOWN
    assert (
        await h.repository.get(session.id)
    ).session.turn_state.shown_answer == "I feel refreshed today."
    copied = await h.service.act(
        session.id,
        m.ActionRequest(
            m.Action.TYPED_COPY, shown.version, m.TextInput("I feel better today.")
        ),
    )
    assert copied.entries[-1].payload == m.TurnDonePayload(
        "I feel better today.", m.TurnEnd.ANSWER_TYPED
    )
    assert (await h.repository.get(session.id)).session.turn_state.retry_count == 1
    assert len(await h.repository.model_calls(session.id)) == 1
    assert h.coach.check_retry_call.requests == []


async def test_show_answer_skip_falls_back_to_example_without_own_english(
    make_conversation, nth_id
):
    h = make_conversation()
    session = m.Session(
        nth_id(50),
        h.clock.now,
        stage=m.Stage.ENGLISH,
        turn_state=m.TurnState(intent="久しぶりに映画を見た"),
    )
    await h.repository.create(session)
    example = "I watched a movie for the first time in a long time."
    h.coach.show_answer_call.outputs.append(_parsed(coaching.Answer(example)))
    shown = await h.service.act(session.id, m.ActionRequest(m.Action.SHOW_ANSWER, 0))
    skipped = await h.service.act(
        session.id, m.ActionRequest(m.Action.SKIP, shown.version)
    )
    assert skipped.entries[-1].payload == m.TurnDonePayload(example, m.TurnEnd.SKIPPED)
    assert (skipped.finished_replies, skipped.stage) == (1, m.Stage.PARTNER_TURN)


async def test_restate_twice_uses_the_original_line_and_preserves_state(
    make_conversation,
):
    h = make_conversation()
    original = "Hey! How's it going?"
    h.partner.open_call.outputs.append(_parsed(partner.PartnerLine(original)))
    h.partner.restate_call.outputs.extend(
        [
            _parsed(partner.PartnerLine("How are you?")),
            _parsed(partner.PartnerLine("How do you feel?")),
        ]
    )
    view = await h.service.start()
    view = await h.service.act(view.id, m.ActionRequest(m.Action.OPEN, 0))
    before = (await h.repository.get(view.id)).session.turn_state
    shorter = await h.service.act(
        view.id,
        m.ActionRequest(
            m.Action.RESTATE, view.version, m.RestateInput(m.RestateMode.SHORTER)
        ),
    )
    simpler = await h.service.act(
        view.id,
        m.ActionRequest(
            m.Action.RESTATE, shorter.version, m.RestateInput(m.RestateMode.SIMPLER)
        ),
    )
    assert simpler.stage is m.Stage.INTENT
    assert (await h.repository.get(view.id)).session.turn_state == before
    assert tuple(request.line for request, _ in h.partner.restate_call.requests) == (
        original,
        original,
    )
    assert tuple(request.mode for request, _ in h.partner.restate_call.requests) == (
        m.RestateMode.SHORTER,
        m.RestateMode.SIMPLER,
    )
    assert (
        h.partner.restate_call.requests[0][0].conversation
        == h.partner.restate_call.requests[1][0].conversation
    )
    assert simpler.entries[-1].payload.line_kind is m.LineKind.RESTATEMENT


async def test_rewrite_intent_resets_working_state_but_keeps_practice(
    make_conversation, turn_feedback, nth_id
):
    h = make_conversation()
    target = m.PracticeTarget(1, "前の意図", turn_feedback)
    state = m.TurnState(
        intent="旧意図",
        english="Old English",
        feedback=turn_feedback,
        retry_count=1,
        reading=coaching.ReadingQuestion("leave", ("leave", "live")),
        shown_answer="Old answer",
        practice=target,
    )
    session = m.Session(
        nth_id(50),
        h.clock.now,
        stage=m.Stage.ANSWER_SHOWN,
        turn_index=2,
        turn_state=state,
    )
    await h.repository.create(session)
    h.coach.acknowledge_call.outputs.append(
        _parsed(coaching.Acknowledgment("いいですね"))
    )
    view = await h.service.act(
        session.id,
        m.ActionRequest(m.Action.REWRITE_INTENT, 0, m.TextInput("新しい意図")),
    )
    assert view.stage is m.Stage.ENGLISH
    assert (await h.repository.get(session.id)).session.turn_state == m.TurnState(
        intent="新しい意図", practice=target
    )
    assert view.entries[0].payload == m.IntentPayload("新しい意図", True)


@pytest.mark.parametrize(
    "frame",
    [(m.Stage.INTENT, 2, 1, 1), (m.Stage.CHECK_IN, 3, 3, 3)],
    ids=["next-turn-intent", "check-in"],
)
@pytest.mark.parametrize(
    "result",
    [
        coaching.RetryAccepted("いいですね"),
        coaching.BlankOff((1,), "最初の形を考えましょう"),
    ],
    ids=["accepted", "blank-off"],
)
async def test_practice_again_changes_only_targeted_entries_and_version(
    make_conversation, turn_feedback, nth_id, frame, result
):
    h = make_conversation()
    stage, turn_index, finished, practised_index = frame
    target = m.PracticeTarget(practised_index, "練習する意図", turn_feedback)
    session = m.Session(
        nth_id(50),
        h.clock.now,
        stage=stage,
        turn_index=turn_index,
        finished_replies=finished,
        turn_state=m.TurnState(practice=target),
    )
    await h.repository.create(session)
    h.coach.check_retry_call.outputs.append(_parsed(result))
    view = await h.service.act(
        session.id,
        m.ActionRequest(
            m.Action.PRACTICE_AGAIN, 0, m.TextInput("I feel refreshed today.")
        ),
    )
    assert (await h.repository.get(session.id)).session == replace(session, version=1)
    assert tuple(entry.kind for entry in view.entries) == (
        m.EntryKind.PRACTICE,
        m.EntryKind.PRACTICE_RESULT,
    )
    assert tuple(entry.turn_index for entry in view.entries) == (
        practised_index,
        practised_index,
    )
    assert view.entries[0].payload == m.PracticePayload(
        practised_index, "I feel refreshed today."
    )
    assert view.entries[1].payload == m.PracticeResultPayload(practised_index, result)
    request, _ = h.coach.check_retry_call.requests[0]
    assert (request.intent, request.feedback, request.submission_number) == (
        target.intent,
        target.feedback,
        1,
    )
    assert h.partner.reply_call.requests == []


async def test_ask_with_feedback_repairs_a_complete_sentence_leak_without_moving_stage(
    make_conversation, turn_feedback, nth_id
):
    h = make_conversation()
    session = m.Session(
        nth_id(50),
        h.clock.now,
        stage=m.Stage.RETRY,
        turn_state=m.TurnState(
            intent="意図", english="I feel refreshing today.", feedback=turn_feedback
        ),
    )
    await h.repository.create(session)
    h.coach.answer_question_call.outputs.extend(
        [
            _parsed(coaching.CoachAnswer("I feel refreshed today.")),
            _parsed(coaching.CoachAnswer("気分を表す形を考えてください")),
        ]
    )
    view = await h.service.act(
        session.id, m.ActionRequest(m.Action.ASK, 0, m.TextInput("質問マーカー"))
    )
    assert (await h.repository.get(session.id)).session == replace(session, version=1)
    assert tuple(entry.kind for entry in view.entries) == (
        m.EntryKind.QUESTION,
        m.EntryKind.COACH_ANSWER,
    )
    assert tuple(
        v.check for v in h.coach.answer_question_call.requests[-1][1].violations
    ) == (m.CheckId.COMPLETED_SENTENCE,)
    assert len(await h.repository.model_calls(session.id)) == 2


@pytest.mark.parametrize(
    ("action", "frame"),
    [
        pytest.param(
            m.Action.HINT,
            (m.Stage.RETRY, m.HintInput("gap"), True, False),
            id="hint-at-retry",
        ),
        pytest.param(
            m.Action.SHOW_ANSWER,
            (m.Stage.INTENT, m.NoInput(), True, False),
            id="answer-at-intent",
        ),
        pytest.param(
            m.Action.SHOW_ANSWER,
            (m.Stage.ANSWER_SHOWN, m.NoInput(), True, False),
            id="answer-already-shown",
        ),
        pytest.param(
            m.Action.TYPED_COPY,
            (m.Stage.RETRY, m.TextInput("copy"), True, False),
            id="copy-at-retry",
        ),
        pytest.param(
            m.Action.SKIP,
            (m.Stage.ENGLISH, m.NoInput(), True, False),
            id="skip-at-english",
        ),
        pytest.param(
            m.Action.RESTATE,
            (m.Stage.OPENING, m.RestateInput(m.RestateMode.SHORTER), True, False),
            id="restate-at-opening",
        ),
        pytest.param(
            m.Action.RESTATE,
            (m.Stage.PARTNER_TURN, m.RestateInput(m.RestateMode.SHORTER), True, False),
            id="restate-at-partner-turn",
        ),
        pytest.param(
            m.Action.RESTATE,
            (m.Stage.CHECK_IN, m.RestateInput(m.RestateMode.SHORTER), True, False),
            id="restate-at-check-in",
        ),
        pytest.param(
            m.Action.REWRITE_INTENT,
            (m.Stage.INTENT, m.TextInput("新意図"), True, False),
            id="rewrite-at-intent",
        ),
        pytest.param(
            m.Action.REWRITE_INTENT,
            (m.Stage.RETRY, m.TextInput("新意図"), False, False),
            id="rewrite-an-english-direct-turn",
        ),
        pytest.param(
            m.Action.PRACTICE_AGAIN,
            (m.Stage.PARTNER_TURN, m.TextInput("practice"), True, True),
            id="practice-at-partner-turn",
        ),
        pytest.param(
            m.Action.PRACTICE_AGAIN,
            (m.Stage.INTENT, m.TextInput("practice"), False, False),
            id="practice-first-turn-or-no-fix",
        ),
        pytest.param(
            m.Action.PRACTICE_AGAIN,
            (m.Stage.ENGLISH, m.TextInput("practice"), True, True),
            id="practice-after-next-intent",
        ),
    ],
)
async def test_controls_at_disallowed_stages_or_without_target_store_nothing(
    make_conversation, turn_feedback, nth_id, action, frame
):
    h = make_conversation()
    stage, value, has_intent, has_practice = frame
    target = {True: m.PracticeTarget(1, "練習する意図", turn_feedback), False: None}[
        has_practice
    ]
    intent = {True: "意図", False: None}[has_intent]
    session = m.Session(
        nth_id(50),
        h.clock.now,
        stage=stage,
        turn_state=m.TurnState(intent=intent, practice=target),
    )
    await h.repository.create(session)
    before = await h.repository.get(session.id)
    with pytest.raises(e.ActionNotAllowedError, match="not allowed"):
        await h.service.act(session.id, m.ActionRequest(action, 0, value))
    assert await h.repository.get(session.id) == before
    assert await h.repository.model_calls(session.id) == ()


@pytest.mark.parametrize(
    "action",
    [
        m.Action.HINT,
        m.Action.SHOW_ANSWER,
        m.Action.TYPED_COPY,
        m.Action.RESTATE,
        m.Action.REWRITE_INTENT,
        m.Action.PRACTICE_AGAIN,
        m.Action.ASK,
    ],
    ids=lambda a: a.value,
)
async def test_every_control_rejects_an_ended_session_before_input_checks(
    make_conversation, nth_id, action
):
    h = make_conversation()
    session = m.Session(
        nth_id(50),
        h.clock.now,
        status=m.SessionStatus.ENDED,
        stage=m.Stage.ENDED,
        ended_at=h.clock.now,
    )
    await h.repository.create(session)
    with pytest.raises(e.SessionEndedError, match="ended"):
        await h.service.act(session.id, m.ActionRequest(action, 0))
    assert (await h.repository.get(session.id)).last_submission is None


@pytest.mark.parametrize(
    ("action", "case"),
    [
        pytest.param(
            m.Action.ASK,
            (
                m.TextInput("日" * 500),
                coaching.CoachAnswer("答え"),
                "answer_question_call",
            ),
            id="question-500",
        ),
        pytest.param(
            m.Action.HINT,
            (m.HintInput("日" * 200), coaching.GapHint("ヒント"), "gap_hint_call"),
            id="gap-200",
        ),
    ],
)
async def test_control_input_limit_is_accepted(make_conversation, nth_id, action, case):
    value, output, port_name = case
    h = make_conversation()
    session = m.Session(
        nth_id(50),
        h.clock.now,
        stage=m.Stage.ENGLISH,
        turn_state=m.TurnState(intent="意図"),
    )
    await h.repository.create(session)
    getattr(h.coach, port_name).outputs.append(_parsed(output))
    view = await h.service.act(session.id, m.ActionRequest(action, 0, value))
    assert (view.stage, view.version) == (m.Stage.ENGLISH, 1)


@pytest.mark.parametrize(
    ("action", "value"),
    [(m.Action.ASK, m.TextInput("日" * 501)), (m.Action.HINT, m.HintInput("日" * 201))],
    ids=["question-501", "gap-201"],
)
async def test_control_input_one_past_limit_stores_nothing(
    make_conversation, nth_id, action, value
):
    h = make_conversation()
    session = m.Session(
        nth_id(50),
        h.clock.now,
        stage=m.Stage.ENGLISH,
        turn_state=m.TurnState(intent="意図"),
    )
    await h.repository.create(session)
    with pytest.raises(e.InvalidInputError, match="limit"):
        await h.service.act(session.id, m.ActionRequest(action, 0, value))
    assert (await h.repository.get(session.id)).last_submission is None


async def test_rewrite_stops_old_hints_and_readings_from_affecting_the_new_intent(
    make_conversation, turn_feedback, nth_id
):
    h = make_conversation()
    session = m.Session(
        nth_id(50),
        h.clock.now,
        stage=m.Stage.ENGLISH,
        turn_state=m.TurnState(intent="旧意図"),
    )
    await h.repository.create(session)
    h.coach.gap_hint_call.outputs.extend(
        [_parsed(coaching.GapHint("old hint")), _parsed(coaching.GapHint("new hint"))]
    )
    h.coach.feedback_call.outputs.extend(
        [
            _parsed(
                replace(
                    turn_feedback,
                    readings_noted=(coaching.ReadingNote("starting", "studying"),),
                )
            ),
            _parsed(coaching.Feedback("いいですね")),
        ]
    )
    h.coach.acknowledge_call.outputs.append(
        _parsed(coaching.Acknowledgment("いいですね"))
    )
    view = await h.service.act(
        session.id, m.ActionRequest(m.Action.HINT, 0, m.HintInput("old gap"))
    )
    view = await h.service.act(
        session.id,
        m.ActionRequest(
            m.Action.ENGLISH, view.version, m.TextInput("I feel refreshing today.")
        ),
    )
    old_entries = view.entries
    view = await h.service.act(
        session.id,
        m.ActionRequest(m.Action.REWRITE_INTENT, view.version, m.TextInput("新意図")),
    )
    assert view.entries[: len(old_entries)] == old_entries
    view = await h.service.act(
        session.id, m.ActionRequest(m.Action.HINT, view.version, m.HintInput("new gap"))
    )
    assert h.coach.gap_hint_call.requests[-1][0].earlier == ()
    assert h.coach.gap_hint_call.requests[-1][0].intent == "新意図"
    view = await h.service.act(
        session.id,
        m.ActionRequest(m.Action.ENGLISH, view.version, m.TextInput("I am starting.")),
    )
    assert h.coach.feedback_call.requests[-1][0].intent == "新意図"
    assert h.coach.feedback_call.requests[-1][0].earlier_english == ()
    assert view.entries[-1].payload == m.TurnDonePayload(
        "I am starting.", m.TurnEnd.NO_FIX_NEEDED
    )


async def test_answer_shown_skip_preserves_existing_learner_english(
    make_conversation, turn_feedback, nth_id
):
    h = make_conversation()
    session = m.Session(
        nth_id(50),
        h.clock.now,
        stage=m.Stage.RETRY,
        turn_state=m.TurnState(
            intent="意図", english="I feel refreshing today.", feedback=turn_feedback
        ),
    )
    await h.repository.create(session)
    h.coach.show_answer_call.outputs.append(
        _parsed(coaching.Answer("I feel refreshed today."))
    )
    shown = await h.service.act(session.id, m.ActionRequest(m.Action.SHOW_ANSWER, 0))
    skipped = await h.service.act(
        session.id, m.ActionRequest(m.Action.SKIP, shown.version)
    )
    assert skipped.entries[-1].payload == m.TurnDonePayload(
        "I feel refreshing today.", m.TurnEnd.SKIPPED
    )
    assert len(await h.repository.model_calls(session.id)) == 1


@pytest.mark.parametrize(
    ("action", "value", "port_name"),
    [
        pytest.param(
            m.Action.ASK, m.TextInput("質問"), "answer_question_call", id="ask"
        ),
        pytest.param(
            m.Action.RESTATE,
            m.RestateInput(m.RestateMode.SIMPLER),
            "restate_call",
            id="restate",
        ),
    ],
)
async def test_control_model_error_preserves_stage_version_and_timeline(
    make_conversation, action, value, port_name
):
    h = make_conversation()
    h.partner.open_call.outputs.append(
        _parsed(partner.PartnerLine("Hey! How's it going?"))
    )
    view = await h.service.start()
    view = await h.service.act(view.id, m.ActionRequest(m.Action.OPEN, 0))
    ports = {m.Action.ASK: h.coach, m.Action.RESTATE: h.partner}
    getattr(ports[action], port_name).outputs.append(
        e.ModelTimeoutError("test", "model", 60000)
    )
    with pytest.raises(e.ModelTimeoutError, match="timeout"):
        await h.service.act(view.id, m.ActionRequest(action, view.version, value))
    failed = await h.service.get(view.id)
    assert (failed.stage, failed.version, failed.entries) == (
        view.stage,
        view.version,
        view.entries,
    )
    assert failed.last_submission.action is action
    assert failed.last_submission.input == value


@pytest.mark.parametrize(
    ("note", "english", "expected"),
    [
        pytest.param(
            coaching.ReadingNote("can", "can't"),
            "I can go but can't stay.",
            "I can't go but can't stay.",
            id="straight-contraction",
        ),
        pytest.param(
            coaching.ReadingNote("can", "can't"),
            "I can go but can\u2019t stay.",
            "I can't go but can\u2019t stay.",
            id="curly-contraction",
        ),
        pytest.param(
            coaching.ReadingNote("can", "can't"),
            "They said 'can'.",
            "They said 'can't'.",
            id="quoted-whole-word",
        ),
        pytest.param(
            coaching.ReadingNote("can", "can't"),
            "I can, not cannon or scan.",
            "I can't, not cannon or scan.",
            id="longer-words",
        ),
        pytest.param(
            coaching.ReadingNote("can't", "cannot"),
            "I can't stay; can't've been easy.",
            "I cannot stay; can't've been easy.",
            id="contraction-is-a-whole-word",
        ),
        pytest.param(
            coaching.ReadingNote(" starting ", "studying"),
            "I am starting English.",
            "I am studying English.",
            id="written-whitespace",
        ),
        pytest.param(
            coaching.ReadingNote("starting", " studying "),
            "I am starting English.",
            "I am studying English.",
            id="replacement-whitespace",
        ),
    ],
)
async def test_reading_notes_preserve_word_internal_apostrophes(
    make_conversation, nth_id, note, english, expected
):
    h = make_conversation()
    session = m.Session(nth_id(50), h.clock.now, stage=m.Stage.INTENT)
    await h.repository.create(session)
    h.coach.feedback_call.outputs.append(
        _parsed(coaching.Feedback("いいですね", readings_noted=(note,)))
    )
    view = await h.service.act(
        session.id, m.ActionRequest(m.Action.ENGLISH_DIRECT, 0, m.TextInput(english))
    )
    assert view.entries[-1].payload == m.TurnDonePayload(
        expected, m.TurnEnd.NO_FIX_NEEDED
    )


@pytest.mark.parametrize(
    "readings",
    [("live", " live "), ("\tlive", "live\n")],
    ids=["spaces", "line-whitespace"],
)
async def test_reading_options_colliding_after_normalization_get_one_schema_repair(
    make_conversation, nth_id, readings
):
    h = make_conversation()
    session = m.Session(nth_id(50), h.clock.now, stage=m.Stage.INTENT)
    await h.repository.create(session)
    h.coach.feedback_call.outputs.extend(
        [
            _parsed(coaching.ReadingQuestion("leave", readings)),
            _parsed(coaching.Feedback("いいですね")),
        ]
    )
    view = await h.service.act(
        session.id,
        m.ActionRequest(m.Action.ENGLISH_DIRECT, 0, m.TextInput("I live here.")),
    )
    assert view.stage is m.Stage.PARTNER_TURN
    assert len(h.coach.feedback_call.requests) == 2
    calls = await h.repository.model_calls(session.id)
    assert tuple(call.call.outcome for call in calls) == (
        m.CallOutcome.INVALID_OUTPUT,
        m.CallOutcome.REPAIRED,
    )
    assert tuple(v.check for v in calls[0].call.violations) == (m.CheckId.SCHEMA,)
    assert not any(entry.kind is m.EntryKind.READING_QUESTION for entry in view.entries)
