"""The fixed mode's public triggers and shared output checks."""

from __future__ import annotations

import pytest

from intent_to_english.adapters.models import fixed
from intent_to_english.core import coaching as c
from intent_to_english.core import models as m
from intent_to_english.core import partner as p

pytestmark = pytest.mark.anyio

_FEEDBACK = c.Feedback(
    "意図は伝わっています",
    (c.Fix(1, "refreshing", "refreshed", "自分の気分は -ed", m.FixTag.MISS),),
    "I feel refreshing today.",
    "I feel (①) ____ today.",
    "(①) を埋めてください",
)
_CASES = [
    ("open", p.OpenRequest(None), p.check_open),
    ("open", p.OpenRequest("Hey! How's it going?"), p.check_open),
    ("reply", p.ReplyRequest((), False), p.check_reply),
    ("reply", p.ReplyRequest((), True), p.check_reply),
    (
        "restate",
        p.RestateRequest((), "How was your day?", m.RestateMode.SHORTER),
        p.check_restate,
    ),
    (
        "restate",
        p.RestateRequest((), "How was your day?", m.RestateMode.SIMPLER),
        p.check_restate,
    ),
    (
        "acknowledge",
        c.AcknowledgeRequest("久しぶりに散歩しました", ()),
        c.check_acknowledgment,
    ),
    ("acknowledge", c.AcknowledgeRequest("散歩しました", ()), c.check_acknowledgment),
    (
        "gap_hint",
        c.GapHintRequest("散歩しました", "楽しかった", "It was", (), ()),
        c.check_gap_hint,
    ),
    (
        "gap_hint",
        c.GapHintRequest(
            "散歩しました",
            " 楽しかった ",
            "It was",
            (c.EarlierHint("楽しかった", "ヒント"),),
            (),
        ),
        c.check_gap_hint,
    ),
    (
        "feedback",
        c.FeedbackRequest("住みたい", "I want to leave in Canada!", None, (), ()),
        c.check_feedback,
    ),
    (
        "feedback",
        c.FeedbackRequest(
            "住みたい",
            "I want to leave in Canada!",
            c.ReadingChoice("leave", "live"),
            (),
            (),
        ),
        c.check_feedback,
    ),
    (
        "feedback",
        c.FeedbackRequest("気分がいい", "I feel refreshing today.", None, (), ()),
        c.check_feedback,
    ),
    (
        "feedback",
        c.FeedbackRequest(None, "I went to the park.", None, (), ()),
        c.check_feedback,
    ),
    (
        "feedback",
        c.FeedbackRequest(None, "That sounds great!  ", None, (), ()),
        c.check_feedback,
    ),
    ("feedback", c.FeedbackRequest(None, "Hello", None, (), ()), c.check_feedback),
    (
        "check_retry",
        c.CheckRetryRequest(None, _FEEDBACK, "I feel REFRESHED today.", 1, ()),
        c.check_retry_result,
    ),
    (
        "check_retry",
        c.CheckRetryRequest(None, _FEEDBACK, "I feel good today.", 1, ()),
        c.check_retry_result,
    ),
    (
        "check_retry",
        c.CheckRetryRequest(None, _FEEDBACK, "I feel good today.", 2, ()),
        c.check_retry_result,
    ),
    (
        "show_answer",
        c.ShowAnswerRequest(m.Stage.ENGLISH, "気分がいい", None, None, ()),
        c.check_show_answer,
    ),
    (
        "show_answer",
        c.ShowAnswerRequest(
            m.Stage.RETRY, "気分がいい", "I feel refreshing today.", _FEEDBACK, ()
        ),
        c.check_show_answer,
    ),
    (
        "answer_question",
        c.AnswerQuestionRequest(
            "なぜですか",
            m.Stage.RETRY,
            "気分がいい",
            "I feel refreshing today.",
            _FEEDBACK,
            (),
        ),
        c.check_answer_question,
    ),
    ("wrap_up", c.WrapUpRequest((_FEEDBACK,), ()), c.check_wrap_up),
]


@pytest.mark.parametrize(
    "case",
    [pytest.param(case, id=f"{case[0]}-{index}") for index, case in enumerate(_CASES)],
)
async def test_fixed_tasks_are_deterministic_ignore_repair_and_pass_core_checks(case):
    task, request, check = case
    model = (
        fixed.FixedPartnerModel()
        if task in {"open", "reply", "restate"}
        else fixed.FixedCoachModel()
    )
    method = getattr(model, task)
    first = await method(request)
    assert first == await method(request)
    assert first == await method(
        request, m.Repair((m.Violation(m.CheckId.SCHEMA, "test repair"),))
    )
    assert first.usage == m.Usage("fixed", "fixed", None, None, None, 0)
    assert check(request, first.output) == ()


@pytest.mark.parametrize(
    ("previous", "expected"),
    [
        (None, "Hey! How's it going?"),
        ("Hey! How's it going?", "Hi! How was your weekend?"),
        ("Hey! How was your day today?", "Hey! How's it going?"),
    ],
)
async def test_opener_chooses_the_first_that_differs_from_previous(previous, expected):
    assert (
        await fixed.FixedPartnerModel().open(p.OpenRequest(previous))
    ).output == p.PartnerLine(expected)


@pytest.mark.parametrize(
    ("english", "reading", "result_type", "tag"),
    [
        ("I want to leave in Canada!", None, c.ReadingQuestion, None),
        ("I feel refreshing today! ", None, c.Feedback, None),
        ("I feel REFRESHING today.", None, c.Feedback, m.FixTag.MISS),
        ("I left yesterday.", None, c.Feedback, m.FixTag.IMPROVEMENT),
        ("Leaves are green.", None, c.Feedback, m.FixTag.IMPROVEMENT),
        ("Hello", None, c.Feedback, None),
        (
            "I want to LEAVE in Canada.",
            c.ReadingChoice("leave", "live"),
            c.Feedback,
            m.FixTag.IMPROVEMENT,
        ),
    ],
)
async def test_feedback_trigger_order_whole_words_and_chosen_reading(
    english, reading, result_type, tag
):
    request = c.FeedbackRequest(None, english, reading, (), ())
    output = (await fixed.FixedCoachModel().feedback(request)).output
    assert isinstance(output, result_type)
    if isinstance(output, c.Feedback):
        assert tuple(fix.tag for fix in output.fixes) == (() if tag is None else (tag,))
        if reading is not None:
            assert output.readings_noted == (c.ReadingNote("LEAVE", "live"),)
    assert c.check_feedback(request, output) == ()


async def test_retry_names_the_first_missing_fix_and_show_answer_fills_every_blank():
    feedback = c.Feedback(
        "意図は伝わっています",
        (
            c.Fix(1, "a", "the", "冠詞", m.FixTag.MISS),
            c.Fix(2, "go", "went", "過去形", m.FixTag.MISS),
        ),
        "I go to a park.",
        "I (②) ____ to (①) ____ park.",
        "埋めてください",
    )
    coach = fixed.FixedCoachModel()
    first = (
        await coach.check_retry(
            c.CheckRetryRequest(None, feedback, "I go to the park.", 1, ())
        )
    ).output
    second = (
        await coach.check_retry(
            c.CheckRetryRequest(None, feedback, "I go to the park.", 2, ())
        )
    ).output
    accepted = (
        await coach.check_retry(
            c.CheckRetryRequest(None, feedback, "I WENT to THE park.", 1, ())
        )
    ).output
    shown = (
        await coach.show_answer(
            c.ShowAnswerRequest(m.Stage.RETRY, None, "I go to a park.", feedback, ())
        )
    ).output
    assert first == c.BlankOff((2,), "②がまだ違います。w で始まります")
    assert second == c.PieceGiven((c.Piece(2, "went"),), "②は went です")
    assert isinstance(accepted, c.RetryAccepted)
    assert shown == c.Answer("I went to the park.")


def test_module_docstring_documents_each_trigger_for_api_and_browser_cases():
    doc = fixed.__doc__
    assert doc is not None
    for trigger in (
        "previous_opener",
        "share",
        "shorter",
        "simpler",
        "久しぶり",
        "gap",
        "leave",
        "live",
        "refreshing",
        "Actually,",
        "!",
        "one-word",
        "check_retry",
        "show_answer",
        "answer_question",
        "wrap_up",
        "fixed",
    ):
        assert trigger in doc


@pytest.mark.parametrize(
    "case",
    [
        (
            "reply",
            p.ReplyRequest((), False),
            p.PartnerLine("Nice! What did you do after that?"),
        ),
        (
            "reply",
            p.ReplyRequest((), True),
            p.PartnerLine("I went for a long walk by the river today."),
        ),
        (
            "restate",
            p.RestateRequest((), "How was your day?", m.RestateMode.SHORTER),
            p.PartnerLine("What's new?"),
        ),
        (
            "restate",
            p.RestateRequest((), "How was your day?", m.RestateMode.SIMPLER),
            p.PartnerLine("How are you doing?"),
        ),
        (
            "acknowledge",
            c.AcknowledgeRequest("散歩しました", ()),
            c.Acknowledgment("いいですね\uff01"),
        ),
        (
            "acknowledge",
            c.AcknowledgeRequest("久しぶりに散歩しました", ()),
            c.Acknowledgment(
                "いいですね\uff01",
                "「久しぶりに」は「長いあいだしていなかった」と言い換えると組み立てやすいです",
            ),
        ),
        (
            "gap_hint",
            c.GapHintRequest("楽しかった", "楽しかった", "It was", (), ()),
            c.GapHint("「楽しかった」の部分は kind of から始めてみてください"),
        ),
        (
            "gap_hint",
            c.GapHintRequest(
                "楽しかった",
                " 楽しかった ",
                "It was",
                (c.EarlierHint("楽しかった", "最初のヒント"),),
                (),
            ),
            c.GapHint("「楽しかった」の部分は it was kind of fun のように言えます"),
        ),
    ],
    ids=[
        "question",
        "share",
        "shorter",
        "simpler",
        "ack",
        "build-hint",
        "first-gap",
        "same-gap",
    ],
)
async def test_fixed_lines_and_repeated_gap_match_the_issue_contract(case):
    task, request, expected = case
    model = (
        fixed.FixedPartnerModel()
        if task in {"reply", "restate"}
        else fixed.FixedCoachModel()
    )
    assert (await getattr(model, task)(request)).output == expected


@pytest.mark.parametrize("intent", [None, "気分がいい"], ids=["direct", "with-intent"])
async def test_feedback_preserves_learner_sentence_and_builds_the_numbered_template(
    intent,
):
    coach = fixed.FixedCoachModel()
    english = "I feel refreshing today."
    output = (
        await coach.feedback(c.FeedbackRequest(intent, english, None, (), ()))
    ).output
    assert isinstance(output, c.Feedback)
    assert output.sentence == english
    assert output.template == "I feel (①) ____ today."
    assert output.request_line == "(①) を埋めて、文全体をもう一度送ってください"
    assert output.fixes == (
        c.Fix(
            1,
            "refreshing",
            "refreshed",
            "自分の気分は -ed。-ing だと「人をさわやかにさせる」",
            m.FixTag.MISS,
        ),
    )
    if intent is None:
        assert "意図は伝わっています" not in output.first_line
    else:
        assert output.first_line == "意図は伝わっています"


@pytest.mark.parametrize(
    ("intent", "expected"),
    [
        (None, "元のままでも通じます"),
        ("散歩しました", "意図は伝わっています。元のままでも通じます"),
    ],
    ids=["direct", "with-intent"],
)
async def test_default_improvement_preserves_first_word_and_does_not_claim_a_missing_intent(
    intent, expected
):
    request = c.FeedbackRequest(intent, "I went to the park.", None, (), ())
    output = (await fixed.FixedCoachModel().feedback(request)).output
    assert isinstance(output, c.Feedback)
    assert output.first_line == expected
    assert output.fixes[0].original == "I"
    assert output.fixes[0].replacement == "Actually, I"
    assert output.template == "(①) ____ went to the park."


async def test_refreshing_template_replaces_the_whole_word_match_not_an_earlier_prefix():
    english = "It was refreshingly cool, but I feel refreshing today."
    request = c.FeedbackRequest(None, english, None, (), ())
    output = (await fixed.FixedCoachModel().feedback(request)).output
    assert isinstance(output, c.Feedback)
    assert output.template == "It was refreshingly cool, but I feel (①) ____ today."
    assert c.check_feedback(request, output) == ()


@pytest.mark.parametrize(
    "english",
    [
        "I went to __ yesterday.",
        "I feel refreshing at (②) ____.",
        "① I went yesterday.",
        "I wrote ⑳ in my notes.",
    ],
    ids=["underscores", "existing-blank", "first-number", "last-number"],
)
async def test_reserved_learner_markers_do_not_become_invalid_retry_templates(english):
    request = c.FeedbackRequest(None, english, None, (), ())
    coach = fixed.FixedCoachModel()
    result = await coach.feedback(request)
    assert result.output == c.Feedback("いいですね\uff01そのままで伝わります")
    assert c.check_feedback(request, result.output) == ()
    assert result == await coach.feedback(request, m.Repair(()))


async def test_reserved_marker_fallback_keeps_reading_question_and_chosen_note():
    coach = fixed.FixedCoachModel()
    request = c.FeedbackRequest(None, "I leave at (②) ____.", None, (), ())
    assert (await coach.feedback(request)).output == c.ReadingQuestion(
        "leave", ("leave", "live")
    )
    chosen = c.FeedbackRequest(
        None, request.english, c.ReadingChoice("leave", "live"), (), ()
    )
    output = (await coach.feedback(chosen)).output
    assert output == c.Feedback(
        "いいですね\uff01そのままで伝わります",
        readings_noted=(c.ReadingNote("leave", "live"),),
    )
    assert c.check_feedback(chosen, output) == ()


@pytest.mark.parametrize("english", ["refreshing", "REFRESHING"])
async def test_one_word_refreshing_cannot_leak_its_entire_completed_sentence(english):
    request = c.FeedbackRequest(None, english, None, (), ())
    output = (await fixed.FixedCoachModel().feedback(request)).output
    assert c.check_feedback(request, output) == ()
    assert output == c.Feedback("いいですね\uff01そのままで伝わります")
