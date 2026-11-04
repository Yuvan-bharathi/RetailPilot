/** Analytics and Settings (D-48): data from the API (fixtures computed from the synthetic data), editable rules. */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { axe } from "vitest-axe";

import { formatINR } from "../lib/format";
import { FIXTURES } from "../mocks/fixtures";
import { renderApp } from "./render";

describe("Analytics", () => {
  it("shows the computed classification, categories and lost sales — no sample figures", async () => {
    renderApp("/analytics", "admin");
    const lost = await screen.findByRole("region", { name: "Highest lost sales (latest run)" });
    const top = FIXTURES.analytics.all!.top_lost_sales[0]!;
    const row = within(lost).getAllByRole("row")[1]!;
    expect(row.textContent).toContain(top.product.name);
    expect(row.textContent).toContain(formatINR(top.lost_revenue));
    const abc = screen.getByRole("region", { name: "ABC-XYZ classification" });
    const total = FIXTURES.analytics.all!.abc_xyz.reduce((s, c) => s + c.skus, 0);
    const shown = within(abc)
      .getAllByRole("cell")
      .reduce((s, c) => s + Number(c.textContent?.replace(/,/g, "")), 0);
    expect(shown).toBe(total);
    expect(screen.queryByText(/18\.4L|342/)).toBeNull();
  });

  it("is scoped to the supervisor's store and has no axe violations", async () => {
    const { container } = renderApp("/analytics", "sup.c");
    expect(await screen.findByRole("heading", { level: 1, name: "Store reports" })).toBeTruthy(); // shell title
    await screen.findByRole("region", { name: "Revenue and margin by category" });
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe("Settings", () => {
  it("lets the Super Admin change a business rule and shows the saved value", async () => {
    const user = userEvent.setup();
    renderApp("/settings", "admin");
    const group = await screen.findByRole("region", { name: "Forecasting" });
    await user.click(within(group).getByRole("button", { name: "Change Stale after" }));
    const input = within(group).getByLabelText("Stale after");
    await user.clear(input);
    await user.type(input, "5");
    await user.click(within(group).getByRole("button", { name: "Save" }));
    expect(await within(group).findByText("5 days")).toBeTruthy();
  });

  it("refuses an out-of-range value with a visible error", async () => {
    const user = userEvent.setup();
    renderApp("/settings", "admin");
    const group = await screen.findByRole("region", { name: "Transfer vs purchase cost" });
    await user.click(within(group).getByRole("button", { name: "Change Expiry risk of perishable surplus" }));
    const input = within(group).getByLabelText("Expiry risk of perishable surplus");
    await user.clear(input);
    await user.type(input, "1.5");
    await user.click(within(group).getByRole("button", { name: "Save" }));
    expect((await within(group).findByRole("alert")).textContent).toMatch(/Invalid/);
  });

  it("shows a supervisor their profile only", async () => {
    renderApp("/settings", "sup.a");
    expect(await screen.findByRole("heading", { level: 1, name: "Profile" })).toBeTruthy(); // shell title
    expect(await screen.findByRole("region", { name: "Account" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Forecasting" })).toBeNull();
    expect(screen.queryByText(/Service level|16:00/)).toBeNull();
  });
});
