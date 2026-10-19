"""Application use cases and their shared, provider-independent model-task runner."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol

from intent_to_english.core import coaching, errors, flow, models, partner
from intent_to_english.core.errors import (
    ModelError,
    ModelOutputInvalidError,
    ModelRateLimitedError,
    ModelTimeoutError,
)
from intent_to_english.core.models import (
    CallAttempt,
    CallOutcome,
    CheckId,
    ModelRole,
    ModelTask,
    Parsed,
    ParseFailure,
    Repair,
    Usage,
    Violation,
    check_page_limit,
)
from intent_to_english.core.text import count_questions as text_count_questions

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from uuid import UUID

    from intent_to_english.core.models import (
        ActionRequest,
        Page,
        SessionSummary,
        SessionView,
    )
    from intent_to_english.core.ports import (
        Clock,
        CoachModel,
        IdFactory,
        PartnerModel,
        SessionRepository,
    )


type ModelCall[Request, Output] = Callable[
    [Request, Repair | None], Awaitable[Parsed[Output] | ParseFailure]
]
type OutputCheck[Request, Output] = Callable[[Request, Output], tuple[Violation, ...]]
type RecordAttempt = Callable[[CallAttempt], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class TaskRun[Output]:
    """A completed task retains every attempt even when no output is usable."""

    output: Output | None
    attempts: tuple[CallAttempt, ...]
    error: ModelError | ModelOutputInvalidError | None


async def run_model_task[Request, Output](
    task: ModelTask,
    call: ModelCall[Request, Output],
    check: OutputCheck[Request, Output],
    request: Request,
    *,
    record: RecordAttempt | None = None,
) -> TaskRun[Output]:
    """Run one call and at most one repair, recording each before proceeding.

    A model error is returned with its recorded attempt, never repaired or raised
    here. Parse and check violations get exactly one repair. Unknown call, check
    and record-callback exceptions propagate so a caller can preserve its input
    and report an internal failure without disguising it as a provider error.
    """
    attempts: list[CallAttempt] = []
    repair: Repair | None = None
    role = MODEL_TASKS[task].role
    for number in (1, 2):
        try:
            parsed = await call(request, repair)
        except ModelError as error:
            outcome = CallOutcome.PROVIDER_ERROR
            if isinstance(error, ModelTimeoutError):
                outcome = CallOutcome.TIMEOUT
            elif isinstance(error, ModelRateLimitedError):
                outcome = CallOutcome.RATE_LIMITED
            usage = Usage(
                error.provider, error.model, None, None, None, error.latency_ms
            )
            attempt = CallAttempt(role, task, number, usage, outcome)
            attempts.append(attempt)
            if record is not None:
                await record(attempt)
            return TaskRun(None, tuple(attempts), error)
        violations = (
            (Violation(CheckId.SCHEMA, parsed.detail),)
            if isinstance(parsed, ParseFailure)
            else check(request, parsed.output)
        )
        if isinstance(parsed, Parsed):
            violations += _schema_violations(task, parsed.output)
        outcome = (
            CallOutcome.INVALID_OUTPUT
            if violations
            else (CallOutcome.OK if number == 1 else CallOutcome.REPAIRED)
        )
        attempt = CallAttempt(role, task, number, parsed.usage, outcome, violations)
        attempts.append(attempt)
        if record is not None:
            await record(attempt)
        if not violations and isinstance(parsed, Parsed):
            return TaskRun(parsed.output, tuple(attempts), None)
        repair = Repair(violations)
    return TaskRun(None, tuple(attempts), ModelOutputInvalidError(task))


def _schema_violations(task: ModelTask, output: object) -> tuple[Violation, ...]:
    if (
        task is ModelTask.WRAP_UP
        and isinstance(output, coaching.WrapUp)
        and not output.items
    ):
        return (
            Violation(CheckId.SCHEMA, "A model wrap-up must contain at least one item"),
        )
    if (
        task is ModelTask.FEEDBACK
        and isinstance(output, coaching.ReadingQuestion)
        and output.readings[0].strip() == output.readings[1].strip()
    ):
        return (
            Violation(
                CheckId.SCHEMA, "Reading options must stay distinct after trimming"
            ),
        )
    return ()


class ModelTaskDefinition(Protocol):
    """A task can be run by name without knowing its request's type parameter."""

    @property
    def role(self) -> ModelRole:
        """The model role whose port is called."""

    @property
    def method(self) -> str:
        """The method on that role's port."""

    @property
    def check(self) -> object:
        """The original typed check entry point, retained as metadata."""

    @property
    def request_type(self) -> type[object]:
        """The request value an evaluator constructs for this task."""

    async def run(
        self,
        partner_model: PartnerModel,
        coach_model: CoachModel,
        request: object,
        *,
        record: RecordAttempt | None = None,
    ) -> TaskRun[object]:
        """Validate a request's type and execute the shared runner."""


@dataclass(frozen=True, slots=True)
class TaskDefinition[Request, Output]:
    """Keep each port method, request type and check coupled by type checking."""

    task: ModelTask
    role: ModelRole
    method: str
    request_type: type[Request]
    check: OutputCheck[Request, Output]
    bind: Callable[[PartnerModel, CoachModel], ModelCall[Request, Output]]

    async def run(
        self,
        partner_model: PartnerModel,
        coach_model: CoachModel,
        request: object,
        *,
        record: RecordAttempt | None = None,
    ) -> TaskRun[Output]:
        """A deserialized request is checked before a provider can be called."""
        if not isinstance(request, self.request_type):
            msg = f"Wrong request type for task {self.task}"
            raise TypeError(msg)
        return await run_model_task(
            self.task,
            self.bind(partner_model, coach_model),
            self.check,
            request,
            record=record,
        )


MODEL_TASKS: Mapping[ModelTask, ModelTaskDefinition] = MappingProxyType(
    {
        ModelTask.OPEN: TaskDefinition[partner.OpenRequest, partner.PartnerLine](
            ModelTask.OPEN,
            ModelRole.PARTNER,
            "open",
            partner.OpenRequest,
            partner.check_open,
            lambda p, _c: p.open,
        ),
        ModelTask.REPLY: TaskDefinition[partner.ReplyRequest, partner.PartnerLine](
            ModelTask.REPLY,
            ModelRole.PARTNER,
            "reply",
            partner.ReplyRequest,
            partner.check_reply,
            lambda p, _c: p.reply,
        ),
        ModelTask.RESTATE: TaskDefinition[partner.RestateRequest, partner.PartnerLine](
            ModelTask.RESTATE,
            ModelRole.PARTNER,
            "restate",
            partner.RestateRequest,
            partner.check_restate,
            lambda p, _c: p.restate,
        ),
        ModelTask.ACKNOWLEDGE: TaskDefinition[
            coaching.AcknowledgeRequest, coaching.Acknowledgment
        ](
            ModelTask.ACKNOWLEDGE,
            ModelRole.COACH,
            "acknowledge",
            coaching.AcknowledgeRequest,
            coaching.check_acknowledgment,
            lambda _p, c: c.acknowledge,
        ),
        ModelTask.GAP_HINT: TaskDefinition[coaching.GapHintRequest, coaching.GapHint](
            ModelTask.GAP_HINT,
            ModelRole.COACH,
            "gap_hint",
            coaching.GapHintRequest,
            coaching.check_gap_hint,
            lambda _p, c: c.gap_hint,
        ),
        ModelTask.FEEDBACK: TaskDefinition[
            coaching.FeedbackRequest, coaching.Feedback | coaching.ReadingQuestion
        ](
            ModelTask.FEEDBACK,
            ModelRole.COACH,
            "feedback",
            coaching.FeedbackRequest,
            coaching.check_feedback,
            lambda _p, c: c.feedback,
        ),
        ModelTask.CHECK_RETRY: TaskDefinition[
            coaching.CheckRetryRequest, coaching.RetryResult
        ](
            ModelTask.CHECK_RETRY,
            ModelRole.COACH,
            "check_retry",
            coaching.CheckRetryRequest,
            coaching.check_retry_result,
            lambda _p, c: c.check_retry,
        ),
        ModelTask.SHOW_ANSWER: TaskDefinition[
            coaching.ShowAnswerRequest, coaching.Answer
        ](
            ModelTask.SHOW_ANSWER,
            ModelRole.COACH,
            "show_answer",
            coaching.ShowAnswerRequest,
            coaching.check_show_answer,
            lambda _p, c: c.show_answer,
        ),
        ModelTask.ANSWER_QUESTION: TaskDefinition[
            coaching.AnswerQuestionRequest, coaching.CoachAnswer
        ](
            ModelTask.ANSWER_QUESTION,
            ModelRole.COACH,
            "answer_question",
            coaching.AnswerQuestionRequest,
            coaching.check_answer_question,
            lambda _p, c: c.answer_question,
        ),
        ModelTask.WRAP_UP: TaskDefinition[coaching.WrapUpRequest, coaching.WrapUp](
            ModelTask.WRAP_UP,
            ModelRole.COACH,
            "wrap_up",
            coaching.WrapUpRequest,
            coaching.check_wrap_up,
            lambda _p, c: c.wrap_up,
        ),
    }
)


class ConversationService:
    """Execute versioned conversation actions over injected models and storage."""

    def __init__(  # noqa: PLR0913, PLR0917 - six collaborators match the constructor contract in Issue #14.
        self,
        repository: SessionRepository,
        partner_model: PartnerModel,
        coach_model: CoachModel,
        clock: Clock,
        new_id: IdFactory,
        boot_id: UUID,
    ) -> None:
        """One process boot id distinguishes live work from interrupted submissions."""
        self._repository = repository
        self._partner = partner_model
        self._coach = coach_model
        self._clock = clock
        self._new_id = new_id
        self._boot_id = boot_id

    async def start(self) -> SessionView:
        """Persist an opening session before any billed call.

        Returns:
            A version-zero view whose opener is still due.
        """
        stored = await self._repository.create(
            models.Session(self._new_id(), self._clock())
        )
        return self._view(stored)

    async def list_page(
        self, cursor: str | None = None, limit: int = models.SESSION_PAGE_LIMIT
    ) -> Page[SessionSummary]:
        """List newest sessions with the shared page bounds.

        Args:
            cursor: A previously returned cursor, or None for the first page.
            limit: At least one and at most MAX_PAGE_LIMIT.

        Returns:
            A newest-first page, with a cursor only when more sessions remain.

        Raises:
            InvalidCursorError: The cursor is not a session cursor.
            InvalidPageLimitError: The limit is outside the shared bounds.
        """
        check_page_limit(limit)
        return await self._repository.list_page(cursor, limit)

    async def get(self, session_id: UUID) -> SessionView:
        """Derive waiting and interrupted states without changing stored work.

        Args:
            session_id: The session to reopen.

        Returns:
            Its stored timeline, allowed actions and recoverable last input.

        Raises:
            SessionNotFoundError: No session has this id.
        """
        return self._view(await self._repository.get(session_id))

    async def act(self, session_id: UUID, request: ActionRequest) -> SessionView:
        """Validate, begin atomically, run one task and finish atomically.

        Args:
            session_id: The session the learner is answering.
            request: The action, displayed version and unnormalized input.

        Returns:
            A new view after exactly one version increment.

        Raises:
            SessionNotFoundError: No session exists.
            StaleSessionError: The learner answered an older version.
            ActionInProgressError: Live work already occupies this version.
            SessionEndedError: This is not a due wrap-up of an ended session.
            ActionNotAllowedError: The stage or extra guard rejects the action.
            InvalidInputError: The input kind, limit or reading is invalid.
            ActionCancelledError: Cancel or end superseded this action.
            ModelError: A provider failed; the input remains recoverable.
            ModelOutputInvalidError: The one repair still failed its checks.
        """
        stored = await self._repository.get(session_id)
        session = stored.session
        now = self._clock()
        if request.version != session.version:
            raise errors.StaleSessionError
        if (
            self._is_live(stored.last_submission)
            and request.action is not models.Action.END
        ):
            raise errors.ActionInProgressError
        if (
            session.status is models.SessionStatus.ENDED
            and request.action is not models.Action.WRAP_UP
        ):
            raise errors.SessionEndedError
        if request.action not in flow.allowed_actions(session):
            raise errors.ActionNotAllowedError(request.action, session.stage)
        normalized = flow.check_input(request.action, request.input)
        if isinstance(normalized, models.ReadingInput):
            reading = session.turn_state.reading
            if reading is None or normalized.reading not in tuple(
                option.strip() for option in reading.readings
            ):
                field = "reading"
                raise errors.InvalidInputError(
                    field, coaching.READING_OPTIONS, len(normalized.reading)
                )
        submission = models.Submission(
            self._new_id(),
            session_id,
            request.version,
            request.action,
            normalized,
            self._boot_id,
            now,
        )
        await self._repository.begin_submission(
            submission, flow.ACTION_STAGES[request.action], now - SUBMISSION_MAX_AGE
        )
        try:
            next_session, entries = await self._perform(stored, submission)
            finished = await self._repository.finish_submission(
                submission.id,
                replace(next_session, version=session.version + 1),
                entries,
                self._clock(),
            )
        except Exception as error:
            code = (
                error.code
                if isinstance(error, (ModelError, ModelOutputInvalidError))
                else "internal_error"
            )
            await self._repository.fail_submission(submission.id, code, self._clock())
            raise
        return self._view(finished)

    async def cancel(self, session_id: UUID, version: int) -> None:
        """Cancel only work sent at that version, without advancing the turn.

        Args:
            session_id: The session whose pending action is being abandoned.
            version: The base version sent with that action.

        Returns:
            None, including when this session has no pending work at that version.

        Raises:
            SessionNotFoundError: No session has this id.
        """
        await self._repository.cancel_submission(session_id, version, self._clock())

    def _is_live(self, submission: models.Submission | None) -> bool:
        return (
            submission is not None
            and submission.status is models.SubmissionStatus.PENDING
            and submission.boot_id == self._boot_id
            and submission.created_at >= self._clock() - SUBMISSION_MAX_AGE
        )

    def _view(self, stored: models.StoredSession) -> SessionView:
        session = stored.session
        last = stored.last_submission
        visible = None
        if last is not None and last.status in {
            models.SubmissionStatus.PENDING,
            models.SubmissionStatus.FAILED,
        }:
            state = models.LastSubmissionState.FAILED
            if last.status is models.SubmissionStatus.PENDING:
                state = (
                    models.LastSubmissionState.PENDING
                    if self._is_live(last)
                    else models.LastSubmissionState.INTERRUPTED
                )
            visible = models.LastSubmission(
                state,
                last.action,
                last.input,
                "interrupted"
                if state is models.LastSubmissionState.INTERRUPTED
                else last.failure_code,
            )
        return models.SessionView(
            session.id,
            session.status,
            session.stage,
            session.version,
            session.turn_index,
            session.finished_replies,
            session.started_at,
            session.ended_at,
            flow.allowed_actions(session),
            stored.entries,
            visible,
            session.wrap_up,
        )

    async def _perform(
        self, stored: models.StoredSession, submission: models.Submission
    ) -> tuple[models.Session, tuple[models.TimelineEntry, ...]]:
        work = _ActionWork(stored, submission, stored.session, [])
        match submission.action, submission.input:
            case models.Action.OPEN, models.NoInput():
                await self._open(work)
            case models.Action.INTENT, models.TextInput(text=text):
                await self._intent(work, text)
            case (
                (models.Action.ENGLISH | models.Action.ENGLISH_DIRECT),
                models.TextInput(text=text),
            ):
                is_direct = submission.action is models.Action.ENGLISH_DIRECT
                state = replace(
                    work.session.turn_state,
                    intent=None if is_direct else work.session.turn_state.intent,
                    english=text,
                    feedback=None,
                    reading=None,
                    retry_count=0,
                    practice=None,
                )
                work.session = replace(work.session, turn_state=state)
                self._append(
                    work,
                    models.EntryKind.ENGLISH,
                    models.EnglishPayload(text, is_direct),
                )
                await self._feedback(work, None)
            case models.Action.READING, models.ReadingInput(reading=chosen):
                question = work.session.turn_state.reading
                if question is None:
                    message = "Reading stage requires a reading question"
                    raise ValueError(message)
                reading = coaching.ReadingChoice(question.word, chosen)
                self._append(
                    work,
                    models.EntryKind.READING_CHOICE,
                    models.ReadingChoicePayload(reading.word, chosen),
                )
                await self._feedback(work, reading)
            case models.Action.RETRY, models.TextInput(text=text):
                await self._retry(work, text)
            case models.Action.SKIP, models.NoInput():
                self._append(work, models.EntryKind.SKIP, models.SkipPayload())
                self._finish_turn(work, models.TurnEnd.SKIPPED)
            case models.Action.PARTNER_REPLY, models.NoInput():
                await self._partner_reply(work)
            case models.Action.END, models.NoInput():
                self._end(work)
            case models.Action.WRAP_UP, models.NoInput():
                await self._wrap_up(work)
            case _:
                await self._control(work)
        return work.session, tuple(work.entries)

    async def _control(self, work: _ActionWork) -> None:
        match work.submission.action, work.submission.input:
            case models.Action.HINT, models.HintInput(gap=gap, partial_english=partial):
                await self._hint(work, gap, partial)
            case models.Action.SHOW_ANSWER, models.NoInput():
                await self._show_answer(work)
            case models.Action.TYPED_COPY, models.TextInput(text=text):
                self._append(
                    work, models.EntryKind.TYPED_COPY, models.TypedCopyPayload(text)
                )
                work.session = replace(
                    work.session,
                    turn_state=replace(work.session.turn_state, english=text),
                )
                self._finish_turn(work, models.TurnEnd.ANSWER_TYPED)
            case models.Action.RESTATE, models.RestateInput(mode=mode):
                await self._restate(work, mode)
            case models.Action.REWRITE_INTENT, models.TextInput(text=text):
                await self._intent(work, text, is_replacement=True)
            case models.Action.PRACTICE_AGAIN, models.TextInput(text=text):
                await self._practice(work, text)
            case models.Action.ASK, models.TextInput(text=text):
                await self._ask(work, text)
            case _:
                message = "Action and normalized input do not agree"
                raise ValueError(message)

    def _append(
        self,
        work: _ActionWork,
        kind: models.EntryKind,
        payload: models.EntryPayload,
        *,
        turn_index: int | None = None,
    ) -> None:
        work.entries.append(
            models.TimelineEntry(
                self._new_id(),
                work.session.id,
                len(work.stored.entries) + len(work.entries) + 1,
                work.session.turn_index if turn_index is None else turn_index,
                kind,
                payload,
                self._clock(),
            )
        )

    async def _run(
        self,
        work: _ActionWork,
        task: ModelTask,
        request: object,
        *,
        practice: bool = False,
    ) -> object:
        async def record(attempt: CallAttempt) -> None:
            await self._repository.record_model_call(
                models.ModelCallRecord(
                    self._new_id(),
                    work.session.id,
                    work.submission.id,
                    work.session.turn_index,
                    attempt,
                    self._clock(),
                )
            )
            await self._require_pending(work)

        await self._require_pending(work)
        result: TaskRun[object]
        if practice and isinstance(request, coaching.CheckRetryRequest):
            practice_result: TaskRun[coaching.RetryResult] = await run_model_task(
                task,
                self._coach.check_retry,
                _check_practice_result,
                request,
                record=record,
            )
            result = practice_result
        else:
            result = await MODEL_TASKS[task].run(
                self._partner, self._coach, request, record=record
            )
        if result.error is not None:
            raise result.error
        return result.output

    async def _require_pending(self, work: _ActionWork) -> None:
        current = (await self._repository.get(work.session.id)).last_submission
        if (
            current is None
            or current.id != work.submission.id
            or current.status is not models.SubmissionStatus.PENDING
        ):
            raise errors.ActionCancelledError

    async def _open(self, work: _ActionWork) -> None:
        previous = await self._repository.previous_opener(work.session.id)
        output = await self._run(work, ModelTask.OPEN, partner.OpenRequest(previous))
        if not isinstance(output, partner.PartnerLine):
            raise TypeError(_WRONG_OUTPUT)
        self._append(
            work,
            models.EntryKind.PARTNER_LINE,
            models.PartnerLinePayload(
                output.text,
                text_count_questions(output.text) > 0,
                models.LineKind.OPENER,
            ),
        )
        work.session = replace(
            work.session, opener=output.text, stage=models.Stage.INTENT
        )

    async def _intent(
        self, work: _ActionWork, text: str, *, is_replacement: bool = False
    ) -> None:
        practice = work.session.turn_state.practice if is_replacement else None
        work.session = replace(
            work.session, turn_state=models.TurnState(intent=text, practice=practice)
        )
        self._append(
            work, models.EntryKind.INTENT, models.IntentPayload(text, is_replacement)
        )
        output = await self._run(
            work,
            ModelTask.ACKNOWLEDGE,
            coaching.AcknowledgeRequest(text, _conversation(work)),
        )
        if not isinstance(output, coaching.Acknowledgment):
            raise TypeError(_WRONG_OUTPUT)
        self._append(
            work,
            models.EntryKind.ACKNOWLEDGMENT,
            models.AcknowledgmentPayload(output.line, output.build_hint),
        )
        work.session = replace(work.session, stage=models.Stage.ENGLISH)

    async def _feedback(
        self, work: _ActionWork, reading: coaching.ReadingChoice | None
    ) -> None:
        state = work.session.turn_state
        if state.english is None:
            message = "Feedback requires learner English"
            raise ValueError(message)
        earlier = tuple(
            entry.payload.text
            if isinstance(entry.payload, models.EnglishPayload)
            else entry.payload.sentence
            for entry in work.stored.entries
            if entry.turn_index < work.session.turn_index
            and isinstance(entry.payload, (models.EnglishPayload, models.RetryPayload))
        )
        request = coaching.FeedbackRequest(
            state.intent, state.english, reading, earlier, _conversation(work)
        )
        output = await self._run(work, ModelTask.FEEDBACK, request)
        if isinstance(output, coaching.ReadingQuestion):
            self._append(
                work,
                models.EntryKind.READING_QUESTION,
                models.ReadingQuestionPayload(output.word, output.readings),
            )
            work.session = replace(
                work.session,
                stage=models.Stage.READING_CHECK,
                turn_state=replace(state, reading=output),
            )
        elif isinstance(output, coaching.Feedback):
            self._append(
                work,
                models.EntryKind.FEEDBACK,
                models.FeedbackPayload(state.intent, output),
            )
            work.session = replace(
                work.session, turn_state=replace(state, feedback=output, reading=None)
            )
            next_stage = flow.after_feedback(output)
            if isinstance(next_stage, models.TurnEnd):
                self._finish_turn(work, next_stage)
            else:
                work.session = replace(work.session, stage=next_stage)
        else:
            raise TypeError(_WRONG_OUTPUT)

    async def _retry(self, work: _ActionWork, sentence: str) -> None:
        state = work.session.turn_state
        if state.feedback is None:
            message = "Retry requires feedback"
            raise ValueError(message)
        number = state.retry_count + 1
        self._append(
            work, models.EntryKind.RETRY, models.RetryPayload(sentence, number)
        )
        output = await self._run(
            work,
            ModelTask.CHECK_RETRY,
            coaching.CheckRetryRequest(
                state.intent, state.feedback, sentence, number, _conversation(work)
            ),
        )
        if not isinstance(
            output, (coaching.RetryAccepted, coaching.BlankOff, coaching.PieceGiven)
        ):
            raise TypeError(_WRONG_OUTPUT)
        self._append(
            work, models.EntryKind.RETRY_RESULT, models.RetryResultPayload(output)
        )
        work.session = replace(
            work.session,
            turn_state=replace(state, english=sentence, retry_count=number),
        )
        next_stage = flow.after_retry(output, number)
        if isinstance(next_stage, models.TurnEnd):
            self._finish_turn(work, next_stage)
        else:
            work.session = replace(work.session, stage=next_stage)

    def _finish_turn(self, work: _ActionWork, how: models.TurnEnd) -> None:
        english = _final_english(work)
        self._append(
            work, models.EntryKind.TURN_DONE, models.TurnDonePayload(english, how)
        )
        state = work.session.turn_state
        practice = (
            models.PracticeTarget(work.session.turn_index, state.intent, state.feedback)
            if state.feedback is not None and state.feedback.fixes
            else None
        )
        finished = work.session.finished_replies + 1
        stage = flow.after_turn_done(finished)
        work.session = replace(
            work.session,
            finished_replies=finished,
            stage=stage,
            turn_state=replace(state, practice=practice),
        )
        if stage is models.Stage.CHECK_IN:
            self._append(work, models.EntryKind.CHECK_IN, models.CheckInPayload())

    async def _partner_reply(self, work: _ActionWork) -> None:
        if work.session.stage is models.Stage.CHECK_IN:
            self._append(
                work,
                models.EntryKind.CHECK_IN_ANSWER,
                models.CheckInAnswerPayload(models.CheckInAnswer.CONTINUE),
            )
        output = await self._run(
            work,
            ModelTask.REPLY,
            partner.ReplyRequest(_conversation(work), _should_share(work)),
        )
        if not isinstance(output, partner.PartnerLine):
            raise TypeError(_WRONG_OUTPUT)
        work.session = replace(
            work.session,
            turn_index=work.session.turn_index + 1,
            turn_state=models.TurnState(practice=work.session.turn_state.practice),
            stage=models.Stage.INTENT,
        )
        self._append(
            work,
            models.EntryKind.PARTNER_LINE,
            models.PartnerLinePayload(
                output.text,
                text_count_questions(output.text) > 0,
                models.LineKind.REPLY,
            ),
        )

    def _end(self, work: _ActionWork) -> None:
        if work.session.stage is models.Stage.CHECK_IN:
            self._append(
                work,
                models.EntryKind.CHECK_IN_ANSWER,
                models.CheckInAnswerPayload(models.CheckInAnswer.END),
            )
        has_feedback = any(
            entry.kind is models.EntryKind.FEEDBACK for entry in work.stored.entries
        )
        work.session = replace(
            work.session,
            status=models.SessionStatus.ENDED,
            stage=models.Stage.ENDED,
            ended_at=self._clock(),
            wrap_up=None if has_feedback else coaching.WrapUp(()),
        )

    async def _wrap_up(self, work: _ActionWork) -> None:
        feedbacks = tuple(
            entry.payload.feedback
            for entry in work.stored.entries
            if isinstance(entry.payload, models.FeedbackPayload)
        )
        output = await self._run(
            work,
            ModelTask.WRAP_UP,
            coaching.WrapUpRequest(feedbacks, _conversation(work)),
        )
        if not isinstance(output, coaching.WrapUp):
            raise TypeError(_WRONG_OUTPUT)
        work.session = replace(work.session, wrap_up=output)

    async def _hint(self, work: _ActionWork, gap: str, partial: str) -> None:
        intent = work.session.turn_state.intent
        if intent is None:
            message = "A gap hint requires an intent"
            raise ValueError(message)
        request = coaching.GapHintRequest(
            intent, gap, partial, _earlier_hints(work), _conversation(work)
        )
        self._append(
            work, models.EntryKind.HINT_REQUEST, models.HintRequestPayload(gap, partial)
        )
        output = await self._run(work, ModelTask.GAP_HINT, request)
        if not isinstance(output, coaching.GapHint):
            raise TypeError(_WRONG_OUTPUT)
        self._append(
            work, models.EntryKind.GAP_HINT, models.GapHintPayload(output.hint)
        )

    async def _show_answer(self, work: _ActionWork) -> None:
        state = work.session.turn_state
        request = coaching.ShowAnswerRequest(
            work.session.stage,
            state.intent,
            state.english,
            state.feedback,
            _conversation(work),
        )
        output = await self._run(work, ModelTask.SHOW_ANSWER, request)
        if not isinstance(output, coaching.Answer):
            raise TypeError(_WRONG_OUTPUT)
        self._append(
            work, models.EntryKind.ANSWER, models.AnswerPayload(output.example)
        )
        work.session = replace(
            work.session,
            stage=models.Stage.ANSWER_SHOWN,
            turn_state=replace(state, shown_answer=output.example),
        )

    async def _restate(self, work: _ActionWork, mode: models.RestateMode) -> None:
        lines = [
            entry.payload
            for entry in work.stored.entries
            if isinstance(entry.payload, models.PartnerLinePayload)
            and entry.payload.line_kind
            in {models.LineKind.OPENER, models.LineKind.REPLY}
        ]
        if not lines:
            message = "Restatement requires an original Partner line"
            raise ValueError(message)
        output = await self._run(
            work,
            ModelTask.RESTATE,
            partner.RestateRequest(_conversation(work), lines[-1].text, mode),
        )
        if not isinstance(output, partner.PartnerLine):
            raise TypeError(_WRONG_OUTPUT)
        self._append(
            work,
            models.EntryKind.PARTNER_LINE,
            models.PartnerLinePayload(
                output.text,
                text_count_questions(output.text) > 0,
                models.LineKind.RESTATEMENT,
                mode,
            ),
        )

    async def _practice(self, work: _ActionWork, sentence: str) -> None:
        target = work.session.turn_state.practice
        if target is None:
            message = "Practice requires a finished turn with a fix"
            raise ValueError(message)
        self._append(
            work,
            models.EntryKind.PRACTICE,
            models.PracticePayload(target.turn_index, sentence),
            turn_index=target.turn_index,
        )
        output = await self._run(
            work,
            ModelTask.CHECK_RETRY,
            coaching.CheckRetryRequest(
                target.intent, target.feedback, sentence, 1, _conversation(work)
            ),
            practice=True,
        )
        if not isinstance(output, (coaching.RetryAccepted, coaching.BlankOff)):
            raise TypeError(_WRONG_OUTPUT)
        self._append(
            work,
            models.EntryKind.PRACTICE_RESULT,
            models.PracticeResultPayload(target.turn_index, output),
            turn_index=target.turn_index,
        )

    async def _ask(self, work: _ActionWork, question: str) -> None:
        state = work.session.turn_state
        self._append(work, models.EntryKind.QUESTION, models.QuestionPayload(question))
        request = coaching.AnswerQuestionRequest(
            question,
            work.session.stage,
            state.intent,
            state.english,
            state.feedback,
            _conversation(work),
        )
        output = await self._run(work, ModelTask.ANSWER_QUESTION, request)
        if not isinstance(output, coaching.CoachAnswer):
            raise TypeError(_WRONG_OUTPUT)
        self._append(
            work, models.EntryKind.COACH_ANSWER, models.CoachAnswerPayload(output.text)
        )


SUBMISSION_MAX_AGE = timedelta(seconds=150)
_WRONG_OUTPUT = "Model returned a value for a different task"
_SHARE_AFTER = 2


def _check_practice_result(
    request: coaching.CheckRetryRequest, output: coaching.RetryResult
) -> tuple[Violation, ...]:
    violations = coaching.check_retry_result(request, output)
    if isinstance(output, coaching.PieceGiven):
        violations += (
            Violation(
                CheckId.SCHEMA,
                "Practice accepts a confirmation or a first-submission hint, never second-submission pieces",
            ),
        )
    return violations


@dataclass(slots=True)
class _ActionWork:
    """Only an action's local draft mutates before atomic repository completion."""

    stored: models.StoredSession
    submission: models.Submission
    session: models.Session
    entries: list[models.TimelineEntry]


def _conversation(work: _ActionWork) -> tuple[models.ConversationLine, ...]:
    lines: list[models.ConversationLine] = []
    for entry in (*work.stored.entries, *work.entries):
        if (
            isinstance(entry.payload, models.PartnerLinePayload)
            and entry.payload.line_kind is not models.LineKind.RESTATEMENT
        ):
            lines.append(
                models.ConversationLine(models.Speaker.PARTNER, entry.payload.text)
            )
        elif isinstance(entry.payload, models.TurnDonePayload):
            lines.append(
                models.ConversationLine(models.Speaker.LEARNER, entry.payload.english)
            )
    return tuple(lines)


def _should_share(work: _ActionWork) -> bool:
    entries = (*work.stored.entries, *work.entries)
    lines = [
        (index, entry.payload)
        for index, entry in enumerate(entries)
        if isinstance(entry.payload, models.PartnerLinePayload)
        and entry.payload.line_kind is not models.LineKind.RESTATEMENT
    ]
    if len(lines) < _SHARE_AFTER:
        return False
    for position in range(len(lines) - _SHARE_AFTER, len(lines)):
        index, line = lines[position]
        stop = lines[position + 1][0] if position + 1 < len(lines) else len(entries)
        if not line.has_question or not any(
            entry.kind is models.EntryKind.TURN_DONE
            for entry in entries[index + 1 : stop]
        ):
            return False
    return True


def _current_intent_entries(work: _ActionWork) -> tuple[models.TimelineEntry, ...]:
    entries = tuple(
        entry
        for entry in (*work.stored.entries, *work.entries)
        if entry.turn_index == work.session.turn_index
    )
    start = max(
        (
            index + 1
            for index, entry in enumerate(entries)
            if entry.kind is models.EntryKind.INTENT
        ),
        default=0,
    )
    return entries[start:]


def _earlier_hints(work: _ActionWork) -> tuple[coaching.EarlierHint, ...]:
    pairs: list[coaching.EarlierHint] = []
    gap: str | None = None
    for entry in _current_intent_entries(work):
        if isinstance(entry.payload, models.HintRequestPayload):
            gap = entry.payload.gap
        elif isinstance(entry.payload, models.GapHintPayload) and gap is not None:
            pairs.append(coaching.EarlierHint(gap, entry.payload.hint))
            gap = None
    return tuple(pairs)


def _final_english(work: _ActionWork) -> str:
    current = _current_intent_entries(work)
    english = (
        work.session.turn_state.english or work.session.turn_state.shown_answer or ""
    )
    for entry in current:
        if isinstance(entry.payload, (models.EnglishPayload, models.TypedCopyPayload)):
            english = entry.payload.text
        elif isinstance(entry.payload, models.RetryPayload):
            english = entry.payload.sentence
    for entry in current:
        notes: tuple[coaching.ReadingNote, ...] = ()
        if isinstance(entry.payload, models.FeedbackPayload):
            notes = entry.payload.feedback.readings_noted
        elif isinstance(entry.payload, models.RetryResultPayload) and isinstance(
            entry.payload.result, (coaching.RetryAccepted, coaching.BlankOff)
        ):
            notes = entry.payload.result.readings_noted
        elif isinstance(entry.payload, models.ReadingChoicePayload):
            notes = (coaching.ReadingNote(entry.payload.word, entry.payload.chosen),)
        for note in notes:
            english = _apply_reading(english, note)
    return english


def _apply_reading(english: str, note: coaching.ReadingNote) -> str:
    def replacement(_match: re.Match[str]) -> str:
        return note.read_as.strip()

    # An apostrophe joins word characters inside a contraction, but a quote
    # surrounding a standalone word must not prevent its replacement.
    pattern = rf"(?<!\w)(?<!\w['\u2019]){re.escape(note.written.strip())}(?!\w)(?!['\u2019]\w)"
    return re.sub(pattern, replacement, english)
