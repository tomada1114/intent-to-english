from __future__ import annotations

import pytest

from intent_to_english.core import coaching, partner
from intent_to_english.core.models import ModelTask
from intent_to_english.evaluation.cases import CaseLoadError, load_case, load_cases

OPENER = """task = "partner.open"
source = "requirements 3.11"
[request]
previous_opener = { none = true }
[[expect]]
kind = "differs_from"
text = "Hi! How was your day?"
"""


def test_case_constructs_nullable_request_without_reinterpreting_empty_string(tmp_path):
    path = tmp_path / "01-opener.toml"
    path.write_text(OPENER)

    case = load_case(path)

    assert case.task is ModelTask.OPEN
    assert case.request == partner.OpenRequest(None)
    path.write_text(OPENER.replace("{ none = true }", '""'))
    assert load_case(path).request == partner.OpenRequest("")


@pytest.mark.parametrize(
    ("before", "after", "key"),
    [
        ("previous_opener = { none = true }", 'extra = "bad"', "request.extra"),
        ("previous_opener = { none = true }", "", "request.previous_opener"),
        ("{ none = true }", "{ none = 1 }", "request.previous_opener"),
        ('kind = "differs_from"', 'kind = "unknown"', "expect[0].kind"),
        ('kind = "differs_from"', 'kind = "no_fix"', "expect[0]"),
        ('text = "Hi! How was your day?"', 'extra = "bad"', "expect[0].extra"),
        ('task = "partner.open"', 'task = "coach.open"', "task"),
        ('source = "requirements 3.11"', "", "source"),
    ],
    ids=[
        "extra-request",
        "missing-request",
        "invalid-null",
        "unknown-expectation",
        "inapplicable",
        "extra-expectation",
        "wrong-role",
        "missing-source",
    ],
)
def test_malformed_case_names_file_and_key(tmp_path, before, after, key):
    path = tmp_path / "case.toml"
    path.write_text(OPENER.replace(before, after))

    with pytest.raises(CaseLoadError, match=r"case\.toml") as caught:
        load_case(path)

    assert key in str(caught.value)


def test_nested_request_fields_decode_and_context_stays_outside_request(tmp_path):
    path = tmp_path / "feedback.toml"
    path.write_text("""task = "coach.feedback"
source = "conversation-rules 7"
[context]
intent_note = "PRIVATE-CONTEXT"
[request]
intent = { none = true }
english = "I like tea."
reading = { word = "bins", chosen = "beans" }
earlier_english = []
conversation = [{ speaker = "partner", text = "What do you like?" }]
[[expect]]
kind = "no_fix"
""")

    case = load_case(path)

    assert isinstance(case.request, coaching.FeedbackRequest)
    assert case.request.reading == coaching.ReadingChoice("bins", "beans")
    assert case.context == {"intent_note": "PRIVATE-CONTEXT"}
    assert "PRIVATE-CONTEXT" not in repr(case.request)


@pytest.mark.parametrize(
    ("reading", "key"),
    [
        ('{ word = "leave" }', "request.reading.chosen"),
        ('{ word = "leave", chosen = "live", extra = "bad" }', "request.reading.extra"),
    ],
    ids=["missing-nested", "extra-nested"],
)
def test_nullable_nested_value_error_preserves_its_precise_field(
    tmp_path, reading, key
):
    path = tmp_path / "nested.toml"
    path.write_text(
        """task = "coach.feedback"
source = "requirements 3.11"
[request]
intent = { none = true }
english = "Hi!"
reading = """
        + reading
        + """
earlier_english = []
conversation = []
[[expect]]
kind = "no_fix"
"""
    )

    with pytest.raises(CaseLoadError, match="nested") as caught:
        load_case(path)

    assert key in str(caught.value)


@pytest.mark.parametrize("count", [10, 20], ids=["minimum", "maximum"])
def test_case_set_accepts_range_without_a_hardcoded_sixteen(tmp_path, count):
    for number in reversed(range(count)):
        (tmp_path / f"{number:02d}.toml").write_text(OPENER)

    cases = load_cases(tmp_path)

    assert len(cases) == count
    assert [case.path.name for case in cases] == sorted(
        case.path.name for case in cases
    )
