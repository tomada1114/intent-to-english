from __future__ import annotations

import pytest

from intent_to_english.core import text


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        pytest.param("", (), id="empty"),
        pytest.param(" \n ", (), id="whitespace"),
        pytest.param("Hey! How's it going?", ("Hey!", "How's it going?"), id="opener"),
        pytest.param(
            "Mr. Tanaka moved to 3.5 km away.",
            ("Mr. Tanaka moved to 3.5 km away.",),
            id="abbreviation-and-decimal",
        ),
        pytest.param(
            "Hi?! Yes... Fine…", ("Hi?!", "Yes...", "Fine…"), id="punctuation-runs"
        ),
        pytest.param(
            "Hello.\nNext\tline", ("Hello.", "Next\tline"), id="trailing-fragment"
        ),
        pytest.param("Hi.There!", ("Hi.There!",), id="boundary-needs-space"),
        pytest.param(
            "はい。 どう\uff1f いい\uff01",
            ("はい。", "どう\uff1f", "いい\uff01"),
            id="japanese-punctuation",
        ),
        pytest.param("Just a fragment", ("Just a fragment",), id="no-terminator"),
    ],
)
def test_sentences_follow_the_contract_boundaries(line, expected):
    assert text.split_sentences(line) == expected
    assert text.count_sentences(line) == len(expected)


@pytest.mark.parametrize(
    "abbreviation", ["Mr", "Mrs", "Ms", "Dr", "St", "vs", "etc", "e.g", "i.e"], ids=str
)
def test_abbreviation_period_does_not_end_a_sentence(abbreviation):
    line = f"Try {abbreviation}. this. Next!"
    assert text.split_sentences(line) == (f"Try {abbreviation}. this.", "Next!")


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        pytest.param("Hello!", 0, id="none"),
        pytest.param("What's up\uff1f", 1, id="fullwidth"),
        pytest.param("Really?? Why\uff1f", 3, id="every-mark-counted"),
    ],
)
def test_question_count_includes_each_mark(line, expected):
    assert text.count_questions(line) == expected


@pytest.mark.parametrize(
    "letter",
    ["A", "z", "\uff21", "\uff5a", "À", "Ö", "Ø", "ö", "ø", "\u017f"],
    ids=repr,
)
def test_latin_letter_detection_covers_each_required_range(letter):
    assert text.has_latin_letter(f"主語 {letter} です") is True


@pytest.mark.parametrize(
    "line",
    [
        "",
        "主語を考えましょう",
        "\u00d7 ÷ 123",
        "\u0391 Ω",
        "Ж",
        "@ [ ` {",
        "\u00bf\u0180\uff20\uff3b\uff40\uff5b",
    ],
    ids=repr,
)
def test_latin_detection_preserves_nonletters_and_other_scripts(line):
    assert text.has_latin_letter(line) is False


@pytest.mark.parametrize(
    "character",
    [
        "\u3041",
        "\u309f",
        "\u30a0",
        "\u30ff",
        "\u31f0",
        "\u31ff",
        "\uff66",
        "\uff9f",
        "\u4e00",
        "\u9fff",
        "\u3400",
        "\u4dbf",
        "\uf900",
        "\ufaff",
        "々",
    ],
    ids=repr,
)
def test_japanese_script_detection_covers_range_edges(character):
    assert text.has_japanese_script(f"It was {character}.") is True


@pytest.mark.parametrize(
    "line",
    [
        "He said 「hi」.",
        "。\uff01\uff1f",
        "English",
        "",
        "\u3040\u3100\u31ef\u3200\uff65\uffa0\u33ff\u4dc0\ua000\uf8ff\ufb00",
    ],
    ids=repr,
)
def test_japanese_detection_accepts_punctuation_and_outside_ranges(line):
    assert text.has_japanese_script(line) is False
