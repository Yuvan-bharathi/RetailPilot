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
  it("renders every component and evidence kind with no axe violations", async () => {
    const { container } = renderApp("/components", "admin");
    await screen.findByRole("heading", { name: "Design system" });
    await waitFor(() => expect(screen.getByText(/^Showing 1–10 of/)).toBeTruthy());
    for (const title of [
      "Why order from the supplier",
      "Why add this to the order",
      "Why this is an expiry alert",
      "Why list this product",
      "Why this needs your review",
    ]) {
      expect(screen.getByText(title)).toBeTruthy();
    }
    expect(screen.getByText("Donor keeps its full requirement")).toBeTruthy(); // destination-view example
    expect(await axe(container)).toHaveNoViolations();
  }, 20_000);
});
