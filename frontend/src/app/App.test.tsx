import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { axe } from "vitest-axe";

import { renderApp } from "../test/render";

describe("app shell", () => {
  it("redirects to login and signs in", async () => {
    const { router } = renderApp("/", null);
    const user = userEvent.setup();
    await screen.findByRole("heading", { name: "RetailPilot AI" });
    await user.type(screen.getByLabelText("Username"), "sup.c");
    await user.type(screen.getByLabelText("Password"), "demo");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByRole("heading", { level: 1, name: "Store overview" });
    expect(router.state.location.pathname).toBe("/");
  });

  it("shows a wrong-password error", async () => {
    renderApp("/login", null);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Username"), "admin");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Wrong username or password");
  });

  it("gives a supervisor their own navigation, no store switcher, and blocks admin pages", async () => {
    renderApp("/monitoring", "sup.a");
    const nav = await screen.findByRole("navigation", { name: "Main" });
    expect(within(nav).queryByRole("link", { name: "System monitoring" })).toBeNull();
    expect(within(nav).getByRole("link", { name: "Goods receipt" })).toBeTruthy();
    expect(screen.queryByLabelText("Store")).toBeNull();
    expect(await screen.findByText("You do not have access to this page")).toBeTruthy();
  });

  it("gives the super admin the store switcher, period selector and last-run time", async () => {
    renderApp("/", "admin");
    expect(await screen.findByLabelText("Store")).toBeTruthy();
    expect(screen.getByLabelText("Period")).toBeTruthy();
    expect(await screen.findByText("Data as of last run: 3 Nov 2026, 00:12 IST")).toBeTruthy();
  });

  it("reaches every sidebar link with the keyboard after the skip link", async () => {
    renderApp("/", "admin");
    const nav = await screen.findByRole("navigation", { name: "Main" });
    const links = within(nav).getAllByRole("link");
    const user = userEvent.setup();
    await user.tab();
    expect(document.activeElement?.textContent).toBe("Skip to main content");
    for (const link of links) {
      await user.tab();
      expect(document.activeElement).toBe(link);
    }
    await user.keyboard("{Enter}");
    expect(document.activeElement).toBe(links[links.length - 1]);
  });
});

describe("/components page", () => {
  it("renders every component with mock data and has no axe violations (super admin)", async () => {
    const { container } = renderApp("/components", "admin");
    await screen.findByRole("heading", { name: "Design system" });
    await screen.findByText("Transfer 24 × Biscuits 200 g");
    await waitFor(() => expect(screen.getByText(/^Showing 1–10 of/)).toBeTruthy());
    expect(screen.getByText("Donor surplus")).toBeTruthy();
    expect(await axe(container)).toHaveNoViolations();
  }, 20_000);

  it("shows a supervisor the other store only as name + quantity", async () => {
    const { container } = renderApp("/components", "sup.c");
    await screen.findByText("Transfer 24 × Biscuits 200 g");
    const evidence = screen.getByRole("region", { name: "Decision evidence" });
    expect(within(evidence).getByText("Store A - Residential · 24 units")).toBeTruthy();
    expect(within(evidence).queryByText("Donor surplus")).toBeNull();
    expect(within(evidence).queryByText("Donor's protected requirement")).toBeNull();
    expect(within(evidence).getByText("Donor keeps its full requirement")).toBeTruthy();
    expect(within(evidence).getByText("Other stores are shown by name and offered quantity only.")).toBeTruthy();
    expect(await axe(container)).toHaveNoViolations();
  }, 20_000);

  it("shows the donor store's own supervisor their surplus and protected requirement", async () => {
    renderApp("/components", "sup.a");
    await screen.findByText("Transfer 24 × Biscuits 200 g");
    const evidence = screen.getByRole("region", { name: "Decision evidence" });
    expect(within(evidence).getByText("Donor surplus")).toBeTruthy();
    expect(within(evidence).getByText("Donor's protected requirement")).toBeTruthy();
  }, 20_000);

  it("explains why a supervisor of another store cannot open the example", async () => {
    renderApp("/components", "sup.b");
    expect(await screen.findByText(/a supervisor cannot open another store/)).toBeTruthy();
  });
});
