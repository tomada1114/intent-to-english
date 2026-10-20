# Accessibility checklist for a screen

Read before a screen ships, and when reviewing one. Each item is a rule first; the
example after it comes from the app's screens under `frontend/src/features/sessions/`
and `frontend/src/features/conversation/`. A component test checks each
item through Testing Library's role and name queries (`writing-tests`), with the states
[testing-screens.md](testing-screens.md) lists.

## Labels and names

- **Every input has a visible label** tied to it with `htmlFor` and an id from
  `useId()`. A placeholder is not a label. The hint request's `分からないところ` label
  points at its text input.
- **Every button has an accessible name.** The visible text is enough when it is unique
  on the screen; a button repeated per row gets an `aria-label` naming its item. The
  home screen's `新しい会話を始める` is named by its text; no screen repeats one per row yet.
- **A form, list, or section has a name** when the screen has more than one: the hint
  request form has `aria-label="ヒントのお願い"`, and the session list and its section
  are `aria-labelledby` the `これまでの会話` heading.

## Focus

- **Focus moves to a defined element after an item is removed**, never to the document
  body. Pick an element that still exists after the removal and give it
  `tabIndex={-1}` when it is not focusable by itself. When the end confirmation's
  `終える` and `戻る` go away, `EndSession` focuses its `会話を終える` button again.
- **Focus returns to the input after a successful submit** that clears it, so the next
  entry can be typed at once. The conversation screen refocuses its composer after a result.
- **Every interactive element shows a visible focus style** (`focus-visible:` utilities).

## Announcements

- **An error is announced:** it renders with `role="alert"`. `Banner` does this,
  and so does a field message next to its input. The input gets `aria-invalid` and
  `aria-describedby` pointing at the message.
- **A status message is announced:** a `role="status"` region (with `aria-atomic`) stays
  mounted for the screen's whole life, and only its content changes. To announce the
  same text twice, replace its child (a new React `key`) rather than leaving it in
  place, and clear the region when the user starts a new action. The conversation
  screen's `お知らせ` region shows each arrival's Partner and coach lines, re-keyed by
  `arrival.key` for each one.
- **A notice is announced only once it is true:** the conversation screen announces an
  entry only once it is in the session view it received, never the entries already
  there when the screen opened.

## Keyboard and pending state

- **Every action works from the keyboard:** use a `<button>` for an action and a
  `<form>` with a submit button for input, never a clickable `<div>` or `<span>`. Enter
  submits the hint request form.
- **A control whose request is in flight is disabled**, and its label says so where it
  helps. A row whose actions change the same item disables all of them while either
  request is pending, as `EndSession` does with `終える` and `戻る`.
- **A double submit sends one request:** guard with a ref as well as the pending flag,
  because a second submit can arrive before React renders the disabled state. The
  conversation screen's `inFlight` ref does this.
