from __future__ import annotations

import pytest

from intent_to_english.core import coaching


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
