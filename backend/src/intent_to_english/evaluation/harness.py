"""Run evaluation cases through the provider-independent task runner."""

from __future__ import annotations

from typing import TYPE_CHECKING

from intent_to_english.core import coaching, partner
from intent_to_english.core import models as m
from intent_to_english.core.services import MODEL_TASKS
from intent_to_english.evaluation.expectations import decide
from intent_to_english.evaluation.observed import (
    Observation,
    ObservedCoach,
    ObservedPartner,
)
from intent_to_english.evaluation.reports import CaseResult, ExpectedResult, Report

if TYPE_CHECKING:
    from collections.abc import Sequence

    from intent_to_english.core.ports import CoachModel, PartnerModel
    from intent_to_english.evaluation.cases import Case
    from intent_to_english.evaluation.reports import CheckValues, RunMetadata


async def run_cases(
    cases: Sequence[Case],
    partner_model: PartnerModel,
    coach_model: CoachModel,
    metadata: RunMetadata,
) -> Report:
    """Run each case once, letting the core alone decide the one repair."""
    results: list[CaseResult] = []
    for case in cases:
        observation = Observation()
        run = await MODEL_TASKS[case.task].run(
            ObservedPartner(partner_model, observation),
            ObservedCoach(coach_model, observation),
            case.request,
        )
        first = _checks(case, observation.outputs[0], run.attempts[0])
        final = _checks(case, observation.outputs[-1], run.attempts[-1])
        results.append(
            CaseResult(
                case,
                run.attempts,
                first,
                final,
                _expectations(case, observation.outputs[0], first),
                _expectations(case, observation.outputs[-1], final),
                run.error.code if run.error else None,
            )
        )
    return Report(metadata, tuple(results))


def _checks(case: Case, output: object, attempt: m.CallAttempt) -> CheckValues:
    applicable: set[m.CheckId] = set()
    optional: set[m.CheckId] = set()
    match case.task:
        case m.ModelTask.OPEN | m.ModelTask.REPLY | m.ModelTask.RESTATE:
            applicable.update(
                (
                    m.CheckId.PARTNER_JAPANESE,
                    m.CheckId.PARTNER_SENTENCES,
                    m.CheckId.PARTNER_QUESTIONS,
                )
            )
            if case.task is m.ModelTask.REPLY:
                if (
                    isinstance(case.request, partner.ReplyRequest)
                    and case.request.share
                ):
                    applicable.add(m.CheckId.PARTNER_SHARE)
                else:
                    optional.add(m.CheckId.PARTNER_SHARE)
        case m.ModelTask.ACKNOWLEDGE:
            applicable.add(m.CheckId.BUILD_HINT_LATIN)
        case m.ModelTask.FEEDBACK:
            checks = {
                m.CheckId.FIX_NUMBERS,
                m.CheckId.BLANKS_FILLED,
                m.CheckId.COMPLETED_SENTENCE,
            }
            target = (
                optional if isinstance(output, coaching.ReadingQuestion) else applicable
            )
            target.update(checks)
        case m.ModelTask.CHECK_RETRY:
            applicable.add(m.CheckId.COMPLETED_SENTENCE)
        case m.ModelTask.ANSWER_QUESTION:
            if (
                isinstance(case.request, coaching.AnswerQuestionRequest)
                and case.request.feedback is not None
            ):
                applicable.add(m.CheckId.COMPLETED_SENTENCE)
            else:
                optional.add(m.CheckId.COMPLETED_SENTENCE)
    bad = {item.check for item in attempt.violations}
    provider_failure = attempt.outcome in {
        m.CallOutcome.TIMEOUT,
        m.CallOutcome.RATE_LIMITED,
        m.CallOutcome.PROVIDER_ERROR,
    }
    schema = None if provider_failure else m.CheckId.SCHEMA not in bad
    values: CheckValues = {"schema": schema}
    for check in sorted(applicable | optional):
        values[check.value] = (
            check not in bad
            if schema and output is not None and check in applicable
            else None
        )
    return values


def _expectations(
    case: Case, output: object, checks: CheckValues
) -> tuple[ExpectedResult, ...]:
    return tuple(
        ExpectedResult(
            kind=item.kind,
            passed=decide(item, output)
            if checks["schema"] and output is not None
            else None,
        )
        for item in case.expectations
    )
