from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING

import anyio
import pytest

from intent_to_english.adapters import memory
from intent_to_english.core.errors import (
    ActionCancelledError,
    ActionInProgressError,
    ActionNotAllowedError,
    InvalidCursorError,
    SessionEndedError,
    SessionNotFoundError,
    StaleSessionError,
)
from intent_to_english.core.models import (
    Action,
    CallAttempt,
    CallOutcome,
    EntryKind,
    LineKind,
    ModelCallRecord,
    ModelRole,
    ModelTask,
    NoInput,
    PartnerLinePayload,
    Session,
    SessionStatus,
    Stage,
    Submission,
    SubmissionStatus,
    TimelineEntry,
    Usage,
)
from intent_to_english.core.ports import SessionRepository

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


@asynccontextmanager
async def _in_memory(_: Path) -> AsyncIterator[SessionRepository]:
    yield memory.InMemorySessionRepository()


REPOSITORY_FACTORIES = [pytest.param(_in_memory, id="in-memory")]

pytestmark = pytest.mark.anyio


@pytest.fixture(params=REPOSITORY_FACTORIES)
async def repository(request, tmp_path):
    async with request.param(tmp_path) as built:
        yield built


@pytest.fixture
def session(fixed_now, nth_id):
    return Session(nth_id(1), fixed_now)


@pytest.fixture
def submission(session, fixed_now, nth_id):
    return Submission(
        nth_id(2), session.id, 0, Action.OPEN, NoInput(), nth_id(99), fixed_now
    )


async def test_create_and_get_are_snapshots_and_duplicate_create_never_overwrites(
    repository, session
):
    assert isinstance(repository, SessionRepository)
    stored = await repository.create(session)
    assert stored.session == session
    assert stored.entries == ()
    assert await repository.get(session.id) == stored
    with pytest.raises(ValueError, match="already stored"):
        await repository.create(replace(session, version=1))
    assert (await repository.get(session.id)).session.version == 0


async def test_begin_rejects_unknown_stale_live_ended_and_wrong_stage_in_order(
    repository, session, submission, fixed_now
):
    with pytest.raises(SessionNotFoundError, match="not found"):
        await repository.begin_submission(
            submission, frozenset({Stage.OPENING}), fixed_now
        )
    await repository.create(session)
    with pytest.raises(StaleSessionError, match="version"):
        await repository.begin_submission(
            replace(submission, base_version=1), frozenset(), fixed_now
        )
    with pytest.raises(ActionNotAllowedError, match="not allowed"):
        await repository.begin_submission(
            submission, frozenset({Stage.INTENT}), fixed_now
        )
    await repository.begin_submission(submission, frozenset({Stage.OPENING}), fixed_now)
    with pytest.raises(ActionInProgressError, match="progress"):
        await repository.begin_submission(submission, frozenset(), fixed_now)


async def test_concurrent_begin_processes_exactly_one_submission(
    repository, session, submission, fixed_now, nth_id
):
    await repository.create(session)
    successes = []
    conflicts = []

    async def begin(index):
        try:
            await repository.begin_submission(
                replace(submission, id=nth_id(index + 2)),
                frozenset({Stage.OPENING}),
                fixed_now,
            )
            successes.append(index)
        except ActionInProgressError:
            conflicts.append(index)

    async with anyio.create_task_group() as tasks:
        for index in range(50):
            tasks.start_soon(begin, index)
    assert len(successes) == 1
    assert len(conflicts) == 49


async def test_cancel_discards_late_output_without_changing_the_session(
    repository, session, submission, fixed_now
):
    await repository.create(session)
    assert (
        await repository.cancel_submission(session.id, session.version, fixed_now)
        is False
    )
    await repository.begin_submission(submission, frozenset({Stage.OPENING}), fixed_now)
    assert (
        await repository.cancel_submission(session.id, session.version, fixed_now)
        is True
    )
    with pytest.raises(ActionCancelledError, match="cancelled"):
        await repository.finish_submission(
            submission.id, replace(session, version=1), (), fixed_now
        )
    assert (await repository.get(session.id)).session == session
    await repository.fail_submission(submission.id, "model_timeout", fixed_now)
    assert (
        await repository.get(session.id)
    ).last_submission.status is SubmissionStatus.CANCELLED


@pytest.mark.parametrize(
    "interruption",
    [pytest.param("boot", id="another-boot"), pytest.param("age", id="expired")],
)
async def test_interrupted_submission_releases_the_same_version(
    repository, session, submission, nth_id, interruption
):
    fixed_now = submission.created_at
    await repository.create(session)
    await repository.begin_submission(submission, frozenset({Stage.OPENING}), fixed_now)
    boot = {"boot": nth_id(100), "age": submission.boot_id}[interruption]
    cutoff = {"boot": fixed_now, "age": fixed_now + timedelta(seconds=1)}[interruption]
    replacement = replace(submission, id=nth_id(3), boot_id=boot)
    await repository.begin_submission(replacement, frozenset({Stage.OPENING}), cutoff)
    assert (await repository.get(session.id)).last_submission == replacement
    with pytest.raises(ActionCancelledError, match="cancelled"):
        await repository.finish_submission(
            submission.id, replace(session, version=1), (), fixed_now
        )


async def test_finish_appends_in_order_and_rejects_duplicate_seq_atomically(
    repository, session, submission, fixed_now, nth_id
):
    await repository.create(session)
    await repository.begin_submission(submission, frozenset({Stage.OPENING}), fixed_now)
    entry = TimelineEntry(
        nth_id(3),
        session.id,
        1,
        1,
        EntryKind.PARTNER_LINE,
        PartnerLinePayload("Hi!", False, LineKind.OPENER),
        fixed_now,
    )
    stored = await repository.finish_submission(
        submission.id,
        replace(session, version=1, stage=Stage.INTENT, opener="Hi!"),
        (entry,),
        fixed_now,
    )
    assert stored.entries == (entry,)
    assert stored.session.version == 1
    second = replace(submission, id=nth_id(4), base_version=1, action=Action.INTENT)
    await repository.begin_submission(second, frozenset({Stage.INTENT}), fixed_now)
    with pytest.raises(ValueError, match="timeline"):
        await repository.finish_submission(
            second.id, replace(stored.session, version=2), (entry,), fixed_now
        )
    assert (await repository.get(session.id)).session.version == 1
    assert (
        await repository.get(session.id)
    ).last_submission.status is SubmissionStatus.PENDING


async def test_failed_submission_can_retry_at_the_same_version(
    repository, session, submission, fixed_now, nth_id
):
    await repository.create(session)
    await repository.begin_submission(submission, frozenset({Stage.OPENING}), fixed_now)
    await repository.fail_submission(submission.id, "model_timeout", fixed_now)
    assert (
        await repository.get(session.id)
    ).last_submission.failure_code == "model_timeout"
    retry = replace(submission, id=nth_id(3))
    await repository.begin_submission(retry, frozenset({Stage.OPENING}), fixed_now)
    await repository.fail_submission(submission.id, "other", fixed_now)
    assert (await repository.get(session.id)).last_submission == retry


async def test_list_pages_newest_first_and_previous_opener_skips_empty(
    repository, session, nth_id
):
    await repository.create(session)
    await repository.create(replace(session, id=nth_id(2), opener="Earlier"))
    await repository.create(replace(session, id=nth_id(3)))
    page = await repository.list_page(None, 2)
    assert tuple(item.id for item in page.items) == (nth_id(3), nth_id(2))
    assert page.next_cursor is not None
    last = await repository.list_page(page.next_cursor, 2)
    assert tuple(item.id for item in last.items) == (nth_id(1),)
    assert last.next_cursor is None
    assert await repository.previous_opener(nth_id(4)) == "Earlier"
    assert await repository.previous_opener(nth_id(2)) is None


async def test_record_model_calls_survive_cancel_and_keep_accounting(
    repository, session, submission, fixed_now, nth_id
):
    await repository.create(session)
    await repository.begin_submission(submission, frozenset({Stage.OPENING}), fixed_now)
    record = ModelCallRecord(
        nth_id(3),
        session.id,
        submission.id,
        1,
        CallAttempt(
            ModelRole.PARTNER,
            ModelTask.OPEN,
            1,
            Usage("fixed", "fixed", None, None, None, 0),
            CallOutcome.OK,
        ),
        fixed_now,
    )
    await repository.record_model_call(record)
    await repository.cancel_submission(session.id, session.version, fixed_now)
    assert await repository.model_calls(session.id) == (record,)
    with pytest.raises(ValueError, match="already stored"):
        await repository.record_model_call(record)


async def test_begin_ended_session_and_duplicate_submission_preserve_snapshot(
    repository, session, submission, fixed_now
):
    ended = replace(
        session, status=SessionStatus.ENDED, stage=Stage.ENDED, ended_at=fixed_now
    )
    await repository.create(ended)
    with pytest.raises(SessionEndedError, match="ended"):
        await repository.begin_submission(submission, frozenset(), fixed_now)
    assert (await repository.get(session.id)).last_submission is None


@pytest.mark.parametrize(
    "cursor",
    [
        pytest.param("invalid", id="malformed"),
        pytest.param("A" * 22, id="todo-family"),
        pytest.param("session:!", id="bad-session"),
    ],
)
async def test_list_rejects_invalid_cursor_without_echo(repository, cursor):
    with pytest.raises(InvalidCursorError, match="Invalid page cursor"):
        await repository.list_page(cursor, 2)


async def test_list_rejects_nonpositive_limit_but_allows_large_positive_limit(
    repository,
):
    with pytest.raises(InvalidCursorError, match="Invalid page cursor"):
        await repository.list_page(None, 0)
    assert (await repository.list_page(None, 1001)).items == ()


async def test_cancel_names_the_pending_version_and_ignores_other_versions(
    repository, session, submission, fixed_now
):
    await repository.create(session)
    await repository.begin_submission(submission, frozenset({Stage.OPENING}), fixed_now)
    assert await repository.cancel_submission(session.id, 1, fixed_now) is False
    assert (await repository.get(session.id)).last_submission == submission
    assert await repository.cancel_submission(session.id, 0, fixed_now) is True
    assert (
        await repository.get(session.id)
    ).last_submission.status is SubmissionStatus.CANCELLED


async def test_end_supersedes_live_pending_and_discards_its_late_output(
    repository, session, submission, fixed_now, nth_id
):
    await repository.create(session)
    await repository.begin_submission(submission, frozenset({Stage.OPENING}), fixed_now)
    ending = replace(submission, id=nth_id(3), action=Action.END)
    await repository.begin_submission(ending, frozenset({Stage.OPENING}), fixed_now)
    assert (await repository.get(session.id)).last_submission == ending
    with pytest.raises(ActionCancelledError, match="cancelled"):
        await repository.finish_submission(
            submission.id, replace(session, version=1), (), fixed_now
        )
    assert (await repository.get(session.id)).session == session


@pytest.mark.parametrize(
    "reason",
    [pytest.param("stale", id="stale-end"), pytest.param("stage", id="disallowed-end")],
)
async def test_refused_end_never_cancels_a_live_submission(
    repository, session, submission, nth_id, reason
):
    now = submission.created_at
    await repository.create(session)
    await repository.begin_submission(submission, frozenset({Stage.OPENING}), now)
    ending = replace(
        submission,
        id=nth_id(3),
        action=Action.END,
        base_version={"stale": 1, "stage": 0}[reason],
    )
    allowed = {"stale": frozenset({Stage.OPENING}), "stage": frozenset()}[reason]
    error = {"stale": StaleSessionError, "stage": ActionNotAllowedError}[reason]
    with pytest.raises(error, match=r"version|not allowed"):
        await repository.begin_submission(ending, allowed, now)
    assert (await repository.get(session.id)).last_submission == submission
    stored = await repository.finish_submission(
        submission.id, replace(session, version=1), (), now
    )
    assert stored.session.version == 1


async def test_ended_allows_wrap_up_but_a_refused_end_keeps_it_pending(
    repository, session, submission, fixed_now, nth_id
):
    ended = replace(
        session, status=SessionStatus.ENDED, stage=Stage.ENDED, ended_at=fixed_now
    )
    await repository.create(ended)
    wrapping = replace(submission, action=Action.WRAP_UP)
    await repository.begin_submission(wrapping, frozenset({Stage.ENDED}), fixed_now)
    ending = replace(submission, id=nth_id(3), action=Action.END)
    with pytest.raises(SessionEndedError, match="ended"):
        await repository.begin_submission(ending, frozenset({Stage.ENDED}), fixed_now)
    assert (await repository.get(session.id)).last_submission == wrapping
