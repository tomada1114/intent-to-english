from __future__ import annotations

from dataclasses import FrozenInstanceError, fields

import pytest

from intent_to_english.core import partner
from intent_to_english.core.models import ConversationLine, RestateMode, Speaker
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
