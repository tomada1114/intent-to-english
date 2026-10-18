from __future__ import annotations

from dataclasses import FrozenInstanceError, fields

import pytest

from intent_to_english.core import partner
from intent_to_english.core.models import (
    CheckId,
    ConversationLine,
    RestateMode,
    Speaker,
)
from intent_to_english.core.ports import CoachModel, PartnerModel


def test_partner_requests_expose_only_the_english_context():
    conversation = (ConversationLine(Speaker.LEARNER, "I stayed home."),)
    request = partner.ReplyRequest(conversation, share=True)
    assert request.conversation == conversation
    assert {field.name for field in fields(request)} == {"conversation", "share"}
    assert {field.name for field in fields(partner.OpenRequest)} == {"previous_opener"}
    assert {field.name for field in fields(partner.RestateRequest)} == {
        "conversation",
        "line",
        "mode",
    }
    assert partner.OpenRequest(None).previous_opener is None
    assert (
        partner.RestateRequest(
            conversation, "How was your day?", RestateMode.SHORTER
        ).mode
        is RestateMode.SHORTER
    )
    field_name = "share"
    with pytest.raises(FrozenInstanceError):
        setattr(request, field_name, False)


@pytest.mark.parametrize(
    "text", [pytest.param("", id="empty"), pytest.param("   ", id="whitespace")]
)
def test_partner_line_rejects_empty_output_before_content_checks(text):
    with pytest.raises(ValueError, match="empty"):
        partner.PartnerLine(text)


def test_model_ports_are_runtime_checkable_and_reject_missing_methods():
    assert not isinstance(object(), PartnerModel)
    assert not isinstance(object(), CoachModel)


@pytest.mark.parametrize("task", ["open", "reply", "restate"])
@pytest.mark.parametrize(
    ("line", "checks"),
    [
        pytest.param("Hey! How's it going?", (), id="two-sentences-one-question"),
        pytest.param(
            "Hi. Fine. Bye.", (CheckId.PARTNER_SENTENCES,), id="three-sentences"
        ),
        pytest.param(
            "Oh really? What did you make?",
            (CheckId.PARTNER_QUESTIONS,),
            id="two-questions",
        ),
        pytest.param("It was 楽しい.", (CheckId.PARTNER_JAPANESE,), id="japanese"),
        pytest.param("He said 「hi」.", (), id="punctuation"),
        pytest.param(
            "こんにちは。 Why? What?",
            (
                CheckId.PARTNER_JAPANESE,
                CheckId.PARTNER_SENTENCES,
                CheckId.PARTNER_QUESTIONS,
            ),
            id="table-order",
        ),
        pytest.param("Mr. Tanaka moved to 3.5 km away.", (), id="abbreviation"),
    ],
)
def test_partner_task_checks_apply_the_required_rules_without_text_in_details(
    task, line, checks
):
    requests = {
        "open": partner.OpenRequest("REQUEST-MARKER"),
        "reply": partner.ReplyRequest((), False),
        "restate": partner.RestateRequest((), "REQUEST-MARKER", RestateMode.SIMPLER),
    }
    result = getattr(partner, f"check_{task}")(
        requests[task], partner.PartnerLine(line)
    )
    assert tuple(violation.check for violation in result) == checks
    for violation in result:
        assert line not in violation.detail
        assert "REQUEST-MARKER" not in violation.detail


@pytest.mark.parametrize(
    ("line", "checks"),
    [
        pytest.param(
            "I tried building a chatbot for my team, but it gave weird answers.",
            (),
            id="worked-example-share",
        ),
        pytest.param(
            "What's up\uff1f", (CheckId.PARTNER_SHARE,), id="fullwidth-question"
        ),
        pytest.param(
            "Really? Why?",
            (CheckId.PARTNER_QUESTIONS, CheckId.PARTNER_SHARE),
            id="both-rules",
        ),
    ],
)
def test_reply_share_forbids_questions_after_other_checks(line, checks):
    result = partner.check_reply(
        partner.ReplyRequest((), True), partner.PartnerLine(line)
    )
    assert tuple(violation.check for violation in result) == checks
    assert all(line not in violation.detail for violation in result)
