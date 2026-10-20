import { expect, test } from "@playwright/test";

test("S2 fits 320 by 568 with the server-unreachable banner", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  expect(await (await page.request.get("/api/meta")).json()).toEqual({
    model_mode: "fixed",
  });
  const created = await page.request.post("/api/sessions");
  expect(created.status()).toBe(201);
  const { id } = (await created.json()) as { id: string };
  await page.goto(`/sessions/${id}`);
  const field = page.getByRole("textbox", { name: "あなたの日本語" });
  await expect(field).toBeEnabled();
  await page.route("**/api/sessions/*/actions", (route) => route.abort());
  await field.fill("映画を見た");
  await page.getByRole("button", { name: "送信", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "アプリのサーバーに接続できません。",
  );
  const size = await page.evaluate(() => ({
    height: document.documentElement.scrollHeight,
    viewport: window.innerHeight,
    width: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
  }));
  console.log(`S2 outage geometry: ${JSON.stringify(size)}`);
  expect(size.height).toBe(size.viewport);
  expect(size.width).toBe(size.viewportWidth);
  await expect(field).toBeInViewport();
});
