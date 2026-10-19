"""The closed, code-decided expectation vocabulary for evaluation cases."""

from __future__ import annotations

import re
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from typing import TYPE_CHECKING

from intent_to_english.core import coaching
from intent_to_english.core.models import FixTag, ModelTask
from intent_to_english.core.partner import PartnerLine
from intent_to_english.core.text import count_questions

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

_FIELDS = {
    "tagged": ("original", "tag"),
    "not_tagged": ("original", "tag"),
    "no_tag": ("tag",),
    "no_fix": (),
    "max_fixes": ("max",),
    "missing_point": ("any_of",),
    "fix_to": ("original", "any_of"),
    "reading_question": ("readings",),
    "accepted": (),
    "reading_noted": ("heard", "read_as"),
    "absent": ("text",),
    "no_question": (),
    "differs_from": ("text",),
}
_PARTNER_TASKS = frozenset({ModelTask.OPEN, ModelTask.REPLY, ModelTask.RESTATE})
_FEEDBACK_TASKS = frozenset({ModelTask.FEEDBACK})
_APPLIES = {
    **dict.fromkeys(
        (
            "tagged",
            "not_tagged",
            "no_tag",
            "no_fix",
            "max_fixes",
            "missing_point",
            "fix_to",
            "reading_question",
        ),
        _FEEDBACK_TASKS,
    ),
    "accepted": frozenset({ModelTask.CHECK_RETRY}),
    "reading_noted": frozenset({ModelTask.FEEDBACK, ModelTask.CHECK_RETRY}),
    "absent": frozenset(ModelTask),
    "no_question": _PARTNER_TASKS,
    "differs_from": _PARTNER_TASKS,
}
READING_COUNT = 2


@dataclass(frozen=True, slots=True)
class Expectation:
    """Validated arguments for one member of the closed vocabulary."""

    kind: str
    original: str | None = None
    tag: FixTag | None = None
    any_of: tuple[str, ...] = ()
    maximum: int | None = None
    readings: tuple[str, ...] = ()
    text: str | None = None
    heard: str | None = None
    read_as: str | None = None


def parse_expectation(
    data: Mapping[str, object], task: ModelTask, key: str
) -> Expectation:
    """Reject unknown arguments and expectations inapplicable to this task."""
    kind = _text(data.get("kind"), f"{key}.kind")
    if kind not in _FIELDS:
        message = f"{key}.kind: unknown expectation"
        raise ValueError(message)
    extra = data.keys() - {"kind", *_FIELDS[kind]}
    if extra:
        message = f"{key}.{min(extra)}: unknown field"
        raise ValueError(message)
    if task not in _APPLIES[kind]:
        message = f"{key}: expectation does not apply to task"
        raise ValueError(message)
    for name in _FIELDS[kind]:
        if name not in data:
            message = f"{key}.{name}: required field"
            raise ValueError(message)
    strings = {
        name: _text(data[name], f"{key}.{name}")
        for name in ("original", "text", "heard", "read_as")
        if name in data
    }
    tag = None
    if "tag" in data:
        try:
            tag = FixTag(_text(data["tag"], f"{key}.tag"))
        except ValueError:
            message = f"{key}.tag: expected miss or improvement"
            raise ValueError(message) from None
    maximum = data.get("max")
    if maximum is not None and (type(maximum) is not int or maximum < 0):
        message = f"{key}.max: expected a nonnegative integer"
        raise ValueError(message)
    any_of = _texts(data["any_of"], f"{key}.any_of") if "any_of" in data else ()
    readings = _texts(data["readings"], f"{key}.readings") if "readings" in data else ()
    if "readings" in data and (
        len(readings) != READING_COUNT or len(set(readings)) != READING_COUNT
    ):
        message = f"{key}.readings: expected two distinct readings"
        raise ValueError(message)
    return Expectation(
        kind,
        strings.get("original"),
        tag,
        any_of,
        maximum if isinstance(maximum, int) else None,
        readings,
        strings.get("text"),
        strings.get("heard"),
        strings.get("read_as"),
    )


def _text(value: object, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        message = f"{key}: expected nonempty text"
        raise ValueError(message)
    return value


def _texts(value: object, key: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        message = f"{key}: expected a nonempty text array"
        raise ValueError(message)
    return tuple(_text(item, key) for item in value)


def decide(expectation: Expectation, output: object) -> bool:
    """Judge only the requested property, without a model grader."""
    kind = expectation.kind
    if (
        kind in _FIELDS
        and kind != "reading_question"
        and _APPLIES[kind] == _FEEDBACK_TASKS
    ):
        return _feedback(expectation, output)
    return _other(expectation, output)


def _feedback(expectation: Expectation, output: object) -> bool:
    if not isinstance(output, coaching.Feedback):
        return False
    matching = tuple(
        fix
        for fix in output.fixes
        if fix.original is not None
        and expectation.original is not None
        and _contains(fix.original, expectation.original)
    )
    match expectation.kind:
        case "tagged":
            result = any(fix.tag == expectation.tag for fix in matching)
        case "not_tagged":
            result = not any(fix.tag == expectation.tag for fix in matching)
        case "no_tag":
            result = not any(fix.tag == expectation.tag for fix in output.fixes)
        case "no_fix":
            result = not output.fixes
        case "max_fixes":
            result = (
                expectation.maximum is not None
                and len(output.fixes) <= expectation.maximum
            )
        case "missing_point":
            result = any(
                fix.original is None
                and any(_contains(fix.replacement, text) for text in expectation.any_of)
                for fix in output.fixes
            )
        case "fix_to":
            result = any(
                _contains(fix.replacement, text)
                for fix in matching
                for text in expectation.any_of
            )
        case _:
            message = f"Unknown feedback expectation: {expectation.kind}"
            raise ValueError(message)
    return result


def _other(expectation: Expectation, output: object) -> bool:
    kind = expectation.kind
    match kind:
        case "reading_question":
            return isinstance(output, coaching.ReadingQuestion) and {
                text.strip().casefold() for text in output.readings
            } == {text.strip().casefold() for text in expectation.readings}
        case "accepted":
            return isinstance(output, coaching.RetryAccepted)
        case "reading_noted":
            return _reading_noted(expectation, output)
        case "absent":
            return expectation.text is not None and all(
                expectation.text.casefold() not in text.casefold()
                for text in text_values(output)
            )
        case "no_question":
            return isinstance(output, PartnerLine) and count_questions(output.text) == 0
        case "differs_from":
            return (
                isinstance(output, PartnerLine)
                and expectation.text is not None
                and output.text.strip().casefold()
                != expectation.text.strip().casefold()
            )
    message = f"Unknown expectation: {kind}"
    raise ValueError(message)


def _reading_noted(expectation: Expectation, output: object) -> bool:
    if not isinstance(
        output, (coaching.Feedback, coaching.RetryAccepted, coaching.BlankOff)
    ):
        return False
    return any(
        note.written.casefold() == (expectation.heard or "").casefold()
        and note.read_as.casefold() == (expectation.read_as or "").casefold()
        for note in output.readings_noted
    )


def _contains(text: str, fragment: str) -> bool:
    """Match a quoted original or replacement without finding AI inside daily."""
    escaped = re.escape(fragment.casefold())
    left = r"(?<!\w)" if fragment[0].isalnum() else ""
    right = r"(?!\w)" if fragment[-1].isalnum() else ""
    return re.search(left + escaped + right, text.casefold()) is not None


def text_values(value: object) -> Iterator[str]:
    """Visit every output text, including nested fixes and reading notes."""
    if isinstance(value, Enum):
        return
    if isinstance(value, str):
        yield value
    elif is_dataclass(value) and not isinstance(value, type):
        for item in fields(value):
            yield from text_values(getattr(value, item.name))
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from text_values(item)
