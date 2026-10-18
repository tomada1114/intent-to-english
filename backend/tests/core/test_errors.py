from __future__ import annotations

import pickle
import re
from uuid import UUID

import pytest

from intent_to_english.core import errors
from intent_to_english.core.errors import (
    AppError,
    InvalidCursorError,
    InvalidPageLimitError,
    InvalidTodoError,
    TodoNotFoundError,
)
from intent_to_english.core.models import Action, ModelTask, Stage

SOME_ID = UUID("01900000-0000-7000-8000-00000000002a")

SESSION_ERRORS = [
    pytest.param(errors.SessionNotFoundError(SOME_ID), id="session-not-found"),
    pytest.param(errors.StaleSessionError(), id="stale"),
    pytest.param(errors.ActionInProgressError(), id="in-progress"),
    pytest.param(
        errors.ActionNotAllowedError(Action.OPEN, Stage.INTENT), id="action-not-allowed"
    ),
    pytest.param(errors.SessionEndedError(), id="ended"),
    pytest.param(errors.ActionCancelledError(), id="cancelled"),
    pytest.param(errors.InvalidInputError("text", 1000, 1001), id="invalid-input"),
    pytest.param(errors.ModelError("test", "model", 0), id="model"),
    pytest.param(errors.ModelTimeoutError("test", "model", 60000), id="timeout"),
    pytest.param(errors.ModelRateLimitedError("test", "model", 1), id="rate-limit"),
    pytest.param(errors.ModelUnavailableError("test", "model", 1), id="unavailable"),
    pytest.param(
        errors.ModelOutputInvalidError(ModelTask.FEEDBACK), id="output-invalid"
    ),
]


@pytest.mark.parametrize(
    "error",
    [
        *SESSION_ERRORS,
        pytest.param(TodoNotFoundError(SOME_ID), id="not-found"),
        pytest.param(InvalidTodoError("bad title"), id="invalid"),
        pytest.param(InvalidCursorError("bad cursor"), id="invalid-cursor"),
        pytest.param(InvalidPageLimitError("bad limit"), id="invalid-page-limit"),
    ],
)
def test_domain_error_is_an_app_error(error):
    assert isinstance(error, AppError)


def test_todo_not_found_error_keeps_the_missing_id_and_names_it():
    error = TodoNotFoundError(SOME_ID)

    assert error.todo_id == SOME_ID
    assert str(error) == "To-do 01900000-0000-7000-8000-00000000002a not found"


@pytest.mark.parametrize(
    "error",
    [
        *SESSION_ERRORS,
        pytest.param(TodoNotFoundError(SOME_ID), id="not-found"),
        pytest.param(InvalidTodoError("bad title"), id="invalid"),
        pytest.param(InvalidCursorError("bad cursor"), id="invalid-cursor"),
        pytest.param(InvalidPageLimitError("bad limit"), id="invalid-page-limit"),
    ],
)
def test_domain_error_pickle_round_trip_keeps_type_message_and_args(error):
    restored = pickle.loads(pickle.dumps(error))  # noqa: S301 - our own bytes, made one line above

    assert type(restored) is type(error)
    assert str(restored) == str(error)
    assert restored.args == error.args


def test_todo_not_found_error_pickle_round_trip_keeps_the_id():
    restored = pickle.loads(pickle.dumps(TodoNotFoundError(SOME_ID)))  # noqa: S301 - our own bytes

    assert restored.todo_id == SOME_ID


def test_every_app_error_declares_its_own_unique_code():
    pending = [AppError]
    codes: set[str] = set()
    while pending:
        error_type = pending.pop()
        pending.extend(error_type.__subclasses__())
        if not error_type.__module__.startswith("intent_to_english."):
            continue
        assert "code" in error_type.__dict__, error_type.__name__
        code = error_type.code
        assert re.fullmatch(r"[a-z][a-z0-9_]*", code), error_type.__name__
        assert code not in codes, code
        codes.add(code)


def test_session_error_preserves_safe_attributes_and_pickle_args():
    error = errors.SessionNotFoundError(SOME_ID)
    assert error.session_id == SOME_ID
    assert str(error) == f"Session {SOME_ID} not found"
