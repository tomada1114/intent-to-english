# Model evaluation

UTC date: 2026-10-22
Coach: `anthropic/claude-sonnet-5.5`; Partner: `anthropic/claude-haiku-5.5`
Commit: `7819ae2ca10cf58da4b71290ecc31165647e60bd`; dirty: false

Rates include applicable observed outputs only. A parse failure fails schema; content checks and expectations are N/A. Provider failures are N/A for output quality and remain counted in outcomes. Final means the last actual attempt, including a failed repair. Task cost is empty if any attempt has no reported cost.

## Checks

| Rule | First | Final |
| --- | --- | --- |
| blanks_filled | 7/7 (100.0%) | 7/7 (100.0%) |
| build_hint_latin | 1/1 (100.0%) | 1/1 (100.0%) |
| completed_sentence | 10/10 (100.0%) | 10/10 (100.0%) |
| fix_numbers | 7/7 (100.0%) | 7/7 (100.0%) |
| partner_japanese | 4/4 (100.0%) | 4/4 (100.0%) |
| partner_questions | 4/4 (100.0%) | 4/4 (100.0%) |
| partner_sentences | 4/4 (100.0%) | 4/4 (100.0%) |
| partner_share | 1/1 (100.0%) | 1/1 (100.0%) |
| schema | 16/16 (100.0%) | 16/16 (100.0%) |

## Expectations

| Rule | First | Final |
| --- | --- | --- |
| absent | 6/6 (100.0%) | 6/6 (100.0%) |
| accepted | 3/3 (100.0%) | 3/3 (100.0%) |
| differs_from | 1/1 (100.0%) | 1/1 (100.0%) |
| fix_to | 0/1 (0.0%) | 0/1 (0.0%) |
| max_fixes | 1/1 (100.0%) | 1/1 (100.0%) |
| missing_point | 0/2 (0.0%) | 0/2 (0.0%) |
| no_fix | 1/1 (100.0%) | 1/1 (100.0%) |
| no_question | 1/1 (100.0%) | 1/1 (100.0%) |
| no_tag | 1/1 (100.0%) | 1/1 (100.0%) |
| not_tagged | 4/4 (100.0%) | 4/4 (100.0%) |
| reading_noted | 2/2 (100.0%) | 2/2 (100.0%) |
| reading_question | 1/1 (100.0%) | 1/1 (100.0%) |
| tagged | 3/5 (60.0%) | 3/5 (60.0%) |

## Tasks

| Task | Calls | ok | invalid_output | repaired | timeout | rate_limited | provider_error | Cost (credits) | p50 (ms) | p95 (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| coach.acknowledge | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.00186 | 1968 | 1968 |
| coach.check_retry | 3 | 3 | 0 | 0 | 0 | 0 | 0 | 0.031014 | 7089 | 7233 |
| coach.feedback | 8 | 8 | 0 | 0 | 0 | 0 | 0 | 0.117058 | 7138 | 15502 |
| partner.open | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.0000603 | 1533 | 1533 |
| partner.reply | 3 | 3 | 0 | 0 | 0 | 0 | 0 | 0.0005608 | 2473 | 2881 |

## Cases

| Case | Task | Outcomes | Error |
| --- | --- | --- | --- |
| 01-refreshing-feedback | coach.feedback | ok |  |
| 02-refreshing-retry | coach.check_retry | ok |  |
| 03-missing-workplace-point | coach.feedback | ok |  |
| 04-recently-feedback | coach.feedback | ok |  |
| 05-multi-sentence-tag-question | coach.feedback | ok |  |
| 06-reaction-and-missing-tag | coach.feedback | ok |  |
| 07-repeated-reaction | coach.feedback | ok |  |
| 08-starting-as-studying | coach.check_retry | ok |  |
| 09-assets-as-agents | coach.check_retry | ok |  |
| 10-partner-shares | partner.reply | ok |  |
| 11-partner-answers-learner | partner.reply | ok |  |
| 12-already-fine | coach.feedback | ok |  |
| 13-leave-or-live | coach.feedback | ok |  |
| 14-sapporo-only-in-intent | partner.reply | ok |  |
| 15-different-opener | partner.open | ok |  |
| 16-build-hint-without-aws | coach.acknowledge | ok |  |
