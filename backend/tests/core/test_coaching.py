from __future__ import annotations

from dataclasses import replace

import pytest

from intent_to_english.core import coaching
from intent_to_english.core.models import CheckId, FixTag, Stage


def test_feedback_without_fixes_refuses_a_sentence_and_keeps_first_line():
    with pytest.raises(ValueError, match="no fixes"):
        coaching.Feedback(first_line="いいですね", sentence="The answer.")
    feedback = coaching.Feedback(first_line="いいですね")
    assert feedback.fixes == ()
    assert feedback.sentence is None


@pytest.mark.parametrize(
    "readings",
    [
        pytest.param(("leave", "leave"), id="same"),
        pytest.param(("", "live"), id="empty"),
    ],
)
def test_reading_question_requires_two_distinct_nonempty_readings(readings):
    with pytest.raises(ValueError, match="readings"):
        coaching.ReadingQuestion("leave", readings)


@pytest.fixture
def make_feedback():
    def make(**changes):
        feedback = coaching.Feedback(
            "意図は伝わっています",
            (
                coaching.Fix(1, "refreshing", "refreshed", "気分は -ed", FixTag.MISS),
                coaching.Fix(
                    2, "completed", "finished", "元のままでも通じる", FixTag.IMPROVEMENT
                ),
            ),
            "I feel refreshing because I completed my study.",
            "I feel (①) ____ because I (②) ____ my study.",
            "穴を埋めて送ってください",
        )
        return replace(feedback, **changes)

    return make


def _request():
    return coaching.FeedbackRequest("REQUEST-MARKER", "INPUT-MARKER", None, (), ())


@pytest.mark.parametrize(
    ("template", "checks"),
    [
        pytest.param(
            "I feel (①) ____ because I (②) ____ my study.", (), id="ascending"
        ),
        pytest.param(
            "I feel (②) ____ because I (①) ____ my study.",
            (CheckId.FIX_NUMBERS,),
            id="reversed",
        ),
        pytest.param(
            "I feel (①) ____ because I (①) ____ my study.",
            (CheckId.FIX_NUMBERS,),
            id="repeated",
        ),
        pytest.param(
            "I feel (①) ____ because I (②) ____ my (③) ____ study.",
            (CheckId.FIX_NUMBERS, CheckId.BLANKS_FILLED),
            id="extra-blank",
        ),
        pytest.param("I feel (①) ____.", (CheckId.FIX_NUMBERS,), id="missing-blank"),
    ],
)
def test_feedback_checks_exact_blank_sequence_and_remaining_markers(
    make_feedback, template, checks
):
    result = coaching.check_feedback(_request(), make_feedback(template=template))
    assert tuple(v.check for v in result) == checks
    assert all(
        template not in v.detail
        and "REQUEST-MARKER" not in v.detail
        and "INPUT-MARKER" not in v.detail
        for v in result
    )


@pytest.mark.parametrize(
    "numbers",
    [(2, 1), (1, 1), (1, 3)],
    ids=["reversed-fixes", "duplicate-fixes", "gap-in-fixes"],
)
def test_feedback_refuses_nonconsecutive_fix_numbers(make_feedback, numbers):
    feedback = make_feedback()
    feedback = replace(
        feedback,
        fixes=tuple(
            replace(fix, number=number)
            for fix, number in zip(feedback.fixes, numbers, strict=True)
        ),
    )
    assert CheckId.FIX_NUMBERS in tuple(
        v.check for v in coaching.check_feedback(_request(), feedback)
    )


@pytest.mark.parametrize(
    "replacement",
    ["____", "①", "text __ text"],
    ids=["underscores", "circled-number", "underscore-run"],
)
def test_feedback_replacement_must_not_leave_a_blank_marker(make_feedback, replacement):
    feedback = make_feedback()
    feedback = replace(
        feedback,
        fixes=(replace(feedback.fixes[0], replacement=replacement), feedback.fixes[1]),
    )
    assert CheckId.BLANKS_FILLED in tuple(
        v.check for v in coaching.check_feedback(_request(), feedback)
    )


@pytest.mark.parametrize(
    "field",
    [
        "first_line",
        "sentence",
        "request_line",
        "reason",
        "original",
        "reading-written",
        "reading-as",
    ],
)
def test_feedback_leak_check_reads_every_nested_text_field(make_feedback, field):
    feedback = make_feedback()
    filled = "I feel refreshed because I finished my study."
    values = {
        "first_line": replace(feedback, first_line=filled),
        "sentence": replace(feedback, sentence=filled),
        "request_line": replace(feedback, request_line=f"{filled} と送ってください"),
        "reason": replace(
            feedback,
            fixes=(replace(feedback.fixes[0], reason=filled), feedback.fixes[1]),
        ),
        "original": replace(
            feedback,
            fixes=(replace(feedback.fixes[0], original=filled), feedback.fixes[1]),
        ),
        "reading-written": replace(
            feedback, readings_noted=(coaching.ReadingNote(filled, "safe"),)
        ),
        "reading-as": replace(
            feedback, readings_noted=(coaching.ReadingNote("safe", filled),)
        ),
    }
    result = coaching.check_feedback(_request(), values[field])
    assert tuple(v.check for v in result) == (CheckId.COMPLETED_SENTENCE,)
    assert all(filled not in v.detail for v in result)


def test_one_word_feedback_has_no_completed_sentence_exemption():
    feedback = coaching.Feedback(
        "直してみましょう",
        (coaching.Fix(1, "sad", "happy", "別の気分", FixTag.MISS),),
        "sad",
        "(①) ____",
        "埋めてください",
    )
    assert tuple(v.check for v in coaching.check_feedback(_request(), feedback)) == (
        CheckId.COMPLETED_SENTENCE,
    )


def test_feedback_without_fixes_and_first_reading_question_pass():
    assert coaching.check_feedback(_request(), coaching.Feedback("いいですね")) == ()
    question = coaching.ReadingQuestion("leave", ("leave", "live"))
    assert coaching.check_feedback(_request(), question) == ()
    request = replace(_request(), reading=coaching.ReadingChoice("leave", "live"))
    result = coaching.check_feedback(request, question)
    assert tuple(v.check for v in result) == (CheckId.SCHEMA,)
    assert all("leave" not in v.detail and "live" not in v.detail for v in result)


@pytest.mark.parametrize(
    ("hint", "expected"),
    [
        pytest.param(None, (), id="none"),
        pytest.param("主語を考えましょう", (), id="japanese"),
        pytest.param("\u00d7 と ÷", (), id="nonletters"),
        pytest.param("主語は I に", (CheckId.BUILD_HINT_LATIN,), id="ascii"),
        pytest.param("\uff21\uff37\uff33", (CheckId.BUILD_HINT_LATIN,), id="fullwidth"),
        pytest.param("café", (CheckId.BUILD_HINT_LATIN,), id="accented"),
    ],
)
def test_acknowledgment_checks_only_latin_in_the_build_hint(hint, expected):
    result = coaching.check_acknowledgment(
        coaching.AcknowledgeRequest("意図", ()),
        coaching.Acknowledgment("ACK-MARKER", hint),
    )
    assert tuple(v.check for v in result) == expected
    assert all(hint not in v.detail and "ACK-MARKER" not in v.detail for v in result)


@pytest.mark.parametrize(
    "result",
    [
        coaching.RetryAccepted("I feel refreshed because I finished my study."),
        coaching.BlankOff((1,), "I feel refreshed because I finished my study."),
        coaching.PieceGiven(
            (coaching.Piece(1, "I feel refreshed because I finished my study."),),
            "続けましょう",
        ),
        coaching.PieceGiven(
            (coaching.Piece(1, "refreshed"),),
            "I feel refreshed because I finished my study.",
        ),
        coaching.RetryAccepted(
            "いいですね",
            (
                coaching.ReadingNote(
                    "I feel refreshed because I finished my study.", "safe"
                ),
            ),
        ),
        coaching.BlankOff(
            (1,),
            "最初だけ",
            (
                coaching.ReadingNote(
                    "safe", "I feel refreshed because I finished my study."
                ),
            ),
        ),
    ],
    ids=["accepted", "hint", "piece", "piece-line", "accepted-reading", "hint-reading"],
)
def test_retry_results_check_every_text_against_the_active_feedback(
    make_feedback, result
):
    request = coaching.CheckRetryRequest(None, make_feedback(), "INPUT-MARKER", 1, ())
    violations = coaching.check_retry_result(request, result)
    assert tuple(v.check for v in violations) == (CheckId.COMPLETED_SENTENCE,)
    assert all(
        "INPUT-MARKER" not in v.detail and "I feel" not in v.detail for v in violations
    )


@pytest.mark.parametrize(
    "output",
    [
        coaching.RetryAccepted("いいですね"),
        coaching.BlankOff((1,), "最初の形を考えましょう"),
        coaching.PieceGiven((coaching.Piece(1, "refreshed"),), "次へ進みましょう"),
    ],
    ids=["accepted", "blank", "piece"],
)
def test_retry_results_without_the_completed_sentence_pass(make_feedback, output):
    assert (
        coaching.check_retry_result(
            coaching.CheckRetryRequest(None, make_feedback(), "attempt", 1, ()), output
        )
        == ()
    )


def test_side_answer_normalizes_case_apostrophe_whitespace_and_trailing_punctuation(
    make_feedback,
):
    feedback = make_feedback(template="I'm (①) ____ because I (②) ____ my study.")
    request = coaching.AnswerQuestionRequest(
        "QUESTION-MARKER", Stage.RETRY, None, None, feedback, ()
    )
    output = coaching.CoachAnswer(
        "I\u2019M \n REFRESHED because I FINISHED my study!!!"
    )
    result = coaching.check_answer_question(request, output)
    assert tuple(v.check for v in result) == (CheckId.COMPLETED_SENTENCE,)
    assert all(
        "QUESTION-MARKER" not in v.detail and "REFRESHED" not in v.detail
        for v in result
    )
    assert (
        coaching.check_answer_question(
            replace(request, feedback=None, stage=Stage.INTENT), output
        )
        == ()
    )
    assert (
        coaching.check_answer_question(
            request, coaching.CoachAnswer("最初の形を考えてください")
        )
        == ()
    )


def test_uniform_noop_task_entry_points_do_not_add_candidate_rules(make_feedback):
    assert (
        coaching.check_gap_hint(
            coaching.GapHintRequest("意図", "gap", "", (), ()),
            coaching.GapHint("a hint"),
        )
        == ()
    )
    assert (
        coaching.check_show_answer(
            coaching.ShowAnswerRequest(
                Stage.RETRY, None, "attempt", make_feedback(), ()
            ),
            coaching.Answer("I feel refreshed because I finished my study."),
        )
        == ()
    )
    assert (
        coaching.check_wrap_up(coaching.WrapUpRequest((), ()), coaching.WrapUp(()))
        == ()
    )


def test_three_fixes_with_only_two_blanks_fails_only_numbering(make_feedback):
    feedback = make_feedback()
    feedback = replace(
        feedback,
        fixes=(
            *feedback.fixes,
            coaching.Fix(3, None, "daily", "習慣を表す", FixTag.IMPROVEMENT),
        ),
    )
    result = coaching.check_feedback(_request(), feedback)
    assert tuple(v.check for v in result) == (CheckId.FIX_NUMBERS,)
    assert all(
        "daily" not in v.detail and "INPUT-MARKER" not in v.detail for v in result
    )


@pytest.mark.parametrize(
    ("sentence", "template", "replacements", "originals"),
    [
        pytest.param(
            "I feel refreshing today because I completed my study routine in the morning about English and programming every day.",
            "I feel (①) ____ today because I (②) ____ my (③) ____ study (④) ____.",
            ("refreshed", "finished", "daily English and programming", "this morning"),
            (
                "refreshing",
                "completed",
                "study routine … about English and programming every day",
                "in the morning",
            ),
            id="worked-example-1",
        ),
        pytest.param(
            "Oh, I got it. It sometimes happens that AI agent doesn't work well when it is used, in fact.",
            "Oh, (①) ____. (②) ____, (③) ____, (④) ____?",
            (
                "I see",
                "When you actually use them",
                "things often don't go the way you expect",
                "right",
            ),
            (
                "I got it",
                "when it is used, in fact",
                "It sometimes happens that AI agent doesn't work well",
                None,
            ),
            id="worked-example-5-reordered-originals",
        ),
    ],
)
def test_feedback_worked_examples_pass_with_blanks_in_template_order(
    sentence, template, replacements, originals
):
    fixes = tuple(
        coaching.Fix(number, original, replacement, "説明", FixTag.IMPROVEMENT)
        for number, (original, replacement) in enumerate(
            zip(originals, replacements, strict=True), start=1
        )
    )
    feedback = coaching.Feedback(
        "意図は伝わっています", fixes, sentence, template, "穴を埋めて送ってください"
    )
    assert coaching.check_feedback(_request(), feedback) == ()


def test_retry_worked_example_four_cannot_quote_the_filled_sentence():
    feedback = coaching.Feedback(
        "意図は伝わっています",
        (coaching.Fix(1, "also … , don't you", "too", "驚きを表す", FixTag.MISS),),
        "Wow, you also build AI agents, don't you?",
        "Wow, you build AI agents (①) ____?",
        "穴を埋めてください",
    )
    request = coaching.CheckRetryRequest(None, feedback, "attempt", 1, ())
    result = coaching.check_retry_result(
        request, coaching.RetryAccepted("Wow, you build AI agents too? で大丈夫です")
    )
    assert tuple(v.check for v in result) == (CheckId.COMPLETED_SENTENCE,)
