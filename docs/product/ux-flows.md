# Intent to English — Screens and flows

Screens, layouts, and user flows for the MVP in `requirements.md` (cited as §n / Fn). App-wide
behavior — navigation model, state timing, feedback, validation timing, motion, language, and
accessibility targets — is `docs/design/ux-guidelines.md`'s; this document cites it rather than
restating it. Visual style (palette, type, tokens) is `docs/design/design-direction.md`'s.

UI copy is Japanese (the learner's language); the Partner speaks English. Strings in 「」 or
quoted inside a wireframe are the copy to use.

## 1. Screen inventory

| ID | Screen | Route | Serves |
|---|---|---|---|
| S1 | Home — start, resume, and the session list | `/` | F1, F9, F10 |
| S2 | Conversation, in progress — two panes: Conversation and Coach | `/sessions/$sessionId` | F1–F8, F10 |
| S3 | Conversation, ended — the same route, read-only | `/sessions/$sessionId` | F8, F9 |
| S4 | Not found — an unknown session id or path | any unmatched route, or a session id the API does not know | F9 |

No settings screen: models and the provider key come from the environment (§3.10). No modal
dialogs in the MVP; everything happens in the page.

## 2. Layout rules for every screen

- **Header** (48px, full width): the app name 「Intent to English」 linking to S1, the page's own
  items, and on the right the **fixed-response badge** 「固定応答モード」 when no model key is
  set (§3.10). The badge has a tooltip: 「OpenRouter のキーが未設定のため、決まった応答で動いています。
  品質の確認には使えません。」 It shows on every screen while the mode is on.
- **Widths**: S1 and S4 center a single column, max 880px. S2 and S3 use the full width.
  Breakpoint: **≥1024px** two panes side by side; **<1024px** the two panes become tabs
  （会話・コーチ）. Smallest supported width: 320px (ux-guidelines § Platform conventions).
- **Sending**: ⌘↵ (Ctrl+Enter off macOS) sends the composer; Enter inserts a newline. A key
  press during IME composition never sends (Japanese input and dictation both compose).

## 3. Wireframes

### S1 Home

```
≥1024px (centered column, max 880px)
┌──────────────────────────────────────────────────────────────────────────┐
│ Intent to English                                        [固定応答モード] │ ← badge only when keyless
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   英語で話す前に、日本語で言いたいことを決める練習                          │ ← one-line tagline
│                                                                          │
│   [ 新しい会話を始める ]                                                  │ ← primary; focused on load
│                                                                          │
│   ┌ 続きから ──────────────────────────────────────────────────────────┐ │ ← only when a session
│   │ 🗣 Hey! How was your weekend?                                       │ │   is in progress: the
│   │ 10/17 18:40 から · 4往復                              [ 続ける ]   │ │   most recent one
│   └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│   これまでの会話                                                          │
│   ────────────────────────────────────────────────────────────────────   │
│   10/17 18:40   進行中   4往復   Hey! How was your weekend?               │ ← whole row is a link
│   10/16 21:02   終了     9往復   Hi! How's it going?                      │   to S2 / S3
│   10/15 07:55   終了     3往復   Morning! Did you sleep well?             │
│   …                                                                      │
│   [ さらに表示 ]                                                          │ ← next cursor page (20)
└──────────────────────────────────────────────────────────────────────────┘
```

- Row: start time (local, `M/D HH:mm`), status 「進行中」/「終了」, finished replies
  「N往復」, the Partner's opener truncated to 60 characters with 「…」.
- 「新しい会話を始める」 creates the session and goes straight to S2; the opener arrives there
  (flow F-1).
- **Empty** (no sessions): the 続きから card and the list are replaced by 「まだ会話はありません。
  最初の会話を始めましょう。」 under the primary button.
- **Loading**: the list area shows 3 skeleton rows (timing per ux-guidelines § States); the
  primary button is usable at once.
- **Error** (the list failed): an inline banner 「会話の一覧を読み込めませんでした。」
  [再読み込み] in place of the list; the primary button still works.
- **More**: 「さらに表示」 appears only while another page exists.

### S2 Conversation — in progress (≥1024px)

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ Intent to English   ← 会話一覧   10/17 18:40 から · 4往復          [会話を終える] [固定応答モード] │
├──────────────────────────────────────┬───────────────────────────────────────────────┤
│ 会話（Partner が聞いている英語）        │ コーチ · ターン 5                              │
│                                      │                                               │
│ 🗣 Partner                            │ あなたの日本語            [日本語を書き直す]     │
│ Hey! How was your day today?         │ 毎日英語とプログラムの勉強を習慣にしてるけど、    │
│                                      │ 今日は朝のうちに全部済ませられて気分がいい        │
│                       You 🙂          │                                               │
│ I feel refreshed today because I     │ 💡 いいですね！                                │
│ finished my daily English and        │                                               │
│ programming routine this morning.    │ あなたの英語                                   │
│                                      │ I feel refreshing today because I completed   │
│ 🗣 Partner                            │ my study routine in the morning about …       │
│ Oh nice! What kind of programming    │ ┌ 💡 コーチ ─────────────────────────────────┐ │
│ are you studying these days?         │ │ 意図は伝わっています                         │ │
│               [言い換え: 短く｜簡単に] │ │ 直し方                                      │ │
│                                      │ │ ① 元: refreshing → 直す: refreshed          │ │
│                                      │ │    なぜ（ミス）: 自分の気分は -ed            │ │
│                                      │ │ ② 元: completed → 直す: finished            │ │
│                                      │ │    なぜ（改善）: 元のままでも通じる。…       │ │
│                                      │ │ あなたの文                                  │ │
│                                      │ │ I feel refreshing today because I …         │ │
│                                      │ │ 穴埋め                                      │ │
│                                      │ │ I feel (①) ____ today because I (②) ____ …  │ │
│                                      │ └────────────────────────────────────────────┘ │
│                                      │ 👉 次: 直し方を見返しながら穴を埋めて、          │
│                                      │    英語の文全体を送ってください（「スキップ」も可） │
│                                      │ ┌───────────────────────────────────────────┐ │
│                                      │ │ 英文全体を入力…                             │ │
│                                      │ └───────────────────────────────────────────┘ │
│                                      │ [スキップ] [答えを見せて]          [送信 ⌘↵]   │
│                                      │ ▸ コーチに質問（会話は進みません）               │
└──────────────────────────────────────┴───────────────────────────────────────────────┘
  left pane: 42% (min 360px)               right pane: 58% (min 480px); each scrolls on its own
```

**Left pane — Conversation** (P7 made visible: only what the Partner hears).

- Partner lines (🗣 Partner) and the learner's finished English of each turn (You), in order.
  The learner's line appears once the turn is done: the accepted retry, or the latest English
  when the retry was skipped or the turn needed no fix.
- **Restate**: under the latest Partner line, while it awaits a reply: 「言い換え: 短く｜簡単に」.
  The restated line appears under the original, labelled 「言い換え（短く）」 or
  「言い換え（簡単に）」; the right pane's stage is unchanged (§3.7).
- **Select a past turn**: clicking one of the learner's lines shows that turn's full coaching
  in the right pane, read-only, with 「今のターンに戻る」 at the top.
- Waiting for the Partner: a line 「Partner が返事を考えています…」 at the end of the pane.
- New content scrolls the pane to the bottom unless the learner has scrolled up.

**Right pane — Coach** (the current turn, top to bottom).

1. Title 「コーチ · ターン N」.
2. **The finished previous turn** (only between turns, until the learner's next reply): one
   collapsed line 「前のターン: 言い直しできました」 / 「前のターン: スキップしました」 with
   [もう一度練習] — reopens that turn's template here (§3.7 Practice again).
3. The learner's **Japanese intent**, with 「日本語を書き直す」 until the turn is done. A
   rewritten intent replaces the shown one; the blocks tied to the old one collapse under
   「書き直す前のやりとり」.
4. Coach blocks and learner entries of this turn, in order: the acknowledgment and the
   optional 「組み立てのヒント: …」; gap requests and their hints; English attempts; the
   **feedback card**; retry submissions and their results; a shown answer; questions to the
   Coach and their answers (labelled 「質問」/「💡 コーチ」, visually lighter). A skip shows
   the fixed line 「スキップして会話に戻ります」 (no model call).
5. **Feedback card**: 「意図は伝わっています」 (or the missing points) → 「直し方」 (①… in
   sentence order; 元 → 直す; なぜ with the tag 「ミス」 or 「改善」, the tag as a small label) →
   「あなたの文」 (verbatim) → 「穴埋め」 directly under it (blanks rendered as numbered gaps
   `(①) ____`). The card stays in view above the composer while the learner types.
6. **Next action** line 「👉 次: …」 — always present above the composer; wording from the
   stage table below.
7. **Composer**: one textarea (grows to 6 lines, then scrolls), placeholder by stage, a
   character counter from 900/1,000, [送信 ⌘↵].
8. **Control row**, by stage (table below).
9. 「▸ コーチに質問（会話は進みません）」 — expands a one-line input (1–500 characters) and
   [質問する]. The answer appears in the turn's blocks; the next-action line repeats.

**Stage table** — what the composer and controls are at each stage (§3.2–§3.8).

| Stage | Composer placeholder | Controls | 👉 次 |
|---|---|---|---|
| Waiting for the opener or a Partner reply | (disabled) | — | 「Partner の返事を待っています」 |
| Intent | 「返したいことを日本語で」 | [英語で直接返す] (switches the composer to English for this turn) | 「返したいことを日本語で送ってください（英語で返してもOK）」 — after a Partner share: 「反応や、相手への質問を日本語で送ってください（英語で返してもOK）」 |
| English | 「英語にしてみましょう（途中まででOK）」 | [ヒント] [答えを見せて] | 「それを英語にしてみてください（途中まででOK。詰まったら「ヒント」）」 |
| Hint request (inline under the composer) | 「分からないところ（例: 「久しぶり」が分からない）」 (1–200 characters) + the composer keeps any partial English | [ヒントをもらう] [やめる] | 「分からないところを書いて、ヒントをもらってください」 |
| After a hint | 「英語の文全体を」 | [ヒント] [答えを見せて] | 「ヒントを使って、英語の文全体を送ってください」 |
| Coach checking (any Coach call) | (disabled, text kept) | — | 「コーチが確認しています…」 |
| Retry | 「穴を埋めた英文全体を」 | [スキップ] [答えを見せて] | 「直し方を見返しながら穴を埋めて、英語の文全体を送ってください（「スキップ」も可）」 |
| One blank still off | 「穴を埋めた英文全体を」 | [スキップ] [答えを見せて] | 「③の穴だけ埋め直して、英語の文全体をもう一度送ってください」 (names the blank) |
| Answer shown | 「見ながら1回打ってみましょう」 | [スキップ] | 「完成例を見ながら、英語の文全体を1回送ってください（「スキップ」で会話に戻ります）」 |
| Reading check (slip with two readings) | (hidden) | [A のつもり] [B のつもり] — the two readings as buttons | 「どちらのつもりか選んでください」 |
| Check-in (after reply 3, 6, 9…) | (hidden) | [続ける] [終わる] | 「「続ける」か「終わる」を選んでください」 |

- 「会話を終える」 in the header works at every stage, mid-retry included, and ends at once
  (§3.8; confirmation policy per ux-guidelines § Feedback).
- **New session**: the right pane opens with the how-to block 「進め方」 (the prototype's four
  lines, adapted to the controls: 「1. 返したいことを、まず日本語で送ってください」「2. それを自分で英語にしてみてください
  （途中まででOK。詰まったら「ヒント」）」「3. 最初から英語で返すときは「英語で直接返す」」「4. 「答えを見せて」「スキップ」
  「会話を終える」はいつでも使えます」), collapsible, shown at the top of turn 1 only.
- **Loading the session**: both panes show skeleton blocks; the composer appears with the state.
- **Model error**: an inline banner in the pane that expected the result — 「コーチの返事を受け取れ
  ませんでした（時間切れ）」 / 「…（混み合っています）」 / 「…（接続できません）」 /
  「…（返事の形式が正しくありませんでした）」, with [もう一度]. The learner's text stays in the
  composer; the stage does not move (§3.10).
- **Stale state** (another tab moved the session): a banner 「別の画面でこの会話が進みました。
  最新の状態を読み込みました。」 and the panes reload (§4 of the requirements).

### S2 / S3 below 1024px — tabs

```
┌────────────────────────────────────┐
│ ← 一覧   4往復        [会話を終える] │
├────────────────────────────────────┤
│ [ 会話 ]  [ コーチ ●]               │ ← the tab with new content gets a dot
├────────────────────────────────────┤
│ 🗣 返事をする発言                    │ ← Coach tab only: the Partner line being
│ What kind of programming are you   │   answered, pinned at the top
│ studying these days?               │
│ ────────────────────────────────── │
│ …the Coach pane, same order as ≥1024px…│
└────────────────────────────────────┘
```

- During a session the Coach tab is selected by default; a new Partner line marks the
  Conversation tab with a dot and also appears pinned at the top of the Coach tab.

### S3 Conversation — ended (read-only)

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ Intent to English   ← 会話一覧   10/16 21:02 – 21:38 · 9往復 · 終了            [固定応答モード] │
├──────────────────────────────────────┬───────────────────────────────────────────────┤
│ 会話（英文だけの通し）                 │ この会話で出てきた表現                           │
│                                      │ ・I feel refreshed（自分の気分は -ed）            │
│ 🗣 Hey! How was your day today?       │ ・these days（今の状態の「最近」）                │
│ 🙂 I feel refreshed today because…    │ ・in the industry（「現場」= 業界）               │
│ 🗣 Oh nice! What kind of …            │ ────────────────────────────────────────────── │
│ 🙂 I have been studying AWS, which …  │ ターンごとのやりとり                             │
│ …                                    │ ▸ ターン 1  I feel refreshed today because …     │
│                                      │ ▾ ターン 2  I have been studying AWS, which …    │
│                                      │    あなたの日本語 / 💡 / あなたの英語 /            │
│                                      │    添削カード / 言い直し / 結果                    │
│                                      │ ▸ ターン 3  …                                    │
└──────────────────────────────────────┴───────────────────────────────────────────────┘
```

- Left: every Partner line and the learner's finished English, nothing else — the prototype
  log's closing section, read straight through.
- Right: the wrap-up (two or three items, as things that came up; never "mastered"), then
  every turn collapsed to one line (turn number and the learner's finished English);
  expanding shows that turn's complete timeline as in S2, without composer or controls.
  Clicking a learner line on the left expands its turn on the right.
- No composer, no controls, no next-action line. No "続ける" — an ended session cannot be
  reopened.
- A session ended before any feedback has no wrap-up: the right pane starts with the turn
  list.

### S4 Not found

```
┌──────────────────────────────────────────────┐
│ Intent to English                            │
├──────────────────────────────────────────────┤
│   この会話は見つかりませんでした。              │
│   [ 会話一覧へ ]                              │
└──────────────────────────────────────────────┘
```

## 4. Flows

### F-1 Start a session

1. S1 → 「新しい会話を始める」.
2. The session is created; S2 opens with the how-to (right) and 「Partner が返事を考えています…」
   (left).
3. The opener appears (greeting + one simple question); the right pane moves to Intent.

```
[S1] -> [新しい会話を始める] -> [S2: waiting for opener] -> [opener shown] -> [Intent]
                                        |
                                        v
                         [error banner + もう一度] -> [waiting for opener]
```

### F-2 One turn (the core interaction)

1. Intent: the learner sends Japanese → 💡 「いいですね！」, at most one 組み立てのヒント → English.
   (Or [英語で直接返す] → the composer takes English → step 3.)
2. English: the learner sends English (full or partial). Stuck → [ヒント] with the gap →
   a gap hint → English again; asking again for the same gap gives a bigger piece.
3. Feedback: no fix needed → one line → step 6. Fixes → the feedback card → Retry.
   A slip with two readings that changes the feedback → Reading check → feedback.
4. Retry: the learner sends the whole sentence. All acceptable → one line → step 6.
   A blank off → named, bigger hint → second submission → still off → the Coach gives that
   piece → step 6.
5. [スキップ] at Retry or Answer shown → one neutral line → step 6.
   [答えを見せて] at English or Retry → the example → Answer shown → one typed copy or
   [スキップ] → step 6.
6. The turn is done: the learner's finished English moves to the left pane; the Partner
   replies; reply 3, 6, 9… → F-3 first. Next turn.

```
[Partner line] -> [Intent] -> [English] -> [Feedback] -> [Retry] -> [done] -> [Partner reply]
                     |           |  ^          |            |  ^
                     |        [Hint]-┘          |      [blank off]
                     |           |              |            |
                     |    [答えを見せて] -------+-------> [Answer shown] -> [type once | スキップ]
                     |                          |
             [英語で直接返す] ----------------->+-- no fix ------------------------> [done]
Any Coach or Partner call: [error banner + もう一度] — the stage stays, the text stays.
```

### F-3 Check-in and ending

1. After the 3rd, 6th, 9th… finished reply: 💡 「ここで3往復です。続けますか？」 → [続ける]
   (the Partner continues) or [終わる].
2. 「会話を終える」 (header) or [終わる] at any stage → the wrap-up is generated → S3.

```
[reply 3k done] -> [Check-in] -> 続ける -> [Partner reply] -> [Intent]
                        |
                      終わる
                        v
[会話を終える (any stage)] -> [waiting: wrap-up] -> [S3]
                                     |
                                     v
                    [error banner + もう一度] — the session stays in progress until the wrap-up exists
```

### F-4 Ask the Coach

1. Any stage of a session in progress → 「コーチに質問」 → the question (1–500 characters) →
   [質問する].
2. The answer appears in the current turn's blocks; the stage and its 👉 次 line are unchanged.

### F-5 Resume

1. S1 「続ける」 or a list row → S2 at the exact stage.
2. If the last submission's model call never finished (server stop, closed tab), the stage is
   the one before it and the composer is pre-filled with the submitted text and [送信].

### F-6 Read an ended session

1. S1 list row (終了) → S3. Learner line or turn row → that turn's timeline.

### F-7 Rewrite the intent

1. Intent sent, turn not done → 「日本語を書き直す」 → the composer switches to Japanese,
   pre-filled with the old intent.
2. Send → the old turn blocks collapse under 「書き直す前のやりとり」 → acknowledgment → English.

### F-8 Restate the Partner's line

1. The latest Partner line → 「言い換え: 短く」 or 「簡単に」 → the restated line under it.
   The right pane does not change.

### F-9 Practice again

1. Between turns, 「前のターン」 line → [もう一度練習] → that turn's template and composer in
   the right pane → send → result → back to the current stage.

## 5. Cross-cutting behavior

Per screen, the rules are ux-guidelines.md's:

- **States** (loading skeleton timing, empty, error, waiting for a model): § States — S1 list,
  S2 panes, S3 panes.
- **Feedback** (inline banners, the end action's confirmation policy, the stale-state banner):
  § Feedback.
- **Validation** (limits 1–1,000 / 1–500 characters, when the counter shows, empty send
  disabled): § Form validation.
- **Language and copy** (Japanese UI, English Partner, the tag labels ミス / 改善): § Language.
- **Accessibility** (focus after each stage change, live regions for new Partner and Coach
  blocks, keyboard operation of every control, tab semantics below 1024px): § Accessibility.
- **Motion** (new blocks, pane scrolling, tabs): § Motion.
