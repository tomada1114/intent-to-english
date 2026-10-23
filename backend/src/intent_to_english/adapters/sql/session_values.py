"""Convert SQL rows and JSON documents to immutable conversation values.

``Any`` is confined to SQLAlchemy's dynamic rows and JSON mappings here. Every
read rebuilds the core constructors, including nested unions and enum members.
Missing optional JSON fields use the core defaults so older payloads stay readable.
"""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from intent_to_english.core import coaching, models

if TYPE_CHECKING:
    from sqlalchemy import RowMapping


def session_values(session: models.Session) -> dict[str, Any]:
    """Return the column values, retaining None for SQL NULL wrap-up."""
    return asdict(session)


def session_from(row: RowMapping) -> models.Session:
    """Restore a session and every nested piece of its working state."""
    data = dict(row)
    data["status"] = models.SessionStatus(data["status"])
    data["stage"] = models.Stage(data["stage"])
    data["turn_state"] = _state(data["turn_state"])
    if data["wrap_up"] is not None:
        data["wrap_up"] = coaching.WrapUp(
            tuple(coaching.WrapUpItem(**item) for item in data["wrap_up"]["items"])
        )
    return models.Session(**data)


def entry_values(entry: models.TimelineEntry) -> dict[str, Any]:
    """Serialize a timeline entry without changing its payload fields."""
    return asdict(entry)


def entry_from(row: RowMapping) -> models.TimelineEntry:
    """Dispatch by the stored kind, then restore nested typed payloads."""
    data = dict(row)
    kind = models.EntryKind(data["kind"])
    payload = dict(data["payload"])
    if kind is models.EntryKind.PARTNER_LINE:
        payload["line_kind"] = models.LineKind(payload["line_kind"])
        if payload.get("restate_mode") is not None:
            payload["restate_mode"] = models.RestateMode(payload["restate_mode"])
    elif kind is models.EntryKind.READING_QUESTION:
        payload["readings"] = tuple(payload["readings"])
    elif kind is models.EntryKind.FEEDBACK:
        payload["feedback"] = _feedback(payload["feedback"])
    elif kind in {models.EntryKind.RETRY_RESULT, models.EntryKind.PRACTICE_RESULT}:
        payload["result"] = _retry(payload["result"])
    elif kind is models.EntryKind.TURN_DONE:
        payload["end"] = models.TurnEnd(payload["end"])
    elif kind is models.EntryKind.CHECK_IN_ANSWER:
        payload["answer"] = models.CheckInAnswer(payload["answer"])
    data["kind"] = kind
    data["payload"] = models.ENTRY_PAYLOAD_TYPES[kind](**payload)
    return models.TimelineEntry(**data)


def submission_values(submission: models.Submission) -> dict[str, Any]:
    """Keep the normalized learner input in its JSON column."""
    return asdict(submission)


def submission_from(row: RowMapping) -> models.Submission:
    """Restore the input by its shape, independently of the submitted action."""
    data = dict(row)
    data["action"] = models.Action(data["action"])
    data["status"] = models.SubmissionStatus(data["status"])
    value = data["input"]
    if "text" in value:
        data["input"] = models.TextInput(**value)
    elif "gap" in value:
        data["input"] = models.HintInput(**value)
    elif "reading" in value:
        data["input"] = models.ReadingInput(**value)
    elif "mode" in value:
        data["input"] = models.RestateInput(models.RestateMode(value["mode"]))
    else:
        data["input"] = models.NoInput()
    return models.Submission(**data)


def call_values(record: models.ModelCallRecord) -> dict[str, Any]:
    """Flatten one attempt into accounting columns, preserving Decimal text."""
    call = record.call
    usage = call.usage
    return {
        "id": record.id,
        "session_id": record.session_id,
        "submission_id": record.submission_id,
        "turn_index": record.turn_index,
        "role": call.role,
        "task": call.task,
        "attempt": call.attempt,
        "provider": usage.provider,
        "model": usage.model,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cost": str(usage.cost) if usage.cost is not None else None,
        "latency_ms": usage.latency_ms,
        "outcome": call.outcome,
        "status": call.status,
        "violations": [asdict(item) for item in call.violations],
        "created_at": record.created_at,
    }


def call_from(row: RowMapping) -> models.ModelCallRecord:
    """Restore accounting without storing prompt text or provider secrets."""
    usage = models.Usage(
        row["provider"],
        row["model"],
        row["input_tokens"],
        row["output_tokens"],
        Decimal(row["cost"]) if row["cost"] is not None else None,
        row["latency_ms"],
    )
    call = models.CallAttempt(
        models.ModelRole(row["role"]),
        models.ModelTask(row["task"]),
        row["attempt"],
        usage,
        models.CallOutcome(row["outcome"]),
        tuple(
            models.Violation(models.CheckId(item["check"]), item["detail"])
            for item in row["violations"]
        ),
        status=row["status"],
    )
    return models.ModelCallRecord(
        row["id"],
        row["session_id"],
        row["submission_id"],
        row["turn_index"],
        call,
        row["created_at"],
    )


def _notes(
    values: list[dict[str, Any]] | tuple[()] = (),
) -> tuple[coaching.ReadingNote, ...]:
    return tuple(coaching.ReadingNote(**value) for value in values)


def _feedback(value: dict[str, Any]) -> coaching.Feedback:
    data = dict(value)
    data["fixes"] = tuple(
        coaching.Fix(**{**fix, "tag": models.FixTag(fix["tag"])})
        for fix in data.get("fixes", ())
    )
    data["readings_noted"] = _notes(data.get("readings_noted", ()))
    return coaching.Feedback(**data)


def _retry(value: dict[str, Any]) -> coaching.RetryResult:
    data = dict(value)
    if "pieces" in data:
        data["pieces"] = tuple(coaching.Piece(**piece) for piece in data["pieces"])
        return coaching.PieceGiven(**data)
    data["readings_noted"] = _notes(data.get("readings_noted", ()))
    if "blanks" in data:
        data["blanks"] = tuple(data["blanks"])
        return coaching.BlankOff(**data)
    return coaching.RetryAccepted(**data)


def _state(value: dict[str, Any]) -> models.TurnState:
    data = dict(value)
    if data.get("feedback") is not None:
        data["feedback"] = _feedback(data["feedback"])
    if data.get("reading") is not None:
        reading = data["reading"]
        data["reading"] = coaching.ReadingQuestion(
            reading["word"], tuple(reading["readings"])
        )
    if data.get("practice") is not None:
        target = data["practice"]
        data["practice"] = models.PracticeTarget(
            target["turn_index"], target["intent"], _feedback(target["feedback"])
        )
    return models.TurnState(**data)
