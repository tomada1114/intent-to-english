"""Strict TOML cases for the closed model-task registry."""

from __future__ import annotations

import tomllib
from dataclasses import MISSING, dataclass, fields, is_dataclass
from enum import Enum
from types import UnionType
from typing import (
    TYPE_CHECKING,
    NoReturn,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from intent_to_english.core import coaching, models, partner
from intent_to_english.core.services import MODEL_TASKS
from intent_to_english.evaluation.expectations import Expectation, parse_expectation

if TYPE_CHECKING:
    from collections.abc import Callable
    from dataclasses import Field
    from pathlib import Path

MIN_CASES = 10
MAX_CASES = 20
_NAMESPACE = vars(models) | vars(partner) | vars(coaching)


class CaseLoadError(ValueError):
    """A case file or one of its named fields is invalid."""


@dataclass(frozen=True, slots=True)
class Case:
    """Public seed data with private context kept separate from the request."""

    path: Path
    task: models.ModelTask
    source: str
    request: object
    context: dict[str, object]
    expectations: tuple[Expectation, ...]


def load_case(path: Path) -> Case:
    """Read one case and construct its exact core request."""
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as error:
        _fail(path, "file", str(error))
    _keys(path, "case", data, {"task", "source", "request", "context", "expect"})
    task_name = data.get("task")
    if not isinstance(task_name, str):
        _fail(path, "task", "expected role.task")
    role, separator, method = task_name.partition(".")
    try:
        task = models.ModelTask(method)
    except ValueError:
        _fail(path, "task", "unknown task")
    definition = MODEL_TASKS[task]
    if not separator or role != definition.role.value:
        _fail(path, "task", "role does not match task")
    source = data.get("source")
    if not isinstance(source, str) or not source.strip():
        _fail(path, "source", "expected nonempty source")
    request = _decode(data.get("request"), definition.request_type, path, "request")
    context = _table(data.get("context", {}), path, "context")
    expected = data.get("expect")
    if not isinstance(expected, list) or not expected:
        _fail(path, "expect", "expected at least one expectation")
    expectations: list[Expectation] = []
    for number, item in enumerate(expected):
        key = f"expect[{number}]"
        table = _table(item, path, key)
        try:
            expectations.append(parse_expectation(table, task, key))
        except ValueError as error:
            _fail(path, str(error), "invalid expectation")
    return Case(path, task, source, request, context, tuple(expectations))


def load_cases(directory: Path) -> tuple[Case, ...]:
    """Read a fixed evaluation set in filename order."""
    paths = sorted(directory.glob("*.toml"))
    if not MIN_CASES <= len(paths) <= MAX_CASES:
        _fail(directory, "cases", "expected between 10 and 20 case files")
    return tuple(load_case(path) for path in paths)


def _decode(value: object, annotation: object, path: Path, key: str) -> object:
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (UnionType, Union):
        return _decode_union(value, args, path, key)
    if origin is tuple:
        return _decode_tuple(value, args, path, key)
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        if not isinstance(value, str):
            _fail(path, key, "expected an enum string")
        try:
            return annotation(value)
        except ValueError:
            _fail(path, key, "unknown enum value")
    if isinstance(annotation, type) and is_dataclass(annotation):
        return _decode_dataclass(value, annotation, fields(annotation), path, key)
    if annotation in (str, int, bool) and type(value) is annotation:
        return value
    return _fail(path, key, "value has the wrong type")


def _decode_union(
    value: object, args: tuple[object, ...], path: Path, key: str
) -> object:
    if (
        type(None) in args
        and isinstance(value, dict)
        and set(value) == {"none"}
        and value["none"] is True
    ):
        return None
    alternatives = tuple(item for item in args if item is not type(None))
    if len(alternatives) == 1:
        return _decode(value, alternatives[0], path, key)
    for alternative in args:
        if alternative is type(None):
            continue
        try:
            return _decode(value, alternative, path, key)
        except CaseLoadError:
            continue
    return _fail(path, key, "expected a declared variant or { none = true }")


def _decode_tuple(
    value: object, args: tuple[object, ...], path: Path, key: str
) -> tuple[object, ...]:
    if not isinstance(value, list):
        _fail(path, key, "expected an array")
    variadic = args[-1:] == (Ellipsis,)
    if not variadic and len(value) != len(args):
        _fail(path, key, "wrong array length")
    return tuple(
        _decode(item, args[0] if variadic else args[n], path, f"{key}[{n}]")
        for n, item in enumerate(value)
    )


def _decode_dataclass(
    value: object,
    annotation: type[object],
    members: tuple[Field[object], ...],
    path: Path,
    key: str,
) -> object:
    table = _table(value, path, key)
    _keys(path, key, table, {item.name for item in members})
    # Only known request/value classes enter this annotation namespace.
    hints: dict[str, object] = get_type_hints(annotation, globalns=_NAMESPACE)
    decoded: dict[str, object] = {}
    for item in members:
        if item.name not in table:
            if item.default is MISSING and item.default_factory is MISSING:
                _fail(path, f"{key}.{item.name}", "required field")
            continue
        decoded[item.name] = _decode(
            table[item.name], hints[item.name], path, f"{key}.{item.name}"
        )
    # Exact field names and recursively checked types precede dynamic construction.
    constructor = cast("Callable[..., object]", annotation)
    try:
        return constructor(**decoded)
    except ValueError:
        return _fail(path, key, "core value invariants failed")


def _table(value: object, path: Path, key: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(name, str) for name in value):
        _fail(path, key, "expected a table")
    return cast("dict[str, object]", value)


def _keys(path: Path, key: str, data: dict[str, object], allowed: set[str]) -> None:
    extra = data.keys() - allowed
    if extra:
        _fail(path, f"{key}.{min(extra)}", "unknown field")


def _fail(path: Path, key: str, reason: str) -> NoReturn:
    message = f"{path.name}: {key}: {reason}"
    raise CaseLoadError(message) from None
