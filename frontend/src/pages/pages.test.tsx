/** Phase 8a screens on the exported fixtures: Store Inventory, Recommendations inbox and detail. */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { axe } from "vitest-axe";

import type { RecommendationDTO } from "../api/types";
import { FIXTURES } from "../mocks/fixtures";
import { renderApp } from "../test/render";

const store = (code: string) => FIXTURES.stores.find((s) => s.code === code)!;
const scenarioRec = (n: "1" | "2" | "3" | "4" | "5", type: RecommendationDTO["rec_type"]) =>
  FIXTURES.recommendations.find((r) => FIXTURES.scenarios[n].rec_ids.includes(r.rec_id) && r.rec_type === type)!;

beforeEach(() => {
  try {
    localStorage.clear();
  } catch {
    /* ignore */
  }
});

describe("Store Inventory", () => {
  it("asks the super admin to pick a store, then remembers it", async () => {
    const user = userEvent.setup();
    const first = renderApp("/inventory", "admin");
    expect(await screen.findByRole("heading", { name: "Choose a store" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: new RegExp(store("C").name) }));
    expect(await screen.findByRole("region", { name: "Store inventory" })).toBeTruthy();
    first.unmount();

    renderApp("/inventory", "admin"); // last store selected is the default next time
    const select = (await screen.findByLabelText("Inventory for")) as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe(store("C").store_id));
    expect(screen.queryByRole("heading", { name: "Choose a store" })).toBeNull();
  });

  it("shows a supervisor their own store directly, with shelf and backroom as separate columns", async () => {
    renderApp("/inventory", "sup.a");
    const table = await screen.findByRole("region", { name: "Store inventory" });
    await within(table).findAllByRole("row");
    for (const header of ["Shelf", "Shelf min", "Backroom", "Available", "Own requirement", "Surplus / shortage", "Stockout risk"]) {
      expect(within(table).getByRole("columnheader", { name: header })).toBeTruthy();
    }
    expect(screen.queryByLabelText("Inventory for")).toBeNull();
    expect(screen.getByText(store("A").name)).toBeTruthy();
  });

  it("filters by the summary chips", async () => {
    const user = userEvent.setup();
    renderApp("/inventory", "sup.c");
    const chip = await screen.findByRole("button", { name: /^High stockout risk · \d+/ });
    const count = Number(chip.textContent?.split("·")[1]);
    await user.click(chip);
    expect(chip.getAttribute("aria-pressed")).toBe("true");
    await waitFor(() =>
      expect(screen.getByText(count === 0 ? "No rows" : new RegExp(`of ${count}$`))).toBeTruthy(),
    );
  });

  it("switches tabs with the arrow keys and shows the ledger, batches and expiring stock", async () => {
    const user = userEvent.setup();
    renderApp("/inventory", "sup.a");
    const tab = await screen.findByRole("tab", { name: "All products" });
    tab.focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Stock moves" }).getAttribute("aria-selected")).toBe("true");
    expect(await screen.findByRole("region", { name: "Stock moves (movement ledger)" })).toBeTruthy();
    await user.keyboard("{End}");
    expect(await screen.findByRole("region", { name: "Batches expiring within 14 days" })).toBeTruthy();
    expect(await screen.findByText("30 will not sell in time")).toBeTruthy(); // scenario 5 paneer batch in Store A
    await user.keyboard("{ArrowLeft}");
    expect(await screen.findByRole("region", { name: "Batches (earliest expiry first)" })).toBeTruthy();
  });

  it("opens a read-only product drawer with recommendations, transfers and batches", async () => {
    const user = userEvent.setup();
    renderApp("/inventory", "sup.c");
    const table = await screen.findByRole("region", { name: "Store inventory" });
    await user.type(screen.getByRole("searchbox"), "Biscuits 200");
    const cell = await within(table).findByText("Biscuits 200 g (demo)");
    await user.click(cell);
    const drawer = await screen.findByRole("dialog", { name: "Biscuits 200 g (demo)" });
    expect(await within(drawer).findByRole("link", { name: /Transfer · 24 units/ })).toBeTruthy();
    expect(within(drawer).getByRole("link", { name: /Reorder · 16 units/ })).toBeTruthy();
    expect(await within(drawer).findByText(new RegExp(`From ${store("A").name} · 24 units`))).toBeTruthy();
    expect(within(drawer).queryByRole("button", { name: /approve|reject/i })).toBeNull(); // read-only
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("has no axe violations", async () => {
    const { container } = renderApp("/inventory", "sup.a");
    await screen.findByRole("region", { name: "Store inventory" });
    await screen.findByText(/^Showing 1–25 of/);
    expect(await axe(container)).toHaveNoViolations();
  }, 20_000);
});

describe("Recommendations inbox", () => {
  it("filters by type through the URL and opens a recommendation", async () => {
    const user = userEvent.setup();
    const { router } = renderApp("/recommendations", "sup.c");
    await screen.findByRole("region", { name: "AI recommendations" });
    await user.selectOptions(screen.getByLabelText("Type"), "TRANSFER");
    await waitFor(() => expect(router.state.location.search).toContain("type=TRANSFER"));
    const table = screen.getByRole("region", { name: "AI recommendations" });
    const row = await within(table).findByText("Biscuits 200 g (demo)");
    await user.click(row);
    await waitFor(() => expect(router.state.location.pathname).toBe(`/recommendations/${scenarioRec("3", "TRANSFER").rec_id}`));
  });

  it("restores filters from the URL and lists high priority first", async () => {
    renderApp("/recommendations?priority=HIGH", "admin");
    const table = await screen.findByRole("region", { name: "AI recommendations" });
    await within(table).findAllByText("High");
    expect(within(table).queryByText("Normal")).toBeNull();
    expect((screen.getByLabelText("Priority") as HTMLSelectElement).value).toBe("HIGH");
  });

  it("hides the store column for a supervisor and has no axe violations", async () => {
    const { container } = renderApp("/recommendations", "sup.b");
    const table = await screen.findByRole("region", { name: "AI recommendations" });
    await screen.findByText(/^Showing 1–/);
    expect(within(table).queryByRole("columnheader", { name: "Store" })).toBeNull();
    expect(await axe(container)).toHaveNoViolations();
  }, 20_000);
});

describe("Recommendation detail", () => {
  it("scenario 3 for the destination supervisor: transfer and PO remainder shown separately, donor as name + quantity", async () => {
    const { container } = renderApp(`/recommendations/${scenarioRec("3", "TRANSFER").rec_id}`, "sup.c");
    await screen.findByRole("heading", { name: "Transfer · Biscuits 200 g (demo)" });
    expect(screen.getByText("Transfer now").nextSibling?.textContent).toBe("24 units");
    expect(screen.getByText("Order from supplier").nextSibling?.textContent).toBe("16 units");
    const evidence = screen.getByRole("region", { name: "Decision evidence" });
    expect(within(evidence).getByText(`${store("A").name} · 24 units`)).toBeTruthy();
    expect(within(evidence).getByText("Donor keeps its full requirement")).toBeTruthy();
    expect(within(evidence).queryByText("Donor surplus")).toBeNull();
    expect(screen.queryByRole("button", { name: /approve|reject|edit/i })).toBeNull(); // read-only in 8a
    expect(await axe(container)).toHaveNoViolations();
  }, 20_000);

  it("scenario 3 for the donor supervisor shows its own surplus and protected requirement", async () => {
    renderApp(`/recommendations/${scenarioRec("3", "TRANSFER").rec_id}`, "sup.a");
    const evidence = await screen.findByRole("region", { name: "Decision evidence" });
    expect(within(evidence).getByText("Donor surplus")).toBeTruthy();
    expect(within(evidence).getByText("30 units kept")).toBeTruthy();
  });

  it("scenario 3 reorder explains the partial surplus", async () => {
    renderApp(`/recommendations/${scenarioRec("3", "REORDER").rec_id}`, "sup.c");
    const evidence = await screen.findByRole("region", { name: "Decision evidence" });
    expect(within(evidence).getByText("Other stores could cover only part of the need")).toBeTruthy();
    expect(screen.getByText("Covered by transfer").nextSibling?.textContent).toBe("24 units");
  });

  it("scenario 4 co-replenishment shows the bread rule; scenario 5 shows the expiring batch", async () => {
    const first = renderApp(`/recommendations/${scenarioRec("4", "CO_REPLENISH").rec_id}`, "sup.a");
    const co = await screen.findByRole("region", { name: "Decision evidence" });
    expect(within(co).getByText("Bread 400 g (demo)")).toBeTruthy();
    first.unmount();

    renderApp(`/recommendations/${scenarioRec("5", "TRANSFER").rec_id}`, "sup.c");
    const expiry = await screen.findByRole("region", { name: "Decision evidence" });
    expect(within(expiry).getByText("Why this batch should move")).toBeTruthy();
    expect(within(expiry).getByText(/5 days left/)).toBeTruthy();
  });

  it("tells a supervisor of an uninvolved store that it belongs to another store", async () => {
    renderApp(`/recommendations/${scenarioRec("3", "TRANSFER").rec_id}`, "sup.b");
    expect(await screen.findByText("This recommendation belongs to another store.")).toBeTruthy();
  });
});
