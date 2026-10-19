"""Domain errors, each a subclass of one package base exception.

An entry point translates these into its own vocabulary (the API into an
HTTP status), so the core never needs to know which one called it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from uuid import UUID

    from intent_to_english.core.models import Action, ModelTask, Stage


class AppError(Exception):
    """Base class for every error the application raises on purpose.

    Catching it separates an expected domain failure, which an entry point
    reports to its user, from a bug, which should surface as a traceback.
    """

    code: ClassVar[str] = "app_error"


class InvalidCursorError(AppError):
    """Raised when a page cursor is not one the store issued.

    The message never echoes the cursor: it is client input of any length.
    """

    code: ClassVar[str] = "invalid_cursor"


class InvalidPageLimitError(AppError):
    """Raised when a page would hold fewer than one item or more than the maximum."""

    code: ClassVar[str] = "invalid_page_limit"


class ActionInProgressError(AppError):
    """An action is already in progress."""

    code: ClassVar[str] = "action_in_progress"

    def __str__(self) -> str:
        """Return a safe explanation for the client."""
        return "An action is already in progress"


class StaleSessionError(AppError):
    """The session version has changed."""

    code: ClassVar[str] = "stale_session"

    def __str__(self) -> str:
        """Return a safe explanation for the client."""
        return "The session version has changed"


class SessionEndedError(AppError):
    """The session has ended."""

    code: ClassVar[str] = "session_ended"

    def __str__(self) -> str:
        """Return a safe explanation for the client."""
        return "The session has ended"


class ActionCancelledError(AppError):
    """The action was cancelled."""

    code: ClassVar[str] = "action_cancelled"

    def __str__(self) -> str:
        """Return a safe explanation for the client."""
        return "The action was cancelled"


class SessionNotFoundError(AppError):
    """No session has the requested id."""

    code: ClassVar[str] = "session_not_found"

    def __init__(self, session_id: UUID) -> None:
        """Keep exactly the arguments needed to rebuild this error."""
        super().__init__(session_id)
        self.session_id = session_id

    def __str__(self) -> str:
        """Name the missing session without exposing its content."""
        return f"Session {self.session_id} not found"


class ActionNotAllowedError(AppError):
    """A known action cannot run at the current stage."""

    code: ClassVar[str] = "action_not_allowed"

    def __init__(self, action: Action, stage: Stage) -> None:
        """Retain the action and stage for callers and pickle."""
        super().__init__(action, stage)
        self.action = action
        self.stage = stage

    def __str__(self) -> str:
        """Explain the conflict without input text."""
        return f"Action {self.action} is not allowed at {self.stage}"


class InvalidInputError(AppError):
    """An action input has the wrong kind or length."""

    code: ClassVar[str] = "invalid_input"

    def __init__(self, field: str, limit: int, length: int) -> None:
        """Keep bounds and length rather than the learner text."""
        super().__init__(field, limit, length)
        self.field = field
        self.limit = limit
        self.length = length

    def __str__(self) -> str:
        """Report a safe field error, including kind mismatches."""
        return f"Invalid {self.field}: limit {self.limit}, length {self.length}"


class ModelError(AppError):
    """A model request failed without returning a checkable value."""

    code: ClassVar[str] = "model_error"

    def __init__(self, provider: str, model: str, latency_ms: int) -> None:
        """Preserve the accounting of the failed call, never its payload."""
        super().__init__(provider, model, latency_ms)
        self.provider = provider
        self.model = model
        self.latency_ms = latency_ms

    def __str__(self) -> str:
        """The stable code is sufficient; provider exceptions stay private."""
        return self.code.replace("_", " ").capitalize()


class ModelTimeoutError(ModelError):
    """A model call ended with model timeout."""

    code: ClassVar[str] = "model_timeout"


class ModelRateLimitedError(ModelError):
    """A model call ended with model rate limited."""

    code: ClassVar[str] = "model_rate_limited"


class ModelUnavailableError(ModelError):
    """A model call ended with model unavailable."""

    code: ClassVar[str] = "model_unavailable"


class ModelOutputInvalidError(AppError):
    """The output still violates its checks after the one repair."""

    code: ClassVar[str] = "model_output_invalid"

    def __init__(self, task: ModelTask) -> None:
        """Keep the task so the caller can choose the affected pane."""
        super().__init__(task)
        self.task = task

    def __str__(self) -> str:
        """Do not expose the output that failed its checks."""
        return f"Model output for {self.task} failed its checks"
