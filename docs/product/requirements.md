# Intent to English — Requirements

- **Status:** Signed off 2026-10-17
- **Platform and stack:** a web app the owner runs locally on their Mac. Built from
  `tomada1114/fastapi-react-template`: an async FastAPI backend over a framework-free core
  with ports and adapters, SQLAlchemy Core + Alembic on SQLite, a React + Vite + TypeScript
  screen (TanStack Router and Query, Tailwind CSS 4) calling the API through a generated
  client, and a Playwright browser test. Models are called through OpenRouter now and
  Amazon Bedrock later, behind ports.

## 1. Overview

**What it is.** An English small-talk practice app. An AI friend (the Partner) chats in
short English lines. Before answering, the learner writes what they really want to say in
Japanese, then builds the English themselves. An AI coach (the Coach) helps only where they
get stuck, checks the English against the Japanese intent, and turns every fix into a
fill-in-the-blank retry. Then the Partner replies to the learner's English and the
conversation goes on.

**Target user.** A Japanese speaker around CEFR B1 who can think of what to say in Japanese
and can build simple English sentences, but who, in a live conversation, shrinks what they
say to the English they already know: the same reactions and short answers, and the thing
they meant to say given up. The MVP has one user, the owner, on their own Mac. The app is
also the owner's portfolio product #1: a product with an LLM built in, with structured
output, evaluation, and a swappable model provider.

**Core interaction — one turn.** Partner line → the learner's Japanese intent → the
learner's own English (hints only for the gap they name) → structured feedback (intent
check → fixes in sentence order → their sentence → a numbered fill-in template) → the
fill-in retry (skippable) → the Partner replies to the learner's latest English. If this
turn is not good, nothing else matters.

**Principles every feature keeps.**

- **P1 Don't shrink the intent.** The learner's Japanese is the yardstick: every core point
  and nuance in it must survive into the English. Splitting into short sentences is fine.
  Only the learner may narrow or replace the intent.
- **P2 The learner builds the English first.** No finished English sentence is shown before
  they try, except for the one spot they explicitly ask an answer for.
- **P3 Help only where they are stuck.**
- **P4 Reuse the fixes.** Any fix means one fill-in retry by default; the learner can skip.
- **P5 Natural English that carries the whole intent is a success.** No literal match with
  the Japanese is required; a correct word other than the one suggested is not a mistake.
- **P6 No scores, CEFR levels, report cards, or "mastered" labels.**
- **P7 The Partner never sees the Japanese intent.** It reacts only to the English and the
  conversation so far. The prototype could only instruct this; the app enforces it by
  building the Partner's model context without the intent, the hints, or the feedback.
- **P8 The app owns the flow.** The server holds each turn's stage and decides what the
  learner may send next; a model only writes the content of a stage.

The behavior below comes from the prototype skill tried on 2026-10-07 (the owner's vault,
`intent-to-english/SKILL.md` and `references/concept.md`). Its runtime rules are copied into
the repository as the conversation rules document, so the implementer never needs the
vault.

## 2. Scope

### MVP

- **F1 Start and resume a session** — the conversation the core interaction lives in (§3.1)
- **F2 Japanese intent and the build hint** — step 2 of the turn (§3.2)
- **F3 English attempt and gap hints** — step 3 of the turn (§3.3)
- **F4 Structured feedback** — step 4 of the turn (§3.4)
- **F5 Fill-in retry** — step 5 of the turn (§3.5)
- **F6 Partner reply** — step 6 of the turn, under P7 (§3.6)
- **F7 In-session controls** — skip, show the answer, hint, restate, rewrite the intent,
  ask the Coach, end — as explicit controls (§3.7)
- **F8 Pacing, ending, and wrap-up** — the 3-reply check-in and the close (§3.8)
- **F9 Session history** — resume after reload, read an ended session (§3.9)
- **F10 Model roles, provider, and the fixed-response mode** — the two model roles behind
  ports, OpenRouter, and a keyless mode for development and tests (§3.10)
- **F11 Output checks and the evaluation set** — every model output checked by code, and a
  fixed set of cases run against real models (§3.11)
- **F12 Model call log** — tokens, cost, latency, and outcome of every call (§3.12)

### Later

- **OWASP Top 10 for LLM Applications (2025) attack tests** — Prompt Injection and the
  other relevant risks as evaluation cases, with a threat model and the results in the
  README. The first item after the MVP (owner's decision 2026-10-16; the Q4 2026 goal).
- **Amazon Bedrock adapter** — when the account's Bedrock quota allows (daily token quota is
  0; re-application around 2026-11-02).
- **Hosting with sign-in** so the app works from a phone — waits for Bedrock; pulls in
  authentication, protecting a billed endpoint, and abuse limits.
- **Reading the Partner's line aloud** — undecided since the prototype.
- **Review of what the learner could not say** — expressions from feedback turned into later
  questions or spaced review.
- **A Partner who remembers past sessions** — retrieval over saved sessions; a RAG candidate.
- **Adjustable support and lengths** — fewer or more hints from now on, a longer or shorter
  Partner from now on, narrowing the intent by picking which points to keep. The prototype had
  them; the MVP's controls (§3.7) cover the core turn without them.
- **Streaming replies** — the MVP shows a reply only after its checks pass (§3.10).
- **A model grading outputs in the evaluation (LLM-as-judge)** — with its agreement against
  the owner's own judgments measured before it is trusted (§3.11).
- **Turning a saved turn into an evaluation case.**
- **Deleting a session from the screen** — the MVP keeps every session; the owner can delete
  the local database file.

### Non-goals

- **Scores, CEFR levels, level diagnosis, streaks, or "mastered" labels** — they grade the
  learner instead of helping them say what they mean (P6).
- **Own recording, speech recognition, or pronunciation assessment** — input is text: typed,
  or produced by the OS's or the learner's own dictation tool.
- **Topic pickers, scenarios, missions, target expressions, role-play scripts, or a choice of
  Partner personas** — the Partner opens like a friend; the learner is never asked for a
  situation to practice.
- **Notifications, reminders, or practice quotas** — the learner opens the app when they want
  to talk.
- **A model answer before the learner tries** (P2).
- **More than one user, accounts, or sharing** in the MVP.
- **Links to the owner's vault, Daily notes, or Anki.**
- **Live model calls in automated tests or CI** — they bill, flake, and need a key.

## 3. Features

### 3.1 Start and resume a session (F1)

- **New session**: the Coach shows how the turn works (send Japanese first, then try the
  English; partial English is fine; English directly is fine; how to skip, ask for an answer,
  or end). The Partner then opens the way friends start a chat: a greeting and one simple
  question ("Hey! How's it going?", "Hi! How was your weekend?"). It never leads with its own
  news, never asks for a topic, and varies the opener across sessions (it differs from the
  previous session's opener).
- **Resume**: a session in progress reopens at the exact stage it was left — after a reload,
  or from the history list (§3.9).
- **Several in progress**: starting a new session leaves the others resumable.
- **Next action**: every state shows one line saying what to send next and in which language
  (the prototype's `👉 次:` table).

### 3.2 Japanese intent and the build hint (F2)

- **Input**: the learner's Japanese intent. Sending English directly (with or without
  Japanese) skips to §3.4; sending partial English or naming a gap goes to §3.3.
- **Coach reply**: one short line ("いいですね！") and the next action. Never lists, counts,
  or restates the points of the Japanese.
- **Build hint**: most turns get none. At most one line `組み立てのヒント: …`, only when a
  word-for-word translation would be hard or misleading (an omitted subject, an idiom, a very
  Japanese framing): one sentence, one idea, for the single hardest spot, on how to think
  about it (the subject, a plainer meaning, splitting). No English words at all, and no point
  dropped. Long sentences, several actions, or a reason plus a result get none.
- **Limits**: 1–1,000 characters; an empty input cannot be sent.

### 3.3 English attempt and gap hints (F3)

- **Full English** → feedback (§3.4).
- **Partial English, or a named gap** ("〜が分からない") → a hint for exactly that gap: a
  word, a short phrase, or part of a structure. Still stuck → a slightly bigger piece, or a
  plainer way to say the *same* point; never a smaller point.
- **Limits**: 1–1,000 characters.

### 3.4 Structured feedback (F4)

- **Checks, in order of importance**: (1) every core point and nuance of the Japanese is
  there — a missing point is a fix whose original is "(なし)"; details the learner adds are
  their choice unless they contradict the intent; (2) it works as a reply the Partner can
  answer; (3) mistakes — grammar, and words or word order that change the meaning; (4) more
  natural ways to say it.
- **How many**: aim for 3 fixes or fewer, 5 at most, chosen by the order above. More than 5
  only when that many mistakes change the meaning. No fix is invented when the English is
  already fine; no judgment by literal match, vocabulary difficulty, or length.
- **Tags**: **ミス** — wrong grammar, a changed meaning, or a core point missing or wrong;
  only when sure (if a fluent speaker could say the original in this context, it is not a
  ミス). **改善** — the English works; this is another way to practice, and its reason says
  so (「元のままでも通じる。…」). When every fix is 改善, the first line says so too.
- **Recurring cases**: a quick reaction followed by more (*I see.*, *Oh, nice!*) is good,
  never padding. A reaction or tag the learner already used this session (*I see*,
  *right?*) gets a 改善 fix offering another that fits the moment.
- **Layout, in this order**: (1) one line on the intent — 「意図は伝わっています」 when every
  point came through, else only the missing point(s); (2) the fixes, numbered ①… in the order
  they appear in the sentence, never grouped by category, each with 元 (what they wrote, or
  （なし）), 直す (the suggested words), なぜ (one short reason with the tag); (3) their
  sentence, verbatim; (4) directly under it, the fill-in template: correct parts stay, each
  fixed part becomes a numbered blank `(①) ____`, a changed word order is already applied;
  (5) one line asking for the whole sentence with the blanks filled.
- **Several sentences**: a sentence that needs no fix is left out of (3) and (4).
- **Never the completed sentence**: filling ①, ②, ③ in turn yields the complete sentence,
  which is never shown. A missing core point's blank is a sentence the learner builds: 直す
  names what to add in Japanese, plus at most one key word.
- **No fix needed** → one line, and straight to the Partner (§3.6).
- **Transcription slips**: a word that arrives misconverted (*starting* for *studying*) is
  read as meant when the intent and context make it nearly certain, noted in a few words
  (「starting は studying として読みました」). When two readings both fit but barely change the
  feedback, the likelier one is taken and noted. The Coach asks which one only when the
  reading changes the feedback a lot (*leave* or *live*). It never claims a pronunciation or
  a recognition error. A confirmed slip is never a mistake: no fix, no blank.
- **Form**: the feedback is structured data the server validates (§3.11) and the screen
  renders; never free text the screen has to parse.

### 3.5 Fill-in retry (F5)

- **Input**: the whole sentence with the blanks filled.
- **All acceptable** → one confirming line and on to the Partner. A different but correct
  word counts as correct. Never "learned" or "mastered".
- **A blank still off** → the Coach names it and gives a slightly bigger hint (first letter,
  word form); the learner retries that blank. On the second miss the Coach gives that piece
  and the turn moves on: at most two retry submissions per turn.
- **Skip** → one neutral line, and the Partner continues from the learner's latest English.
- **The turn is done** once the core intent comes through and the Partner can reply to it.

### 3.6 Partner reply (F6)

- **Context**: the Partner sees only the English of the conversation — its own lines and the
  learner's latest English of each turn (the retry when there was one). Never the Japanese
  intent, hints, or feedback (P7).
- **Length**: about one sentence of 12 words or fewer; a second short sentence only when the
  first cannot stand alone; never unnatural English to hit a count.
- **One thing to respond to**: each line asks one question, or reacts and adds one follow-up
  on the same thread, or shares a short experience of its own with no question. Never its own
  news plus an unrelated question.
- **Taking turns**: after the learner has answered two Partner questions in a row, the next
  line shares instead of asking. The Partner has a made-up life (job, hobbies, small events)
  that stays consistent within the session. Asked something, it answers with real content (one
  sentence, two at most) and only sometimes turns the question back. After two learner
  questions in a row, it shares or reacts rather than inviting a third.
- **Reacting**: only to what the English says; a natural follow-up when something is
  missing; clarification requests, rephrasing, and topic changes are normal conversation; no
  steering toward a planned reply or target expression.

### 3.7 In-session controls (F7)

The prototype took requests in plain words and had the model tell a reply from a request.
The app offers them as explicit controls instead, so no model ever classifies what the
learner sent: a fixed operation is a control, a hint request names its gap, and a question
to the Coach goes in its own box.

| Control | Available | Does |
|---|---|---|
| Reply in English directly | at the intent stage | sends English without a Japanese intent; feedback checks the English alone (§3.4) |
| Hint (with "what I can't say", 1–200 characters, and optional partial English) | at the English stage | a gap hint (§3.3); asking again for the same gap gives a bigger piece |
| Show the answer | at the English stage and the retry stage | one natural complete example for the current spot only; the learner then types it once while looking (skippable); from the next turn, answers are not shown first again |
| Skip | at the retry stage, and at "type the shown answer once" | ends the retry with one neutral line; the Partner continues from the latest English |
| Practice again | on the current turn's feedback once the turn is done, until the learner's next reply | reopens the same fill-in template for one more practice submission, checked like a retry; changes nothing in the conversation |
| Restate the Partner's line (shorter / simpler) | while the latest Partner line awaits a reply | the Partner says the same line shorter or simpler; the learner's stage is unchanged |
| Rewrite my Japanese | after the intent is sent, until the turn is done | the new intent replaces the old as the yardstick; hints, fixes, and blanks tied to the old one are dropped; the learner is asked for English for the new one |
| Ask the Coach (free text, 1–500 characters) | at any stage of a session in progress | answered by the Coach in Japanese; does not advance the turn; the stage's next action is repeated; the Partner never sees it |
| End | at any stage of a session in progress | ends at once (§3.8) |

The app tells a Japanese intent from an English reply by the control the learner used,
never by guessing the language of the text.

Rules every control keeps: a control adjusts the current stage and never resets the
conversation.

### 3.8 Pacing, ending, and wrap-up (F8)

- **Check-in**: finished replies are counted (feedback and retry done, or skipped; questions
  to the Coach do not count). After the 3rd, 6th, 9th…, before the Partner's next line, the
  Coach asks 「ここで3往復です。続けますか？」 with two answers, 続ける and 終わり. 続ける → the
  Partner continues from the learner's latest English.
- **End any time**, even mid-retry: at once, with no pending retry or last question.
- **Wrap-up**: two or three expressions or noticings from this session, presented as things
  that came up, never as mastered. No scores, no reflection prompts, no next action.
- **After the end**: the session is read-only.

### 3.9 Session history (F9)

- **List**: newest first, 20 per page (cursor paging). Each row: start time (local), status
  (in progress / ended), finished replies, and the Partner's opener (truncated to 60
  characters).
- **Open**: in progress → resume (§3.1); ended → the read-only transcript: every Partner line,
  the learner's Japanese and English, and every Coach output in order, then a closing section
  with the learner's finished English lines alone, so the conversation reads straight through.
- **Empty**: no sessions yet → the list invites the first session.
- **Retention**: kept until the owner deletes the local database file.

### 3.10 Model roles, provider, and the fixed-response mode (F10)

- **Two roles**, each with its own configured model: the **Partner** (the opener and every
  Partner line, restatements included) and the **Coach** (build hints, gap hints, feedback,
  retry checks, shown answers, answers to questions, the wrap-up). Defaults on OpenRouter:
  Coach `anthropic/claude-sonnet-5.5`, Partner `anthropic/claude-haiku-5.5` — the prototype
  was tuned on Sonnet, and feedback quality is what the Coach is for. OpenRouter's catalogue,
  checked 2026-10-17: Sonnet 5.5 $2 / $10 and Haiku 5.5 $0.10 / $0.50 per million input /
  output tokens. At about 12k input and 1.1k output tokens per turn, a turn costs about
  $0.03 (about $5 a month at six turns a day). Whether the Coach can move to Haiku is
  decided by the evaluation set (§3.11).
- **Waiting**: no streaming. A reply is shown only after its checks pass (§3.11), so P2 holds
  by construction; while a call runs, the screen shows a waiting state. Latency is measured
  (§3.12) and reported by the evaluation run.
- **Provider**: OpenRouter, with the owner's API key from the environment. Bedrock later: a new
  adapter and a setting, with no change to the core, the API, or the screen.
- **Fixed-response mode**: with no key, the app runs on scripted Partner lines and Coach
  outputs, so the screen, the API, every stage, and the browser test work without a key or
  cost. The screen shows that it is on. Its outputs are never used to judge quality.
- **Failure**: a timeout (60 s per call), rate limiting, a provider error, or an output that
  still fails its checks after one automatic repair attempt (§3.11) keeps the learner's input,
  shows what failed with a retry action, and does not advance the stage.

### 3.11 Output checks and the evaluation set (F11)

- **On every model output**, checked by code before anything is stored or shown: it matches
  its schema; fixes and blanks correspond one to one, numbered in sentence order; filling the
  blanks with the fixes leaves no blank; the completed sentence does not appear in the output;
  a build hint contains no English words; a Partner line is English, at most two sentences,
  and asks at most one question — and none when the taking-turns rule says share. A failure
  gets one repair attempt with the reasons, then the failure state (§3.10).
- **Evaluation set**: 10–20 fixed cases seeded from the 2026-10-07 prototype session and the
  prototype's examples, plus edge cases — English already fine; a missing intent point; a
  clear transcription slip (*starting*/*studying*); an ambiguous one (*leave*/*live*); a
  multi-sentence reply with one correct sentence; a repeated set phrase; two Partner questions
  answered in a row; the learner asking the Partner something; content only in the Japanese
  (the Partner must not mention it). Each case states what must and must not happen
  ("flags *refreshing* as ミス", "marks nothing as ミス", "the Partner line does not mention
  Sapporo"), and code decides pass or fail. No model grades another model's output in the
  MVP, so a run is repeatable and costs only the calls under test; phrasing quality is not
  judged.
- **Running it**: one command runs the set against the configured models and writes a report
  — pass rate per check, cost, latency, model ids, date. The owner runs it (it bills); CI runs
  the harness against the fixed-response mode only. The same set runs with any model per role,
  so models can be compared on quality, cost, and latency.

### 3.12 Model call log (F12)

- **Every call** is recorded: the session and turn it served, role, provider, model id, input
  and output tokens, cost when the provider reports it, latency, and outcome (ok, repaired,
  invalid output, timeout, rate limited, provider error). Never the API key.
- **Shown**: not on the practice screens; the evaluation report and a command summarize it.

## 4. Cross-cutting rules

- **Roles stay visibly apart** on every screen: the Partner (English), the Coach (Japanese,
  English only for the phrases taught), and the next action.
- **Stale or repeated submissions**: each submission names the stage it answers; one that no
  longer matches (a second tab, a double click) is rejected and the screen reloads the
  session's state. A submission is processed at most once.
- **Privacy**: everything stays in the local SQLite file, except the text sent to OpenRouter
  (and the model provider behind it) for each call. The README says so, and says that the
  owner's OpenRouter privacy settings decide whether a provider may log or train on it.
- **Interrupted calls**: a model call cut off by a server stop or a closed tab leaves the
  stage as it was before the call; the learner's input is kept and can be sent again.
- **Cost**: the owner caps spend in their OpenRouter account; the app sets no budget of its
  own in the MVP.
- **Time**: stored in UTC, shown in local time.

## 5. Data

- **Session** — id (UUIDv7), started and ended times, status (in progress / ended), finished
  reply count, the opener, the wrap-up (2–3 items).
- **Turn and its events** — per turn: index, Partner line (and whether it asked a question),
  the Japanese intent (optional), each English attempt, hints, the structured feedback, retry
  submissions and their results, how the turn ended (accepted, skipped, answer shown, ended),
  and the final English. Coach questions and answers, check-ins, and notices belong to the
  session's timeline in order. The exact storage shape is an architecture decision.
- **Model call** — §3.12.
- **Evaluation cases and reports** — files in the repository, not the database.
- **Retention** — indefinite, in the local file.

## 6. Open questions

None. The model library behind the ports and where evaluation reports live are decided in
`docs/architecture/overview.md` § Decisions.

## 7. Decision log

- 2026-10-17 Working title Intent to English, slug intent-to-english.
- 2026-10-17 Models through OpenRouter now, Amazon Bedrock later behind the same ports
  (rejected: Bedrock now, because the account's daily token quota is 0; Claude Code invoked
  from the app, because it is not an in-app inference path).
- 2026-10-17 MVP is the owner only, local on their Mac, no sign-in or hosting (rejected:
  online for the owner, because sign-in, a protected billed endpoint, and hosting would enter
  the MVP; a public demo, because accounts, limits, abuse handling, and cost caps would).
- 2026-10-17 Sessions are saved, resumable, and readable afterwards; no scores, progress, or
  review (rejected: saving only to resume, because ended sessions are evaluation material and
  the prototype's session log; no saving, because nothing would be left to evaluate).
- 2026-10-17 MVP has code checks on every output and a 10–20 case evaluation set; the OWASP
  LLM attack tests come right after (rejected: attack tests in the MVP, because the first
  working turn would move further out; checks only, because the quality evidence the Q4 goal
  asks for would wait).
- 2026-10-17 Controls are explicit — buttons, a hint request naming its gap, and a separate
  box for questions to the Coach (rejected: one free-text box with a model classifying each
  message, because misclassification, extra calls, and harder tests; buttons only, because
  the learner could not ask why a fix was made).
- 2026-10-17 Default models: Coach Claude Sonnet 5.5, Partner Claude Haiku 5.5, both via
  OpenRouter and configurable per role (rejected: Haiku for both, because the prototype was
  tuned on Sonnet and the evaluation set should show Haiku is enough before it coaches;
  Sonnet for both, because the Partner's short lines do not need it and it is slower).
- 2026-10-17 No streaming: a reply appears after its checks pass, with a waiting state
  (rejected: streaming the Partner only, because a line that fails its checks would have to be
  taken back; streaming everything, because feedback would show before it is checked).
- 2026-10-17 The evaluation set's pass/fail is decided by code from per-case expectations
  (rejected: adding a model as judge, because its own agreement must be measured first; the
  owner reading a report each run, because it costs their time every run).
