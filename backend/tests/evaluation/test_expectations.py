from __future__ import annotations

import pytest

from intent_to_english.core import coaching as c
from intent_to_english.core.models import FixTag, ModelTask
from intent_to_english.core.partner import PartnerLine
from intent_to_english.evaluation.expectations import (
    Expectation,
    decide,
    parse_expectation,
)


def feedback(original="refreshing", replacement="refreshed", tag=FixTag.MISS):
    return c.Feedback(
        "意図は伝わっています",
        (c.Fix(1, original, replacement, "理由", tag),),
        "I feel refreshing.",
        "I feel (①) ____.",
        "空欄を埋めてください",
    )


@pytest.mark.parametrize(
    ("expectation", "passing", "failing"),
    [
        (
            Expectation("tagged", original="refreshing", tag=FixTag.MISS),
            feedback(),
            feedback(tag=FixTag.IMPROVEMENT),
        ),
        (
            Expectation("not_tagged", original="refreshing", tag=FixTag.MISS),
            feedback(tag=FixTag.IMPROVEMENT),
            feedback(),
        ),
        (
            Expectation("no_tag", tag=FixTag.MISS),
            feedback(tag=FixTag.IMPROVEMENT),
            feedback(),
        ),
        (Expectation("no_fix"), c.Feedback("自然です"), feedback()),
        (Expectation("max_fixes", maximum=0), c.Feedback("自然です"), feedback()),
        (
            Expectation("missing_point", any_of=("widely", "commonly")),
            feedback(None, "widely", FixTag.IMPROVEMENT),
            feedback("used", "widely"),
        ),
        (
            Expectation("fix_to", original="don't you", any_of=("too", "as well")),
            feedback("also, don't you", "too"),
            feedback("don't you", "right"),
        ),
        (
            Expectation("reading_question", readings=("leave", "live")),
            c.ReadingQuestion("leave", ("live", "leave")),
            c.ReadingQuestion("leave", ("leave", "leaf")),
        ),
        (
            Expectation("accepted"),
            c.RetryAccepted("伝わりました"),
            c.BlankOff((1,), "ヒント"),
        ),
        (
            Expectation("reading_noted", heard="starting", read_as="studying"),
            c.RetryAccepted("伝わりました", (c.ReadingNote("starting", "studying"),)),
            c.RetryAccepted("伝わりました"),
        ),
        (
            Expectation("absent", text="AWS"),
            c.CoachAnswer("別の言い方"),
            c.CoachAnswer("try aws today"),
        ),
        (
            Expectation("no_question"),
            PartnerLine("I went for a walk."),
            PartnerLine("Where did you go?"),
        ),
        (
            Expectation("differs_from", text="Hi!"),
            PartnerLine("How was your day?"),
            PartnerLine("Hi!"),
        ),
    ],
    ids=[
        "tagged",
        "not-tagged",
        "no-tag",
        "no-fix",
        "max-fixes",
        "missing-point",
        "fix-to",
        "reading-question",
        "accepted",
        "reading-noted",
        "absent-casefold",
        "no-question",
        "different-opener",
    ],
)
def test_each_closed_expectation_accepts_and_rejects_output(
    expectation, passing, failing
):
    assert decide(expectation, passing) is True
    assert decide(expectation, failing) is False


def test_absent_inspects_nested_feedback_text_including_reading_notes():
    output = c.Feedback(
        "自然です", readings_noted=(c.ReadingNote("starting", "STUDYING"),)
    )

    assert decide(Expectation("absent", text="studying"), output) is False


def test_original_match_does_not_find_ai_inside_daily():
    output = feedback("daily", "every day")

    assert (
        decide(Expectation("not_tagged", original="AI", tag=FixTag.MISS), output)
        is True
    )


@pytest.mark.parametrize(
    "kind", ["not_tagged", "no_tag", "no_fix", "max_fixes"], ids=lambda x: x
)
def test_feedback_expectation_cannot_pass_a_reading_question(kind):
    expectation = Expectation(kind, original="AI", tag=FixTag.MISS, maximum=5)

    assert decide(expectation, c.ReadingQuestion("leave", ("leave", "live"))) is False


@pytest.mark.parametrize(
    ("data", "task"),
    [
        ({"kind": "max_fixes", "max": True}, ModelTask.FEEDBACK),
        ({"kind": "max_fixes", "max": -1}, ModelTask.FEEDBACK),
        ({"kind": "tagged", "original": "AI", "tag": "unknown"}, ModelTask.FEEDBACK),
        ({"kind": "missing_point", "any_of": []}, ModelTask.FEEDBACK),
        (
            {"kind": "reading_question", "readings": ["leave", "leave"]},
            ModelTask.FEEDBACK,
        ),
        ({"kind": "accepted"}, ModelTask.OPEN),
    ],
    ids=[
        "boolean-count",
        "negative-count",
        "unknown-tag",
        "empty-alternatives",
        "same-readings",
        "wrong-task",
    ],
)
def test_expectation_arguments_are_strict(data, task):
    with pytest.raises(ValueError, match="expect"):
        parse_expectation(data, task, "expect")
