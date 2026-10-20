import { expect, test } from "@playwright/test";

test("S1 restores the loaded second page and scroll position after a session", async ({
  page,
}) => {
  expect(await (await page.request.get("/api/meta")).json()).toEqual({
    model_mode: "fixed",
  });
  const ids: string[] = [];
  for (let index = 0; index < 22; index += 1) {
    const response = await page.request.post("/api/sessions");
    expect(response.status()).toBe(201);
    const { id } = (await response.json()) as { id: string };
    ids.push(id);
  }
  await page.setViewportSize({ width: 375, height: 667 });
  await page.goto("/");
  const list = page.getByRole("list", { name: "これまでの会話" });
  await expect(list.getByRole("listitem")).toHaveCount(20);
  await page.getByRole("button", { name: "さらに表示" }).click();
  await expect(list.locator(`a[href="/sessions/${ids[0]}"]`)).toHaveCount(1);
  const loaded = await list.getByRole("listitem").count();
  const more = page.getByRole("button", { name: "さらに表示" });
  const moreCount = await more.count();
  const last = list.getByRole("listitem").last().getByRole("link");
  await last.scrollIntoViewIfNeeded();
  await expect(last).toBeInViewport();
  const before = await page.evaluate(() => window.scrollY);
  expect(before).toBeGreaterThan(0);
  await last.click();
  await expect(page.getByRole("textbox", { name: "あなたの日本語" })).toBeEnabled();
  const back = page.getByRole("link", { name: "← 一覧" });
  await expect(back).toHaveAttribute("href", "/");
  await back.click();
  await expect(list.getByRole("listitem")).toHaveCount(loaded);
  await expect(last).toBeInViewport();
  await expect
    .poll(async () => Math.abs((await page.evaluate(() => window.scrollY)) - before))
    .toBeLessThanOrEqual(3);
  await expect(more).toHaveCount(moreCount);
});
