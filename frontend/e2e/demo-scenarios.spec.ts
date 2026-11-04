/** The five demo scenarios (docs/04-demo-scenarios.md, docs/DEMO_SCRIPT.md) as each demo user sees them. */
import { expect, type Page, test } from "@playwright/test";

async function login(page: Page, username: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill("demo");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("navigation")).toBeVisible();
}

async function recommendations(page: Page, type: string, search: string) {
  await page.goto(`/recommendations?type=${type}`);
  const table = page.getByRole("region", { name: "AI recommendations" });
  await page.getByRole("searchbox").fill(search);
  await expect(table.getByRole("row", { name: new RegExp(search) }).first()).toBeVisible();
  return table;
}

test.beforeAll(async ({ request }) => {
  const health = await request.get("http://127.0.0.1:8077/health");
  expect(health.ok(), "backend not reachable").toBeTruthy();
});

test("scenario 1: rice sells high in every store — purchase orders only", async ({ page }) => {
  await login(page, "admin");
  const table = await recommendations(page, "REORDER", "Rice 5 kg");
  const rows = table.getByRole("row", { name: /Rice 5 kg/ });
  await expect(rows).toHaveCount(3);
  for (const qty of ["35", "45", "51"]) await expect(rows.filter({ hasText: qty })).toHaveCount(1);
  await recommendations(page, "TRANSFER", "Biscuits"); // the transfer list works for the admin
  await page.getByRole("searchbox").fill("Rice 5 kg");
  await expect(
    page.getByRole("region", { name: "AI recommendations" }).getByRole("row", { name: /Rice 5 kg/ }),
  ).toHaveCount(0);
});

test("scenario 2: tea surplus in Store A covers Store C — destination sees name and quantity only", async ({
  page,
}) => {
  await login(page, "sup.c");
  const table = await recommendations(page, "TRANSFER", "Tea 250 g");
  await table.getByRole("row", { name: /Tea 250 g/ }).click();
  await expect(page.getByText("Store A - Residential · 20 units").first()).toBeVisible();
  await expect(page.getByText("Donor keeps its full requirement")).toBeVisible();
  await expect(page.getByText("Donor surplus")).toHaveCount(0);
});

test("scenario 3: partial surplus — transfer 24 plus purchase order 16; donor and third store views", async ({
  page,
  browser,
}) => {
  await login(page, "sup.c");
  const reorders = await recommendations(page, "REORDER", "Biscuits 200 g");
  await expect(reorders.getByRole("row", { name: /Biscuits 200 g/ }).filter({ hasText: "16" })).toHaveCount(1);
  const transfers = await recommendations(page, "TRANSFER", "Biscuits 200 g");
  await transfers.getByRole("row", { name: /Biscuits 200 g/ }).click();
  await expect(page.getByText("Store A - Residential · 24 units").first()).toBeVisible();
  const detailUrl = page.url();

  const donor = await browser.newPage();
  await login(donor, "sup.a");
  await donor.goto(detailUrl);
  await expect(donor.getByText("Donor surplus")).toBeVisible();
  await expect(donor.getByText("24 units").first()).toBeVisible();
  await donor.close();

  const other = await browser.newPage();
  await login(other, "sup.b");
  await other.goto(detailUrl);
  await expect(other.getByText(/another store/i)).toBeVisible();
  await other.close();
});

test("scenario 4: bread reorder with butter co-replenished in Store A", async ({ page }) => {
  await login(page, "sup.a");
  const reorders = await recommendations(page, "REORDER", "Bread 400 g");
  await expect(reorders.getByRole("row", { name: /Bread 400 g/ }).filter({ hasText: "38" })).toHaveCount(1);
  const co = await recommendations(page, "CO_REPLENISH", "Butter 100 g");
  await co.getByRole("row", { name: /Butter 100 g/ }).click();
  await expect(page.getByText(/Bread 400 g/).first()).toBeVisible(); // the linked product in the evidence
  await expect(page.getByText("3 units").first()).toBeVisible();
});

test("scenario 5: paneer at risk in Store A moves to Store C", async ({ page }) => {
  await login(page, "sup.c");
  const table = await recommendations(page, "TRANSFER", "Paneer 200 g");
  await table.getByRole("row", { name: /Paneer 200 g/ }).click();
  await expect(page.getByText("Store A - Residential · 30 units").first()).toBeVisible();
  await expect(page.getByText(/expire|expiry/i).first()).toBeVisible();
});

test("dashboards show API figures for each role", async ({ page }) => {
  await login(page, "admin");
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Business overview" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Revenue", exact: true })).toContainText("₹");
  await expect(page.getByRole("region", { name: "Store performance" })).toContainText("Store C - Temple street");
  await expect(page.getByText(/42\.8L|Anna Nagar/)).toHaveCount(0);
});
