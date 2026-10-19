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
