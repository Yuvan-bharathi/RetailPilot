import { describe, expect, it } from "vitest";

import {
  formatDateIST,
  formatDateTimeIST,
  formatDays,
  formatINR,
  formatINRCompact,
  formatNumber,
  formatPercent,
} from "./format";

describe("formatters", () => {
  it("groups rupees the Indian way", () => {
    expect(formatINR("123456.5")).toBe("₹1,23,456.50");
    expect(formatINR(1234567, { whole: true })).toBe("₹12,34,567");
    expect(formatNumber(1234567)).toBe("12,34,567");
  });

  it("compacts to K, L and Cr", () => {
    expect(formatINRCompact("4280000")).toBe("₹42.8L");
    expect(formatINRCompact(12_000_000)).toBe("₹1.2Cr");
    expect(formatINRCompact(12_500)).toBe("₹12.5K");
    expect(formatINRCompact(950)).toBe("₹950");
    expect(formatINRCompact(-250_000)).toBe("−₹2.5L");
  });

  it("formats ratios and days", () => {
    expect(formatPercent(0.125)).toBe("12.5%");
    expect(formatDays(3.25)).toBe("3.3 days");
  });

  it("shows datetimes in IST and plain dates unshifted", () => {
    expect(formatDateTimeIST("2026-11-02T18:15:00Z")).toBe("2 Nov 2026, 23:45 IST");
    expect(formatDateIST("2026-11-03")).toBe("3 Nov 2026");
    expect(formatDateIST("2026-11-02T19:00:00Z")).toBe("3 Nov 2026"); // already the next day in IST
  });

  it("rejects non-numbers", () => {
    expect(() => formatINR("abc")).toThrow();
  });
});
