# The design lock

Binding for every screen. `docs/design/design-direction.md` is the research record and the
source of every value named here; `docs/design/ux-guidelines.md` holds the app-wide behavior
(states, forms, motion timing, accessibility targets). A change to a rule below changes this
page in the same pull request.

- **Direction:** friendly-professional learning UI after Brilliant — white canvas, role tints,
  bold type, tactile controls. Never cool monochrome, never an engineer's tool, never childish.
- **Preserve:** the white canvas (no cream or gray page); role-tinted surfaces with a 1 px
  border in the same hue; bold near-black headings and labels; tactile buttons with a 3 px
  bottom edge that collapses when pressed; a 12 px radius on bubbles, panels, buttons, and
  inputs.
- **Role colors:** lime is the Partner only (bubble, avatar, label); pale yellow is the
  Coach's feedback card and the marker on the parts to rebuild only; green is success only;
  the ミス and 改善 tags keep their own hues and appear nowhere else; ink is primary actions
  and text; blue is the focus ring and links only.
- **Reject:** gamification (streaks, XP, confetti), big pastel color blocks, indigo or violet,
  drop shadows as separators, cards around every block (only the feedback card and the
  bubbles are containers), serif type, illustrations or mascots beyond the Partner's SVG
  avatar, an icon package (a handful of inline SVGs at 20 px, 1.75 px stroke).
- **Type:** system fonts only — `--font-sans` for Japanese, `--font-en` (`ui-rounded` first)
  on every `lang="en"` element; the scale 12 · 13 · 15 · 16 · 17 · 20 · 24 px, body in `rem`.
- **Shape:** Tailwind's 4 px spacing scale; 1 px borders; no elevation except the composer's
  hairline; radius 12 px, 999 px for tags and the badge, 8 px for template slots.
- **Motion:** 150 ms fade with a 4 px rise for a new line or block, 200 ms expand and
  collapse, 100 ms between tabs, 100 ms button press, 600 ms success edge; `transform` and
  `opacity` only; reduced motion drops the rise and makes expand, collapse, and scrolling
  instant. The values are Tailwind duration utilities, not tokens.
- **Tokens:** design-direction's "Tokens (Tailwind CSS 4)" block, in `frontend/src/styles.css`
  after `@import "tailwindcss";`, with `color-scheme: light dark` and `light-dark()` pairs;
  markup uses the semantic utilities only, never a raw palette color.
  Opacity modifiers on these tokens are allowed with tailwindcss 4.3.3 (checked
  2026-10-18). The production build rewrites the ink token as
  `--color-ink:var(--lightningcss-light,#1c1f24)var(--lightningcss-dark,#eceef1)`;
  the root's fallback variables swap their initial/empty values in
  `@media (prefers-color-scheme:dark)`. The `bg-ink/50` probe emits
  `background-color:var(--lightningcss-light,#1c1f2480)var(--lightningcss-dark,#eceef180)`
  and, inside its color-mix support query,
  `background-color:color-mix(in oklab, var(--color-ink) 50%, transparent)`.
  Both forms follow the OS scheme; the probe is absent from the source.
- **Contrast:** the 53 light and dark pairs in `docs/design/contrast-pairs.json` passed WCAG
  2.2 AA when measured on 2026-10-28 with design-direction's "Measured contrast" command; a
  token change re-runs it in the same pull request. No test measures contrast:
  `frontend/tests/styles.test.ts` pins the token names and values only.

## What the suite proves

- Waiting states follow ux-guidelines (300 ms, 10 s, 60 s): component tests with fake timers.
- Accessibility targets hold (WCAG 2.2 AA + 2.4.13): component tests for focus after a stage
  change and the live regions; ux-guidelines' manual verification list.
