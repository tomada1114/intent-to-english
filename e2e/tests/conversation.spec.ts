import { spawnSync } from "node:child_process";
import { expect, type Page, test } from "@playwright/test";
import {
  e2eRun,
  isolatedEnvironment,
  REPOSITORY_ROOT,
  settingsEnvironment,
} from "../environment.ts";

// The first of the fixed Partner's openers (backend adapters/models/fixed.py),
// which a session gets when no earlier session has an opener: a fresh database.
const OPENER = "Hey! How's it going?";
const TAGLINE = "英語で話す前に、日本語で言いたいことを決める練習";
const EMPTY = "まだ会話はありません。最初の会話を始めましょう。";
const NEXT_AT_INTENT =
  "👉 次: 返したいことを日本語で送ってください（英語で返してもOK）";

/** Count the `open` actions the screen posts, across reloads. */
function countOpens(page: Page) {
  const opens: string[] = [];
  page.on("request", (request) => {
    const { pathname } = new URL(request.url());
    if (request.method() !== "POST" || !pathname.endsWith("/actions")) return;
    const body: unknown = request.postDataJSON();
    if (typeof body === "object" && body !== null && "action" in body) {
      if (body.action === "open") opens.push(pathname);
    }
  });
  return opens;
}

/** S2 at `intent`: the how-to, the fixed opener once, and the next step. */
async function expectAtIntent(page: Page) {
  const conversation = page.getByRole("region", { name: "会話" });
  await expect(conversation.getByText(OPENER, { exact: true })).toHaveCount(1);
  await expect(page.getByRole("button", { name: /進め方/ })).toBeVisible();
  await expect(page.getByText(NEXT_AT_INTENT, { exact: true })).toBeVisible();
}

/**
 * Ask a process of its own whether the session is in the database at intent
 * with the opener. A reload alone cannot tell a database from an API that keeps
 * sessions in memory.
 */
function expectStoredAtIntent(id: string) {
  const { databaseUrl } = e2eRun();
  const result = spawnSync(
    "uv",
    ["run", "--locked", "python", "e2e/verify_persistence.py", databaseUrl, id, OPENER],
    {
      cwd: REPOSITORY_ROOT,
      env: isolatedEnvironment(settingsEnvironment(databaseUrl)),
      encoding: "utf8",
    },
  );
  expect(result.error, "could not start the persistence check").toBeUndefined();
  expect(result.status, `${result.stdout}${result.stderr}`).toBe(0);
  console.log(result.stdout.trim());
}

test("a session starts on the home screen, opens at intent, and is listed there", async ({
  page,
}) => {
  const opens = countOpens(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: TAGLINE })).toBeVisible();
  await expect(page.getByText(EMPTY, { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "固定応答モード" })).toBeVisible();
  const start = page.getByRole("button", { name: "新しい会話を始める" });
  await expect(start).toBeFocused();

  const created = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/sessions",
  );
  await start.click();
  const response = await created;
  expect(response.status()).toBe(201);
  const body: unknown = await response.json();
  expect(body).toMatchObject({ id: expect.any(String), stage: "opening" });
  const { id } = body as { id: string };

  await expect(page).toHaveURL(`/sessions/${id}`);
  await expectAtIntent(page);

  await page.reload();
  await expectAtIntent(page);
  expect(opens).toEqual([`/api/sessions/${id}/actions`]);

  expectStoredAtIntent(id);

  await page.getByRole("link", { name: /会話一覧/ }).click();
  await expect(page).toHaveURL("/");
  const row = page
    .getByRole("list", { name: "これまでの会話" })
    .getByRole("link", { name: /進行中 0往復 Hey! How's it going\?$/ });
  await expect(row).toHaveAttribute("href", `/sessions/${id}`);
  const resume = page.getByRole("region", { name: "続きから" });
  await expect(resume.getByText(OPENER, { exact: true })).toBeVisible();
  await expect(page.getByText(EMPTY, { exact: true })).toHaveCount(0);
});

// The fixed responses this file's turns see, copied from the docstring of
// backend adapters/models/fixed.py.
const OPENERS = [
  "Hey! How's it going?",
  "Hi! How was your weekend?",
  "Hey! How was your day today?",
];
const QUESTION_REPLY = "Nice! What did you do after that?";
const SHARE_REPLY = "I went for a long walk by the river today.";
const ACKNOWLEDGE = "💡 いいですね！";
const NO_FIX = "いいですね！そのままで伝わります";
const BLANK_OFF = "💡 ①がまだ違います。A で始まります";
const ACCEPTED = "いいですね！伝わります";
const WRAP_UP = ["Actually, …", "I feel refreshed"];

const INTENT = "週末は家でのんびりしてたよ。";
const ENGLISH = "I stayed home and relaxed.";
const RIGHT_RETRY = "Actually, I stayed home and relaxed.";
const DIRECT_REPLIES = ["I'm good!", "It was really fun!", "Sounds great!"];

const NEXT_AT_ENGLISH =
  "👉 次: それを英語にしてみてください（途中まででOK。詰まったら「ヒント」）";
const NEXT_AFTER_MISS =
  "👉 次: ①の穴だけ埋め直して、英語の文全体をもう一度送ってください";
const NEXT_AT_CHECK_IN = "👉 次: 「続ける」か「終わる」を選んでください";

/** Record every action the screen posts, so a reload can be shown to send none. */
function recordActions(page: Page) {
  const posted: string[] = [];
  page.on("request", (request) => {
    const { pathname } = new URL(request.url());
    if (request.method() === "POST" && pathname.endsWith("/actions")) {
      posted.push(pathname);
    }
  });
  return posted;
}

/**
 * Refuse a run whose API is not in fixed mode, then start a session from S1 and
 * wait for its opener: one of the three fixed openers, and never the opener of
 * the newest earlier session, when there is one.
 */
async function startSession(page: Page) {
  const meta = await page.request.get("/api/meta");
  expect(await meta.json()).toEqual({ model_mode: "fixed" });
  const listed = await page.request.get("/api/sessions");
  const { items } = (await listed.json()) as { items: { opener: string | null }[] };
  const previous = items[0]?.opener ?? null;

  await page.goto("/");
  await expect(page.getByRole("button", { name: "固定応答モード" })).toBeVisible();
  await page.getByRole("button", { name: "新しい会話を始める" }).click();
  await expect(page).toHaveURL(/\/sessions\/[^/]+$/);
  const id = new URL(page.url()).pathname.split("/").at(-1) ?? "";

  const timeline = page
    .getByRole("region", { name: "会話" })
    .getByRole("list", { name: "会話の流れ" });
  await expect(timeline.getByRole("listitem")).toHaveCount(1);
  const opener =
    (await timeline.getByRole("listitem").getByText(/\S/).last().textContent()) ?? "";
  expect(OPENERS).toContain(opener);
  if (previous !== null) expect(opener).not.toBe(previous);
  return { id, opener, timeline };
}

/** Type into the Coach pane's composer, labelled `label`, and send it. */
async function send(page: Page, label: string, text: string) {
  const coach = page.getByRole("region", { name: "コーチ" });
  await coach.getByRole("textbox", { name: label }).fill(text);
  await coach.getByRole("button", { name: "送信" }).click();
}

test("a turn gets its fix, misses the retry once, survives reloads, and is accepted", async ({
  page,
}) => {
  const { id, timeline } = await startSession(page);
  const coach = page.getByRole("region", { name: "コーチ" });
  const turn1 = coach.getByRole("list", { name: "ターン 1" });
  const posted = recordActions(page);

  await send(page, "あなたの日本語", INTENT);
  await expect(turn1.getByText(ACKNOWLEDGE, { exact: true })).toBeVisible();
  await expect(turn1.getByText("組み立てのヒント", { exact: false })).toHaveCount(0);
  await expect(page.getByText(NEXT_AT_ENGLISH, { exact: true })).toBeVisible();

  // F-5 at english: the same blocks and 👉 次 line come back, and nothing is sent.
  posted.length = 0;
  await page.reload();
  await expect(turn1.getByText(INTENT, { exact: true })).toBeVisible();
  await expect(turn1.getByText(ACKNOWLEDGE, { exact: true })).toBeVisible();
  await expect(page.getByText(NEXT_AT_ENGLISH, { exact: true })).toBeVisible();
  expect(posted).toEqual([]);

  await send(page, "あなたの英語", ENGLISH);
  const card = turn1.getByRole("article", { name: "コーチの添削" });
  await expect(card).toBeVisible();
  const fixes = card.getByRole("list", { name: "直し方" }).getByRole("listitem");
  await expect(fixes).toHaveCount(1);
  await expect(fixes).toContainText("元 I");
  await expect(fixes).toContainText("直す Actually, I");
  await expect(fixes).toContainText("改善");
  const [sentence, template] = [
    card.locator("p[lang=en]").nth(0),
    card.locator("p[lang=en]").nth(1),
  ];
  await expect(sentence).toHaveText("I① stayed home and relaxed.");
  await expect(sentence.locator("mark")).toHaveText("I①");
  await expect(template).toHaveText("(①) ____ stayed home and relaxed.");

  // A wrong retry: still at retry, the composer enabled and empty, the card in view.
  await send(page, "あなたの英語", ENGLISH);
  await expect(turn1.getByText(BLANK_OFF, { exact: true })).toBeVisible();
  await expect(page.getByText(NEXT_AFTER_MISS, { exact: true })).toBeVisible();
  const composer = coach.getByRole("textbox", { name: "あなたの英語" });
  await expect(composer).toBeEnabled();
  await expect(composer).toHaveValue("");
  await expect(card).toBeInViewport();

  // F-5 at retry, after the miss.
  posted.length = 0;
  await page.reload();
  await expect(card).toBeVisible();
  await expect(turn1.getByText(BLANK_OFF, { exact: true })).toBeVisible();
  await expect(page.getByText(NEXT_AFTER_MISS, { exact: true })).toBeVisible();
  expect(posted).toEqual([]);

  // A resume from S1's 「続きから」 lands on the same retry.
  await page.getByRole("link", { name: /会話一覧/ }).click();
  await expect(page).toHaveURL("/");
  await page
    .getByRole("region", { name: "続きから" })
    .getByRole("link", { name: "続ける" })
    .click();
  await expect(page).toHaveURL(`/sessions/${id}`);
  await expect(turn1.getByText(BLANK_OFF, { exact: true })).toBeVisible();
  await expect(page.getByText(NEXT_AFTER_MISS, { exact: true })).toBeVisible();

  await send(page, "あなたの英語", RIGHT_RETRY);

  // The learner's line, then the Partner's question; the Coach at turn 2's intent.
  const lines = timeline.getByRole("listitem");
  await expect(lines).toHaveCount(3);
  await expect(lines.nth(1)).toHaveText(`You${RIGHT_RETRY}`);
  await expect(lines.nth(2)).toHaveText(`Partner${QUESTION_REPLY}`);
  expect(QUESTION_REPLY).toContain("?");
  await expect(coach.getByRole("heading", { name: "コーチ · ターン 2" })).toBeVisible();
  await expect(page.getByText(NEXT_AT_INTENT, { exact: true })).toBeVisible();
  await expect(coach.getByText("前のターン: 言い直しできました")).toBeVisible();

  // Turn 1, selected on the left, ends with the accepted retry.
  await lines.nth(1).getByRole("button", { name: RIGHT_RETRY }).click();
  await expect(turn1.getByText(`✓ ${ACCEPTED}`)).toBeVisible();
  await expect(turn1.getByText("✓ 言い直しできました")).toBeVisible();
  await coach.getByRole("button", { name: "今のターンに戻る" }).click();
  await expect(coach.getByRole("heading", { name: "コーチ · ターン 2" })).toBeVisible();
});

test("three direct replies reach the check-in, and ending shows the transcript", async ({
  page,
}) => {
  const { id, timeline } = await startSession(page);
  const coach = page.getByRole("region", { name: "コーチ" });
  const lines = timeline.getByRole("listitem");

  for (const [index, reply] of DIRECT_REPLIES.entries()) {
    await coach.getByRole("button", { name: "英語で直接返す" }).click();
    await send(page, "あなたの英語", reply);
    await expect(lines.nth(2 * index + 1)).toHaveText(`You${reply}`);
    if (index < 2) {
      await expect(lines).toHaveCount(2 * index + 3);
    }
  }

  // Reply 1 answered a question, so the Partner asks; after reply 2 it shares.
  await expect(lines.nth(2)).toHaveText(`Partner${QUESTION_REPLY}`);
  await expect(lines.nth(4)).toHaveText(`Partner${SHARE_REPLY}`);
  await expect(lines.nth(4)).not.toContainText("?");

  // The check-in: no composer, focus on 「続ける」, and no Partner line yet.
  await expect(
    coach.getByText("💡 ここで3往復です。続けますか？", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(NEXT_AT_CHECK_IN, { exact: true })).toBeVisible();
  const controls = coach.getByRole("group", { name: "操作" });
  await expect(controls.getByRole("button", { name: "続ける" })).toBeFocused();
  await expect(coach.getByRole("textbox")).toHaveCount(0);
  await expect(lines).toHaveCount(6);

  await controls.getByRole("button", { name: "終わる" }).click();

  // S3 at the same URL: the wrap-up's two items and the three English lines.
  await expect(page).toHaveURL(`/sessions/${id}`);
  await expect(page.getByText(/3往復 · 終了$/)).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "会話（英文だけの通し）" }),
  ).toBeVisible();
  const wrapUp = page.getByRole("region", { name: "この会話で出てきた表現" });
  const items = wrapUp.getByRole("listitem");
  await expect(items).toHaveCount(2);
  for (const [index, phrase] of WRAP_UP.entries()) {
    await expect(items.nth(index)).toContainText(phrase);
  }
  const transcript = page
    .getByRole("region", { name: "会話" })
    .getByRole("list", { name: "会話の流れ" });
  for (const reply of DIRECT_REPLIES) {
    await expect(
      transcript.getByRole("button", { name: reply, exact: true }),
    ).toBeVisible();
  }
  // Each turn's feedback, opened from S3's list, needed no fix.
  for (const number of [1, 2, 3]) {
    await page.getByRole("button", { name: new RegExp(`^ターン ${number} `) }).click();
    const turn = page.getByRole("list", { name: `ターン ${number}` });
    const card = turn.getByRole("article", { name: "コーチの添削" });
    await expect(card.getByText(NO_FIX, { exact: true })).toBeVisible();
  }
  // S3 has no composer, no control row, and no 👉 次 line.
  await expect(page.getByRole("textbox")).toHaveCount(0);
  await expect(page.getByRole("group", { name: "操作" })).toHaveCount(0);
  await expect(page.getByText(/👉/)).toHaveCount(0);

  await page.getByRole("link", { name: /会話一覧/ }).click();
  await expect(page).toHaveURL("/");
  const row = page
    .getByRole("list", { name: "これまでの会話" })
    .locator(`a[href="/sessions/${id}"]`);
  await expect(row).toContainText("終了");
  await expect(row).toContainText("3往復");
});
