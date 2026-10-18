# Intent to English — Design direction

The visual direction: references, the reference lock, role rules, and token values for light
and dark. Screens and states are `docs/product/ux-flows.md`'s; app-wide behavior (timing,
motion amounts, accessibility targets) is `docs/design/ux-guidelines.md`'s. The tokens land
as a Tailwind CSS 4 `@theme` block in `frontend/src/styles.css` (the template's only styling
layer); nothing here is applied to code until that issue ships.

## Brief

Designing a two-pane English conversation practice app (Partner on the left, Coach on the
right) for one Japanese adult learner on desktop web. Goal: say the whole intent in their own
English, then rebuild it from the fixes. Tone, in the owner's words: professional, yet
friendly and easy to touch — a little lively, never childish, never cool monochrome, never
an engineer's work tool. Constraints: Tailwind CSS 4 tokens only, system fonts (no font
package), light and dark following the OS, WCAG 2.2 AA + 2.4.13.

## Research

Refero's style search returned no results on 2026-10-17 (every query, including the
documented examples), so the direction is grounded in Refero screens of real products and
the bundled craft references.

- First round, rejected by the owner: a proofreading direction (Grammarly's suggestion
  panel), a reading-desk direction (Matter's reader and notebook), and a review-tool
  direction (Factory's two-pane review, GitHub's diff) — "a reading desk is not it; cool
  black-and-white is not it; engineer-like or work-like is not it".
- Second round: Brilliant (home, onboarding bubble), Promova (pastel course cards), Busuu
  (lesson screen). The owner chose the Brilliant-led direction.

| Reference | Screen | Taken |
|---|---|---|
| Brilliant — home | https://refero.design/pages/cf3d5290-97eb-4584-b4c5-3fbba946e16d | white canvas; panels tinted by role with a thin same-hue border; bold near-black type; small bold labels above blocks |
| Brilliant — onboarding | https://refero.design/pages/22b0cf75-d0ae-42ec-a8c5-7a77e1d9f449 | the mascot speaking from a pale lime bubble with a lime edge; option rows as bordered, rounded, tappable rows |
| Busuu — lesson | https://refero.design/pages/67459f9f-d5dd-4dfd-bdc5-16c8d84c5cc6 | success green kept to progress and success only |

## Reference lock

- **Primary direction:** Brilliant's friendly-professional learning UI — white canvas, role
  tints, bold type, tactile controls.
- **Preserve:** (1) the white canvas — no cream, no gray page; (2) role-tinted surfaces with a
  1 px border in the same hue — pale lime for the Partner, pale yellow for the Coach's
  feedback; (3) bold near-black headings and labels; (4) tactile buttons: a 3 px bottom edge
  that collapses when pressed; (5) 12 px radius on bubbles, panels, and buttons.
- **Borrow only:** Busuu's discipline that green means progress or success and nothing else.
- **Role rules:** lime = the Partner (bubble, avatar, its label) only; yellow = the Coach's
  feedback card and the marker on parts to rebuild only; green = success only (a retry
  accepted, a turn done); the ミス and 改善 tags keep their own two hues and are never used
  elsewhere; ink (near-black) = primary actions and text; blue = focus ring and links only.
- **Media strategy:** code-native only. The Partner's avatar is an inline SVG — a 28 px
  rounded square in lime with two dot eyes and a small smile; no illustrations, photos, or
  mascots elsewhere. Icons are a handful of inline SVGs (send, lightbulb, chevron, close,
  alert) drawn at 20 px with a 1.75 px stroke; no icon package.
- **Reject:** gamification (streaks, XP, leagues, confetti); big pastel color blocks; gray or
  cream page backgrounds; indigo or violet anywhere; drop shadows as the main separator;
  cards around every block (only the feedback card and the bubbles are containers);
  serif type.
- **Memorable detail:** the conversation reads like a friendly chat — the Partner speaks
  from a lime bubble beside its little avatar, the learner's English sits in a white bubble
  on the right — while the Coach's pale yellow feedback card turns each fix into a numbered
  slot `①` in the template, the parts to rebuild marked in yellow in 「あなたの文」.

## Decision ledger

| Decision | Source | Source rule / role | Why |
|---|---|---|---|
| White canvas, role tints with same-hue borders | Brilliant home and onboarding | tint marks a role, never decoration | friendly without pastel blocks; the two voices are told apart at a glance |
| Lime Partner bubble + SVG avatar | Brilliant onboarding (mascot bubble) | lime is the speaker's color | makes the left pane a conversation with someone, not a log |
| Pale yellow feedback card, yellow marker on fixed spans | owner's chosen preview; prototype's 直し方 → あなたの文 → 穴埋め order | yellow = "rebuild here", not "wrong" | P5: natural English is not a mistake; a marker reads as "work on this", red ink would read as grading |
| Tactile ink buttons with a 3 px bottom edge | Brilliant / owner: 「触れやすさ」 | primary actions only | the next action looks pressable; ink keeps it professional |
| Green only for success | Busuu lesson | progress and success only | a green CTA would blur "go" with "correct" |
| System fonts: Hiragino Sans for Japanese, `ui-rounded` → system UI for English | template constraint (no font package); craft: typography | English set slightly larger | Safari shows SF Pro Rounded for the English lines (friendlier); other browsers fall back to the system sans |
| Light and dark follow the OS | owner, 2026-10-17 | `color-scheme: light dark`, `light-dark()` | night practice without glare |

## Typography

| Role | Family (CSS) | Size / line height | Weight |
|---|---|---|---|
| Japanese UI and Coach text | `"Hiragino Sans", "Hiragino Kaku Gothic ProN", "Noto Sans JP", "Yu Gothic UI", Meiryo, system-ui, sans-serif` (`--font-sans`) | 15 px / 1.7 | 400; labels 700 |
| English in the conversation, fixes, and templates | `ui-rounded, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif` (`--font-en`), set on every `lang="en"` element | 17 px / 1.55 in bubbles; 16 px / 1.6 in the Coach pane | 400; 直す words 700 |
| Page title (S1) | `--font-sans` | 24 px / 1.35 | 700 |
| Pane titles 「会話」「コーチ · ターン N」 | `--font-sans` | 13 px / 1.4, letter-spacing 0.04em | 700, ink-muted |
| Labels (Partner, 直し方, あなたの文, 穴埋め) | `--font-sans` | 12 px / 1.4 | 700 |
| Counts, times | `--font-sans` with `font-variant-numeric: tabular-nums` | 13 px | 400 |

- Scale: 12 · 13 · 15 · 16 · 17 · 20 · 24 px. Body text is `rem`-based (1 rem = 16 px) so
  200% text scaling holds.
- Japanese line length: the Coach pane's text column caps at 40 em; English bubbles cap at
  36 em.
- `text-wrap: pretty` on Coach paragraphs; never on English being corrected (it must break
  exactly as the learner wrote it).

## Spacing, radius, borders, elevation

- Spacing: Tailwind's 4 px scale. Pane padding 20 px (≥1024px) / 16 px (<1024px); 12 px
  between blocks in a pane; 8 px between a label and its content; 24 px between turns.
- Radius: 12 px — bubbles, panels, the feedback card, buttons, inputs; 999 px — tags and the
  fixed-response badge; 8 px — the template's numbered slots.
- Borders: 1 px everywhere a surface meets another (`--color-line`); tinted surfaces use their
  own edge color. Tactile buttons add a 3 px bottom edge (`--color-ink-edge` for primary,
  `--color-line-strong` for secondary).
- Elevation: none by default. Only the composer area at the bottom of the Coach pane casts
  `0 -1px 0 var(--color-line)` (a hairline, not a shadow). Shadows never separate content.
- Pressed state (motion per ux-guidelines § Motion): the button moves 2 px down and its bottom
  edge shrinks to 1 px, 100 ms; reduced motion → color change only.

## Components

- **Partner bubble** — `bg-partner` fill, 1 px `border-partner-edge`, 12 px radius with the
  top-left corner 4 px (the tail side), padding 12 × 16 px, English text 17 px. The avatar
  sits to its left; the label 「Partner」 above it in `text-partner-ink`.
- **Learner bubble (left pane)** — canvas fill, 1 px `border-line`, aligned right, top-right
  corner 4 px; English text 17 px.
- **Coach blocks (right pane)** — plain rows on the pane's `bg-surface`: a label line and the
  text, no container. The learner's Japanese and English entries are rows with a
  `border-l-2 border-line-strong` rule.
- **Feedback card** — `bg-coach` fill, 1 px `border-coach-edge`, 12 px radius, padding 16 px.
  Sections 「直し方」「あなたの文」「穴埋め」 with 12 px labels. Each fix: `①` in a 20 px
  ink circle with on-ink text, 元 in ink-muted, 「→」, 直す in 700 weight, the tag, and the
  なぜ line below in ink-muted.
- **Tags** — 999 px pills, 12 px 700 text, 2 × 8 px padding: 「ミス」 `text-miss` on
  `bg-miss-tint`; 「改善」 `text-improve` on `bg-improve-tint`. Text, not color, carries the
  meaning.
- **Marker** — in 「あなたの文」, each fixed span gets `bg-marker` with 2 px horizontal
  padding and 4 px radius, followed by its small circled number (`refreshing①`); the text
  stays ink. The number, not the yellow, ties the span to its fix, so color is never the
  only carrier.
- **Template slot** — `(①) ____` renders as the circled number followed by a 4 em gap with a
  2 px `border-b-ink` underline; 8 px radius on the number chip.
- **Buttons** — primary: `bg-ink text-on-ink`, 3 px bottom edge `border-b-ink-edge`, height
  44 px, padding 0 20 px, 15 px 700. Secondary: canvas fill, 1 px `border-line-strong` with a
  3 px bottom edge, ink text. Quiet (「言い換え」「▸ コーチに質問」): text only, ink-muted,
  underline on hover.
- **Composer** — canvas fill, 1 px `border-field-edge` (≥3:1, WCAG 1.4.11), 12 px radius, 15 px Japanese / 16 px
  English placeholder text in `text-ink-subtle`; focus shows the focus ring, not a border
  change.
- **Banners** — error: `bg-danger-tint`, 1 px `border-danger-edge`, `text-danger`, alert icon
  + text; waiting and cancelled lines: `text-ink-muted`, no container.
- **Fixed-response badge** — 999 px pill, `bg-badge text-badge-ink`, 12 px 700.
- **Success line** — 「言い直しできました」 in `text-success` with a check icon; a retry
  accepted flashes the template card's edge to `border-success` for 600 ms (reduced motion:
  none).
- **Focus ring** — 2 px solid `outline-focus`, 2 px offset, on `:focus-visible` only.

## Tokens (Tailwind CSS 4)

`frontend/src/styles.css`, after `@import "tailwindcss";`. Every color pairs a light and a
dark value through `light-dark()`; `color-scheme: light dark` on `:root` makes the OS setting
choose. Names are semantic (utilities `bg-canvas`, `text-ink-muted`, `border-partner-edge`,
`outline-focus`); no raw palette color is used in markup.

```css
:root {
  color-scheme: light dark;
}

@theme {
  --font-sans: "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Noto Sans JP", "Yu Gothic UI", Meiryo, system-ui, sans-serif;
  --font-en: ui-rounded, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;

  --color-canvas: light-dark(#ffffff, #15171b);
  --color-surface: light-dark(#f6f7f9, #1b1e23);
  --color-line: light-dark(#e2e5ea, #2c3038);
  --color-line-strong: light-dark(#c9ced6, #444a55);
  --color-field-edge: light-dark(#8a919c, #6b7380);

  --color-ink: light-dark(#1c1f24, #eceef1);
  --color-ink-muted: light-dark(#5a606b, #a7adb8);
  --color-ink-subtle: light-dark(#6b7280, #8c93a0);
  --color-on-ink: light-dark(#ffffff, #15171b);
  --color-ink-edge: light-dark(#000000, #9aa1ad);

  --color-partner: light-dark(#f2f9e4, #1d2915);
  --color-partner-edge: light-dark(#bfe08a, #4a6b26);
  --color-partner-ink: light-dark(#3d6e12, #b5dc7a);

  --color-coach: light-dark(#fff9e6, #2a2415);
  --color-coach-edge: light-dark(#f0d68a, #6b5820);
  --color-marker: light-dark(#ffe680, #5c4a0f);

  --color-miss: light-dark(#b93815, #ff9b85);
  --color-miss-tint: light-dark(#ffede5, #3a1d16);
  --color-improve: light-dark(#1f5fbf, #8db4ff);
  --color-improve-tint: light-dark(#e8f0fd, #18243a);

  --color-success: light-dark(#1e7f3b, #6fd08c);
  --color-success-tint: light-dark(#e7f6ec, #15291c);

  --color-danger: light-dark(#b42318, #ff9b85);
  --color-danger-tint: light-dark(#fdecea, #2e1a16);
  --color-danger-edge: light-dark(#f5c2bc, #6b2e24);

  --color-badge: light-dark(#fff4cc, #2e2610);
  --color-badge-ink: light-dark(#6b4f00, #f0cd6e);

  --color-focus: light-dark(#2563eb, #6e9bff);

  --radius-panel: 12px;
  --radius-slot: 8px;
}
```

Open: whether Tailwind 4's opacity modifiers (`bg-ink/50`) resolve through `light-dark()` in
the pinned version — the implementing issue checks it once; until then no markup uses an
opacity modifier on these tokens.

## Measured contrast

Pairs: `docs/design/contrast-pairs.json` (49 pairs, light and dark). Re-run after any token
change: `python3 <ui-ux-designing>/scripts/check_contrast.py docs/design/contrast-pairs.json`.
Measured 2026-10-17, WCAG 2.2 AA, exit 0. Bubble, card, and tint edges are decorative
boundaries (their content is the text) and are not in the table; input boundaries are
(`field-edge`).

```
name                                      fg       bg       kind  ratio  required  result
----------------------------------------  -------  -------  ----  -----  --------  ------
light/ink on canvas                       #1c1f24  #ffffff  text  16.52  4.50      PASS
light/ink on surface                      #1c1f24  #f6f7f9  text  15.42  4.50      PASS
light/ink on partner                      #1c1f24  #f2f9e4  text  15.30  4.50      PASS
light/ink on coach                        #1c1f24  #fff9e6  text  15.69  4.50      PASS
light/ink on marker                       #1c1f24  #ffe680  text  13.28  4.50      PASS
light/ink-muted on canvas                 #5a606b  #ffffff  text  6.32   4.50      PASS
light/ink-muted on surface                #5a606b  #f6f7f9  text  5.90   4.50      PASS
light/ink-muted on coach                  #5a606b  #fff9e6  text  6.01   4.50      PASS
light/ink-subtle (placeholder) on canvas  #6b7280  #ffffff  text  4.83   4.50      PASS
light/on-ink on ink (primary button)      #ffffff  #1c1f24  text  16.52  4.50      PASS
light/on-ink on ink (slot number chip)    #ffffff  #1c1f24  text  16.52  4.50      PASS
light/partner-ink on canvas (label)       #3d6e12  #ffffff  text  6.11   4.50      PASS
light/partner-ink on partner              #3d6e12  #f2f9e4  text  5.66   4.50      PASS
light/miss on miss-tint                   #b93815  #ffede5  text  5.08   4.50      PASS
light/improve on improve-tint             #1f5fbf  #e8f0fd  text  5.31   4.50      PASS
light/success on surface                  #1e7f3b  #f6f7f9  text  4.72   4.50      PASS
light/success on coach                    #1e7f3b  #fff9e6  text  4.80   4.50      PASS
light/danger on danger-tint               #b42318  #fdecea  text  5.75   4.50      PASS
light/badge-ink on badge                  #6b4f00  #fff4cc  text  6.95   4.50      PASS
light/focus on canvas                     #2563eb  #ffffff  ui    5.17   3.00      PASS
light/focus on surface                    #2563eb  #f6f7f9  ui    4.82   3.00      PASS
light/focus on coach                      #2563eb  #fff9e6  ui    4.91   3.00      PASS
light/focus on partner                    #2563eb  #f2f9e4  ui    4.79   3.00      PASS
light/field-edge on canvas                #8a919c  #ffffff  ui    3.18   3.00      PASS
light/success border on coach             #1e7f3b  #fff9e6  ui    4.80   3.00      PASS
dark/ink on canvas                        #eceef1  #15171b  text  15.44  4.50      PASS
dark/ink on surface                       #eceef1  #1b1e23  text  14.38  4.50      PASS
dark/ink on partner                       #eceef1  #1d2915  text  13.09  4.50      PASS
dark/ink on coach                         #eceef1  #2a2415  text  13.27  4.50      PASS
dark/ink on marker                        #eceef1  #5c4a0f  text  7.40   4.50      PASS
dark/ink-muted on canvas                  #a7adb8  #15171b  text  7.96   4.50      PASS
dark/ink-muted on surface                 #a7adb8  #1b1e23  text  7.41   4.50      PASS
dark/ink-muted on coach                   #a7adb8  #2a2415  text  6.84   4.50      PASS
dark/ink-subtle (placeholder) on canvas   #8c93a0  #15171b  text  5.81   4.50      PASS
dark/on-ink on ink (primary button)       #15171b  #eceef1  text  15.44  4.50      PASS
dark/partner-ink on canvas (label)        #b5dc7a  #15171b  text  11.52  4.50      PASS
dark/partner-ink on partner               #b5dc7a  #1d2915  text  9.77   4.50      PASS
dark/miss on miss-tint                    #ff9b85  #3a1d16  text  7.52   4.50      PASS
dark/improve on improve-tint              #8db4ff  #18243a  text  7.47   4.50      PASS
dark/success on surface                   #6fd08c  #1b1e23  text  8.82   4.50      PASS
dark/success on coach                     #6fd08c  #2a2415  text  8.14   4.50      PASS
dark/danger on danger-tint                #ff9b85  #2e1a16  text  8.06   4.50      PASS
dark/badge-ink on badge                   #f0cd6e  #2e2610  text  9.75   4.50      PASS
dark/focus on canvas                      #6e9bff  #15171b  ui    6.66   3.00      PASS
dark/focus on surface                     #6e9bff  #1b1e23  ui    6.20   3.00      PASS
dark/focus on coach                       #6e9bff  #2a2415  ui    5.73   3.00      PASS
dark/focus on partner                     #6e9bff  #1d2915  ui    5.65   3.00      PASS
dark/field-edge on canvas                 #6b7380  #15171b  ui    3.75   3.00      PASS
dark/success border on coach              #6fd08c  #2a2415  ui    8.14   3.00      PASS
```
