import { expect, test } from "@playwright/test";

// Runs on desktop and mobile (see playwright.config.ts). Needs the backend running and
// E2E_PASSWORD set to SEED_DEMO_PASSWORD.
const password = process.env.E2E_PASSWORD ?? "";

test("signed-out users are sent to the login page", async ({ page }) => {
  await page.goto("/folders");
  await expect(page).toHaveURL(/\/login\?next=%2Ffolders/);
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
});

test("sign in and open a folder", async ({ page, isMobile }) => {
  test.skip(!password, "Set E2E_PASSWORD to the demo password");
  await page.goto("/login");
  await page.getByLabel("Email").fill("alice@ledgerly.test");
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/folders$/);

  await page.getByRole("main").getByRole("link", { name: /Q3/ }).first().click();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  // The assistant is a side column on desktop and a button on phones.
  if (isMobile) await expect(page.getByRole("button", { name: "Assistant" })).toBeVisible();
  else await expect(page.getByRole("complementary", { name: "Assistant" })).toBeVisible();

  // Records table: rows load, and the status filter asks the server again.
  const table = page.getByRole("table");
  await expect(table.getByRole("row").nth(1)).toBeVisible();
  await expect(page.getByText(/^\d+–\d+ of \d+$/)).toBeVisible();
  await page.getByRole("group", { name: "Filter by status" }).getByRole("button", { name: "paid" }).click();
  await expect(page.getByRole("button", { name: "paid" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText(/^\d+–\d+ of \d+$/)).toBeVisible();

  // The assistant opens with the engine toggle.
  if (isMobile) await page.getByRole("button", { name: "Assistant" }).click();
  await expect(page.getByRole("radio", { name: "LangGraph" }).last()).toBeVisible();
});
