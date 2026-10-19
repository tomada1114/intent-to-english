"""Settings isolation follows the prefix and future model aliases."""

from __future__ import annotations

import pytest
from pydantic import AliasChoices, AliasPath, Field

from intent_to_english.settings import Settings
from tests.settings_env import without_settings_env


def test_settings_env_provider_alias_is_removed_in_either_case():
    assert without_settings_env(
        {
            "OPENROUTER_API_KEY": "dummy",
            "openrouter_api_key": "dummy-lowercase",
            "PATH": "preserved",
        }
    ) == {"PATH": "preserved"}


def test_settings_env_prefix_and_model_aliases_are_removed(monkeypatch):
    monkeypatch.setitem(
        Settings.model_fields,
        "future",
        Field(validation_alias=AliasChoices("VENDOR_FUTURE", "vendor_fallback")),
    )
    environment = {
        "INTENT_TO_ENGLISH_FUTURE_SETTING": "1",
        "intent_to_english_database_url": "postgresql://x",
        "VENDOR_FUTURE": "future",
        "VENDOR_FALLBACK": "fallback",
        "UNRELATED": "preserved",
    }

    cleaned = without_settings_env(environment)

    assert cleaned == {"UNRELATED": "preserved"}
    assert environment["INTENT_TO_ENGLISH_FUTURE_SETTING"] == "1"


@pytest.mark.parametrize(
    "field",
    [
        pytest.param(Field(alias="VENDOR_FUTURE"), id="alias"),
        pytest.param(Field(validation_alias="VENDOR_FUTURE"), id="validation-alias"),
        pytest.param(
            Field(validation_alias=AliasPath("VENDOR_FUTURE", "nested")),
            id="alias-path",
        ),
    ],
)
def test_settings_env_single_alias_input_is_removed(monkeypatch, field):
    monkeypatch.setitem(Settings.model_fields, "future", field)

    assert without_settings_env({"VENDOR_FUTURE": "fake", "PATH": "keep"}) == {
        "PATH": "keep"
    }
