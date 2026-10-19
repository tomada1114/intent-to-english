from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import AliasChoices, AliasPath

from intent_to_english.settings import ENV_FILE, ENV_PREFIX, Settings
from tests.settings_env import settings_from_env_file

if TYPE_CHECKING:
    from pydantic.fields import FieldInfo

EXAMPLE = ENV_FILE.with_name(".env.example")


def _aliases(field: FieldInfo) -> set[str]:
    """Admit only input aliases explicitly declared on a settings field."""
    alias = field.validation_alias or field.alias
    if isinstance(alias, str):
        return {alias.upper()}
    if isinstance(alias, (AliasChoices, AliasPath)):
        paths = (
            alias.convert_to_aliases()
            if isinstance(alias, AliasChoices)
            else [alias.convert_to_aliases()]
        )
        return {path[0].upper() for path in paths if isinstance(path[0], str)}
    return set()


def _environment_names() -> set[str]:
    """Derive input names using the same aliases as settings_env's isolation."""
    names: set[str] = set()
    for name, field in Settings.model_fields.items():
        names.update(_aliases(field) or {f"{ENV_PREFIX}{name.upper()}"})
    return names


def test_settings_env_example_lists_exactly_every_setting_with_empty_values():
    assignments = [
        line.split("=", 1)
        for line in EXAMPLE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert {name for name, _ in assignments} == _environment_names()
    assert len(assignments) == len(_environment_names())
    aliases = {
        alias for field in Settings.model_fields.values() for alias in _aliases(field)
    }
    assert all(
        (name.startswith(ENV_PREFIX) or name in aliases) and value == ""
        for name, value in assignments
    )


def test_settings_env_example_loads_all_defaults():
    assert EXAMPLE.is_file()
    assert (
        settings_from_env_file(EXAMPLE).model_dump()
        == settings_from_env_file(None).model_dump()
    )
