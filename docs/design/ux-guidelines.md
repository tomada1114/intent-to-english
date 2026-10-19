# UX guidelines

| | |
|---|---|
| Product | Intent to English — English small-talk practice: Japanese intent first, the learner's own English, structured feedback, fill-in retry |
| Platforms | Web (React SPA), served locally on the owner's Mac; desktop browsers first (Safari, Chrome) |
| App type | Conversation (text, session-based, no scoring) with an AI assistant's waiting and failure states |
| Related | Requirements: `docs/product/requirements.md` · UX flows: `docs/product/ux-flows.md` · Design direction: `docs/design/design-direction.md` |

## Principles

- **Checked before shown** — nothing a model wrote appears until the server's checks pass
  (requirements §3.11). Decides: no streaming, no partial text, a waiting state instead.
  Gives up: perceived speed on long feedback.
- **One next action, always in view** — every state of a session in progress names what to
  send next and in which language (the 👉 次 line, ux-flows' stage table). Decides: the line
  is never scrolled away or hidden behind a menu. Gives up: one permanent line of height above
  the composer.
- **The learner's words are never lost** — a typed or dictated sentence survives an error, a
  cancel, a stale tab, and a reload. Decides: the composer is never cleared by anything but a
  successful send; the server keeps a submission until its call finishes. Gives up: a little
  server state per stage.

## Navigation

- Model: hub and spoke — S1 Home lists sessions; a session opens in S2 (in progress) or S3
  (ended); 「← 会話一覧」 and the app name return to S1. No sidebar. Why: one session at a time
  gets the full width for the two panes; home is one click away.
- Back behavior: browser back from a session returns to S1 at the same list scroll position
  and loaded pages. Within a session, back never steps through stages — stages are server
  state, not history entries.
- Deep links: every session has its URL `/sessions/{id}`; reloading it restores the exact
  stage (ux-flows F-5). The tab chosen below 1024px is not in the URL; it resets to コーチ.

## Platform conventions

- **Web (desktop first):** two panes at ≥1024px, tabs below (ux-flows §2); smallest
  supported width 320px with no horizontal scrolling of the page (WCAG 1.4.10). Sending is
  ⌘↵ (Ctrl+Enter elsewhere); Enter inserts a newline; a key event with `isComposing` true
  never sends. Esc closes an open hint request or Coach question box and returns focus to the
  control that opened it. No other shortcuts in the MVP. No modal dialogs and no toasts:
  every message lives inline where it happened.

## States

| State | Trigger | Shows | Primary action | Copy pattern |
|---|---|---|---|---|
| First-run empty | no sessions in the list | the one-line purpose and the start button | 新しい会話を始める | 「まだ会話はありません。最初の会話を始めましょう。」 |
| Loading a page | S1 list or a session's state is being fetched | skeletons in the final layout (S1: 3 rows; S2/S3: 3 blocks per pane) | — | — |
| Load failed | the list or the session failed to load | inline banner in place of the content; anything already shown stays | 再読み込み | 「会話の一覧を読み込めませんでした。」 / 「この会話を読み込めませんでした。」 |
| Server unreachable | the app's own API does not answer (the local server is stopped) | banner under the header on every screen | 再試行 | 「アプリのサーバーに接続できません。起動しているか確認してください。」 |
| Waiting for a model | a Partner or Coach call is running | nothing for the first 300 ms; then the status line (「Partner が返事を考えています…」 left pane, 「コーチが確認しています…」 right pane); the composer is disabled with its text kept | — | — |
| Long wait | the same action passes 10 s from the send | the status line becomes 「時間がかかっています（最大2分）」 with [中止] | 中止 | — |
| Cancelled | 中止 | the stage as before the submission, the text back in an enabled composer, one quiet line 「中止しました。」 | 送信 | 「中止しました。」 |
| Model failed | timeout (60 s), rate limited, provider unreachable or erroring, output still invalid after one repair | inline banner in the pane that expected the result; the stage does not move; the composer keeps the text | もう一度 | 「コーチの返事を受け取れませんでした（時間切れ）。」 — reasons: 時間切れ / 混み合っています / 接続できません / 返事の形式が正しくありませんでした; 「Partner の返事を…」 in the left pane |
| Stale state | the server rejects a submission whose stage moved on (another tab, a double send) | banner at the top of the right pane; both panes reload | — | 「別の画面でこの会話が進みました。最新の状態を読み込みました。」 |
| Not found | unknown session id or path | S4 | 会話一覧へ | 「この会話は見つかりませんでした。」 |
| Fixed-response mode | no model key configured | header badge on every screen, with its tooltip (ux-flows §2) | — | 「固定応答モード」 |

## Feedback and loading

| Rule | Value |
|---|---|
| Loading indicator delay | nothing under 300 ms; shown after 300 ms; once shown, kept at least 500 ms — avoids a flash on fast local calls |
| Long waits | at 10 s from the send the status says 「時間がかかっています（最大2分）」 and offers [中止]. Each model call's limit is 60 s (requirements §3.10), and one action may make two (a repair after a failed check), so the screen keeps no timer of its own and never abandons a request by itself: 「時間切れ」 comes from the server's 504 |
| Cancel | abandons the wait: the stage stays as before the submission and the text returns to the composer; a result that arrives after the cancel is discarded by the server, never shown |
| Submissions | wait for the server — no optimistic stage changes, since the next stage depends on a model's output; the send control shows the pending state and blocks a second send |
| Ending a session | 「会話を終える」 stays usable while a call runs and ends the session at once: the server supersedes the call, and its late result is discarded, never shown. It becomes, in place, 「終えて振り返りを作りますか？ [終える] [戻る]」; it reverts by itself after 5 s untouched. No confirmation for [終わる] at the 3-reply check-in, which is already an explicit choice |
| Error placement | input limits → under the composer; a failed load or model call → an inline banner in the pane concerned; a missing session → S4. No toasts, no modals |
| Success feedback | the next block appearing is the confirmation; no separate "sent" messages |

## Forms and validation

The app has three inputs: the composer (1–1,000 characters), the hint request's "what I
can't say" field (1–200 characters), and the Coach question box (1–500 characters).

- Timing: live, as a counter — every field's limit is a length, so there is nothing to
  validate on blur. The counter appears at 90% of the limit (900 / 180 / 450) as 「915 /
  1,000」 and turns to the error style past it.
- Empty: the send control is disabled while the field is empty or whitespace only — the one
  disabled-submit case, because sending nothing has no meaning in any stage.
- Over the limit: the send control is disabled and the message under the field says what to
  fix, linked with `aria-describedby`: 「1,000字以内にしてください（いま1,034字）」.
- A server-side rejection (422) shows the same way under the field; the text is never cleared
  on error.
- Spell checking and autocorrect stay on (the browser's defaults); the app never rewrites what
  the learner typed — a slip is the Coach's to read (requirements §3.4).

## Motion

- Amount: restrained — new blocks, expand and collapse, pane scrolling, and tab changes only.
  Why: the learner's attention belongs on the sentence they are building.
- Durations: 150 ms fade with a 4 px rise for a new Partner line or Coach block · 200 ms for
  expand/collapse (the how-to, a past turn, the question box) · 100 ms cross-fade between
  tabs · smooth scroll to new content only when the pane was within 80 px of its bottom.
- Only `transform` and `opacity` animate.
- Reduced motion (`prefers-reduced-motion: reduce`): the rise is dropped (opacity only, same
  duration); expand/collapse and scrolling are instant.
- The durations are Tailwind duration utilities, not tokens (`docs/architecture/overview.md`
  § Design lock).

## Language and copy

- UI language: Japanese, fixed. The Partner speaks English; the Coach writes Japanese, with
  English only for the phrases it teaches. No language switcher. Every element holding English
  produced by or for the conversation (Partner lines, the learner's English, fixes, templates)
  carries `lang="en"`; the page is `lang="ja"` — screen readers switch voice, and the browser
  spell-checks the right language.
- Formatting: dates and times through `Intl.DateTimeFormat("ja-JP")` — list rows `M/D HH:mm`;
  counts through `Intl.NumberFormat("ja-JP")` (「1,000字」).
- Register: です・ます, short sentences, the learner addressed without a pronoun; the Coach's
  copy follows the prototype's wording (requirements §3). No exclamation marks in system copy;
  the Coach's 「いいですね！」 is the Coach speaking, not the UI.
- Buttons: the action itself — 「送信」「ヒント」「答えを見せて」「スキップ」「会話を終える」「もう一度」 —
  never 「OK」.

| Use | Don't use | For |
|---|---|---|
| Partner | 友達・相手・AI | the English-speaking role, as a label |
| コーチ | 先生・AI・アシスタント | the Japanese-speaking helper |
| 往復 | ターン数・回 | finished replies (「4往復」) |
| ターン | 往復 | one cycle of the core interaction (「コーチ · ターン 5」) |
| 直し方 / あなたの文 / 穴埋め | 修正点・回答・テンプレート | the three parts of the feedback card |
| ミス / 改善 | エラー・提案・スコア | the two fix tags |
| 言い直し | リトライ・再挑戦 | the fill-in retry |
| 組み立てのヒント | アドバイス | the build hint before the English |
| 振り返り | 結果・レポート・成績 | the wrap-up |

## Accessibility targets

| Target | This product |
|---|---|
| Level | WCAG 2.2 AA + 2.4.13 Focus appearance |
| Focus ring | 2 px solid `outline`, 2 px offset, on `:focus-visible` only; color from the design direction's focus token, ≥3:1 against every surface it sits on (measured there) |
| Minimum target size | 44×44 px for the send control and the stage's primary buttons; 32 px tall for secondary controls (restate links, tags' toggles) with at least 8 px between targets; 24×24 px absolute floor |
| Keyboard | every control reachable and operable by keyboard; focus order = visual order (left pane, then right pane top to bottom); nothing exists only on hover |
| Focus after a stage change | when a result arrives, focus goes to the composer, or to the first control when the composer is hidden (check-in, reading check); a new Coach block or Partner line never steals focus from a field the learner is typing in |
| Focus not obscured | the header is the only sticky region: `scroll-padding-top` = 48 px + 8 px |
| Live regions | each new Partner line and each new Coach block is announced once, politely (「Partner: …」「コーチ: <the block's first line>」); waiting status changes are polite; model-failure and stale-state banners are assertive |
| Structure | landmarks `header` and `main`; inside `main`, two labelled regions 「会話」 and 「コーチ」 (≥1024px) or a WAI-ARIA tablist with the same names (<1024px); one `h1` per page, `h2` per pane |
| Color use | never the only carrier: the ミス / 改善 tags are text labels, the fixed-response badge is text, an error banner has an icon and text |
| Text scaling | 200% without loss; reflow at 320 px |
| Reduced motion / forced colors | see Motion; focus rings and boundaries use `outline` / `border`, never `box-shadow` alone |
| Contrast | measured: 49 light and dark pairs pass AA (2026-10-17) — the "Measured contrast" table in `docs/design/design-direction.md`, pairs in `docs/design/contrast-pairs.json` |

Verification for the implementing session: keyboard-only pass through flows F-1 to F-9;
VoiceOver (Safari) pass on F-2, checking that English lines are read with an English voice;
achromatopsia simulation in DevTools on S2.

## App-type rules

- **No streaming; the wait is visible and stoppable** — the AI-assistant pattern's "always a
  stop control" is met by [中止] from 10 s, under "Checked before shown". Why: short local
  calls finish before 10 s, and a cancel button flashing on every call is noise.
- **Auto-scroll yields to the reader** — a pane scrolls to new content only when it was at the
  bottom (Motion). Why: the learner often scrolls up to re-read the fixes while typing.
- **No scores after a session** — S3 opens directly with the wrap-up; no score view, gauges,
  or summary modal (requirements P6).

## Non-goals

| Not doing | Why | Covered instead by |
|---|---|---|
| Toasts | messages that disappear get missed, and every message here belongs to a place | inline banners and lines |
| Modal dialogs | nothing in the MVP needs to block the page | in-place confirmation for ending |
| Keyboard shortcuts beyond ⌘↵ and Esc | one user, few actions; shortcuts would need a help surface | visible buttons |
| Sound | no audio in the MVP (requirements: reading aloud is Later) | — |

## Decision log

| Date | Decided | Rejected options | Why |
|---|---|---|---|
| 2026-10-17 | Navigation, platform, device priority, empty states, error placement, UI language taken from requirements and ux-flows, not asked | — | already settled there: hub and spoke, web desktop-first, single local user, Japanese UI |
| 2026-10-17 | Ending asks once, in place, reverting after 5 s | end at once (the prototype); 5 s undo | an ended session cannot be reopened, so one stray click must not end it; undo would delay the wrap-up call |
| 2026-10-17 | Long waits: explanation and [中止] at 10 s | a waiting line only; a running seconds counter | a 60 s silent wait looks frozen; a counter pulls attention from the sentence being built |
| 2026-10-17 | Motion restrained, 100–200 ms | moderate (press effects, retry celebration); none | the learner's attention stays on the sentence; with none, a new block is easy to miss |
| 2026-10-17 | WCAG 2.2 AA + 2.4.13 focus appearance | AA only; AA + selected AAA | one focus ring decided now stays consistent; AAA contrast would constrain the palette for no audience need |
| 2026-10-17 | Contrast measured on the chosen palette: 49 pairs pass AA | — | the design direction's token values, light and dark |
