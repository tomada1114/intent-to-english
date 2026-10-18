"""Deterministic fixed-mode triggers for API and browser tests (Issue #17).

All methods ignore repair and keep no state. Usage is fixed/fixed, no tokens or
cost, and latency 0 ms. The service still runs the real checks and its one repair.

Partner open selects the first opener different from previous_opener, in order:
``Hey! How's it going?``, ``Hi! How was your weekend?``,
``Hey! How was your day today?``. None selects the first.
Reply is ``Nice! What did you do after that?``; share instead returns
``I went for a long walk by the river today.`` without a question.
Restate shorter is ``What's new?``; simpler is ``How are you doing?``.

Acknowledge is 「いいですね\uff01」. Only an intent containing 「久しぶり」 adds
「「久しぶりに」は「長いあいだしていなかった」と言い換えると組み立てやすいです」.
The first gap hint is 「「<gap>」の部分は kind of から始めてみてください」;
the same stripped gap again gives 「「<gap>」の部分は it was kind of fun のように言えます」.

Feedback tries leave, !, refreshing, then the default, in that order. Leave and
refreshing are case-insensitive whole words; ! is the last non-space character.
Unchosen leave asks leave/live; a choice never asks again. Choosing live records
leave as live (「leave は live として読みました」) and interprets the English that way.
Bang means no fix: 「いいですね\uff01そのままで伝わります」. A one-word default also
uses that line so a single replacement cannot leak the whole completed sentence.
After leave/!, learner text containing circled numbers ① through ⑳ or two consecutive
underscores uses that no-fix line too: those reserved template markers cannot be
copied into a retry without violating the core checks. Reading notes are retained.
Refreshing gets one ミス fix to refreshed, with reason
「自分の気分は -ed。-ing だと「人をさわやかにさせる」」. The default's first word
gets an 改善 fix to ``Actually, <word>``, with reason
「元のままでも通じる。Actually, で始めると話を続ける感じが出る」.
With intent the first line is 「意図は伝わっています」, adding
「。元のままでも通じます」 for 改善; without intent 改善 says only
「元のままでも通じます」, and ミス uses its explanation without judging intent.
The template replaces that word with ``(①) ____``; the request is
「(①) を埋めて、文全体をもう一度送ってください」.

`check_retry` (also practice) accepts case-insensitive containment of every fix's
replacement: 「いいですね\uff01伝わります」. The first absent fix gets
「①がまだ違います。<first letter> で始まります」 on submission 1, then the piece
and 「①は <replacement> です」 on submission 2 (using that fix's number).
`show_answer` at english is ``I had a relaxing day, so I feel good.``; at retry it
fills every numbered blank. `answer_question` is
「会話では、短い文に分けて言っても十分に伝わります」.
`wrap_up` has two items and no question: ``Actually, …`` with
「話を続けるときの切り出し方として出てきました」, and ``I feel refreshed`` with
「自分の気分を -ed で言う形が出てきました」.
"""

from __future__ import annotations

import re

from intent_to_english.core import coaching as c
from intent_to_english.core import models as m
from intent_to_english.core import partner as p

_USAGE = m.Usage("fixed", "fixed", None, None, None, 0)
_OPENERS = (
    "Hey! How's it going?",
    "Hi! How was your weekend?",
    "Hey! How was your day today?",
)
_LEAVE = re.compile(r"\bleave\b", re.IGNORECASE)
_REFRESHING = re.compile(r"\brefreshing\b", re.IGNORECASE)
_BLANK = re.compile(r"\(([①-⑳])\) ____")
_RESERVED_MARKER = re.compile(r"[①-⑳]|_{2,}")
_NO_FIX = "いいですね\uff01そのままで伝わります"
_MISS_REASON = "自分の気分は -ed。-ing だと「人をさわやかにさせる」"
_IMPROVEMENT_REASON = "元のままでも通じる。Actually, で始めると話を続ける感じが出る"


class FixedPartnerModel:
    """Implement the Partner tasks without state or network access."""

    async def open(
        self, request: p.OpenRequest, repair: m.Repair | None = None
    ) -> m.Parsed[p.PartnerLine]:
        """Choose the first fixed opener that differs from the previous one."""
        del repair
        return _parsed(
            p.PartnerLine(
                next(line for line in _OPENERS if line != request.previous_opener)
            )
        )

    async def reply(
        self, request: p.ReplyRequest, repair: m.Repair | None = None
    ) -> m.Parsed[p.PartnerLine]:
        """Obey the service's taking-turns decision."""
        del repair
        return _parsed(
            p.PartnerLine(
                "I went for a long walk by the river today."
                if request.share
                else "Nice! What did you do after that?"
            )
        )

    async def restate(
        self, request: p.RestateRequest, repair: m.Repair | None = None
    ) -> m.Parsed[p.PartnerLine]:
        """Return the fixed shorter or simpler wording."""
        del repair
        return _parsed(
            p.PartnerLine(
                "What's new?"
                if request.mode is m.RestateMode.SHORTER
                else "How are you doing?"
            )
        )


class FixedCoachModel:
    """Implement the Coach tasks as pure functions of each request."""

    async def acknowledge(
        self, request: c.AcknowledgeRequest, repair: m.Repair | None = None
    ) -> m.Parsed[c.Acknowledgment]:
        """Give the Japanese build hint only for its documented intent trigger."""
        del repair
        hint = (
            "「久しぶりに」は「長いあいだしていなかった」と言い換えると組み立てやすいです"
            if "久しぶり" in request.intent
            else None
        )
        return _parsed(c.Acknowledgment("いいですね\uff01", hint))

    async def gap_hint(
        self, request: c.GapHintRequest, repair: m.Repair | None = None
    ) -> m.Parsed[c.GapHint]:
        """Increase the piece when the stripped gap appeared in earlier hints."""
        del repair
        gap = request.gap.strip()
        repeated = any(earlier.gap.strip() == gap for earlier in request.earlier)
        piece = (
            "it was kind of fun のように言えます"
            if repeated
            else "kind of から始めてみてください"
        )
        return _parsed(c.GapHint(f"「{gap}」の部分は {piece}"))

    async def feedback(
        self, request: c.FeedbackRequest, repair: m.Repair | None = None
    ) -> m.Parsed[c.Feedback | c.ReadingQuestion]:
        """Apply the documented trigger order to interpreted learner English."""
        del repair
        if _LEAVE.search(request.english) and request.reading is None:
            return _parsed(c.ReadingQuestion("leave", ("leave", "live")))
        english, notes = _read_english(request)
        if english.rstrip().endswith("!") or _RESERVED_MARKER.search(english):
            return _parsed(c.Feedback(_NO_FIX, readings_noted=notes))
        refreshing = _REFRESHING.search(english)
        if refreshing is not None:
            return _parsed(
                _feedback(request, english, refreshing.group(), m.FixTag.MISS, notes)
            )
        words = english.split()
        if len(words) <= 1:
            return _parsed(c.Feedback(_NO_FIX, readings_noted=notes))
        first = words[0]
        return _parsed(_feedback(request, english, first, m.FixTag.IMPROVEMENT, notes))

    async def check_retry(
        self, request: c.CheckRetryRequest, repair: m.Repair | None = None
    ) -> m.Parsed[c.RetryResult]:
        """Accept all present replacements or report the first absent piece."""
        del repair
        missing = next(
            (
                fix
                for fix in request.feedback.fixes
                if fix.replacement.casefold() not in request.sentence.casefold()
            ),
            None,
        )
        if missing is None:
            return _parsed(c.RetryAccepted("いいですね\uff01伝わります"))
        number = chr(ord("①") + missing.number - 1)
        if request.submission_number == 1:
            return _parsed(
                c.BlankOff(
                    (missing.number,),
                    f"{number}がまだ違います。{missing.replacement[0]} で始まります",
                )
            )
        return _parsed(
            c.PieceGiven(
                (c.Piece(missing.number, missing.replacement),),
                f"{number}は {missing.replacement} です",
            )
        )

    async def show_answer(
        self, request: c.ShowAnswerRequest, repair: m.Repair | None = None
    ) -> m.Parsed[c.Answer]:
        """Show the requested complete example, exempt from the leak check."""
        del repair
        if request.stage is m.Stage.RETRY and request.feedback is not None:
            return _parsed(c.Answer(_fill_template(request.feedback)))
        return _parsed(c.Answer("I had a relaxing day, so I feel good."))

    async def answer_question(
        self, request: c.AnswerQuestionRequest, repair: m.Repair | None = None
    ) -> m.Parsed[c.CoachAnswer]:
        """Answer in Japanese without advancing the conversation."""
        del request, repair
        return _parsed(
            c.CoachAnswer("会話では、短い文に分けて言っても十分に伝わります")
        )

    async def wrap_up(
        self, request: c.WrapUpRequest, repair: m.Repair | None = None
    ) -> m.Parsed[c.WrapUp]:
        """Return the two fixed expressions without a question or score."""
        del request, repair
        return _parsed(
            c.WrapUp(
                (
                    c.WrapUpItem(
                        "Actually, …", "話を続けるときの切り出し方として出てきました"
                    ),
                    c.WrapUpItem(
                        "I feel refreshed", "自分の気分を -ed で言う形が出てきました"
                    ),
                )
            )
        )


def _parsed[T](output: T) -> m.Parsed[T]:
    return m.Parsed(output, _USAGE)


def _read_english(request: c.FeedbackRequest) -> tuple[str, tuple[c.ReadingNote, ...]]:
    if (
        request.reading is None
        or request.reading.word.casefold() != "leave"
        or request.reading.chosen.casefold() != "live"
    ):
        return request.english, ()
    words = dict.fromkeys(match.group() for match in _LEAVE.finditer(request.english))
    notes = tuple(c.ReadingNote(word, "live") for word in words)
    return _LEAVE.sub("live", request.english), notes


def _feedback(
    request: c.FeedbackRequest,
    english: str,
    original: str,
    tag: m.FixTag,
    notes: tuple[c.ReadingNote, ...],
) -> c.Feedback:
    improvement = tag is m.FixTag.IMPROVEMENT
    replacement = "Actually, " + original if improvement else "refreshed"
    reason = _IMPROVEMENT_REASON if improvement else _MISS_REASON
    template = (
        english.replace(original, "(①) ____", 1)
        if improvement
        else _REFRESHING.sub("(①) ____", english, count=1)
    )
    first_line = "意図は伝わっています" if request.intent is not None else reason
    if improvement:
        first_line = (
            first_line + "。" if request.intent is not None else ""
        ) + "元のままでも通じます"
    return c.Feedback(
        first_line,
        (c.Fix(1, original, replacement, reason, tag),),
        request.english,
        template,
        "(①) を埋めて、文全体をもう一度送ってください",
        notes,
    )


def _fill_template(feedback: c.Feedback) -> str:
    replacements = {fix.number: fix.replacement for fix in feedback.fixes}
    return _BLANK.sub(
        lambda match: replacements[ord(match[1]) - ord("①") + 1],
        feedback.template or "",
    )
