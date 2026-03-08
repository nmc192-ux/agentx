/**
 * AgentX Frontend — Utility function tests
 */
import {
  formatTrust,
  shortDid,
  formatDate,
  timeAgo,
  clamp,
  cn,
} from "@/lib/utils";
import { trustTierFromScore, trustTierColor, postTypeColor } from "@/types";

// ── formatTrust ───────────────────────────────────────────────────────────────

describe("formatTrust", () => {
  it("formats 0.75 as 75%", () => expect(formatTrust(0.75)).toBe("75%"));
  it("formats 1.0 as 100%", () => expect(formatTrust(1.0)).toBe("100%"));
  it("formats 0.0 as 0%",   () => expect(formatTrust(0.0)).toBe("0%"));
  it("rounds correctly",     () => expect(formatTrust(0.756)).toBe("76%"));
});

// ── shortDid ──────────────────────────────────────────────────────────────────

describe("shortDid", () => {
  it("extracts last segment",   () => expect(shortDid("did:agentx:nova-001")).toBe("nova-001"));
  it("handles no colon",        () => expect(shortDid("plain")).toBe("plain"));
  it("handles empty string",    () => expect(shortDid("")).toBe(""));
});

// ── clamp ─────────────────────────────────────────────────────────────────────

describe("clamp", () => {
  it("clamps below min",   () => expect(clamp(-1, 0, 1)).toBe(0));
  it("clamps above max",   () => expect(clamp(5, 0, 1)).toBe(1));
  it("passes through mid", () => expect(clamp(0.5, 0, 1)).toBe(0.5));
});

// ── cn ────────────────────────────────────────────────────────────────────────

describe("cn", () => {
  it("merges class names",        () => expect(cn("a", "b")).toBe("a b"));
  it("deduplicates tailwind",     () => expect(cn("p-2", "p-4")).toBe("p-4"));
  it("handles conditional false", () => expect(cn("a", false && "b")).toBe("a"));
});

// ── trustTierFromScore ────────────────────────────────────────────────────────

describe("trustTierFromScore", () => {
  it("returns elite for ≥0.9",      () => expect(trustTierFromScore(0.95)).toBe("elite"));
  it("returns trusted for ≥0.7",    () => expect(trustTierFromScore(0.75)).toBe("trusted"));
  it("returns verified for ≥0.4",   () => expect(trustTierFromScore(0.5)).toBe("verified"));
  it("returns unverified for <0.4",  () => expect(trustTierFromScore(0.2)).toBe("unverified"));
  it("boundary 0.9 → elite",        () => expect(trustTierFromScore(0.9)).toBe("elite"));
  it("boundary 0.7 → trusted",      () => expect(trustTierFromScore(0.7)).toBe("trusted"));
  it("boundary 0.4 → verified",     () => expect(trustTierFromScore(0.4)).toBe("verified"));
});

// ── trustTierColor ────────────────────────────────────────────────────────────

describe("trustTierColor", () => {
  it("returns hex string for each tier", () => {
    expect(trustTierColor("elite")).toMatch(/^#[0-9A-Fa-f]{6}$/);
    expect(trustTierColor("trusted")).toMatch(/^#[0-9A-Fa-f]{6}$/);
    expect(trustTierColor("verified")).toMatch(/^#[0-9A-Fa-f]{6}$/);
    expect(trustTierColor("unverified")).toMatch(/^#[0-9A-Fa-f]{6}$/);
  });

  it("elite color is different from unverified", () => {
    expect(trustTierColor("elite")).not.toBe(trustTierColor("unverified"));
  });
});

// ── postTypeColor ─────────────────────────────────────────────────────────────

describe("postTypeColor", () => {
  const types = ["REQUEST", "OFFER", "TASK", "PREDICTION", "UPDATE", "PROPOSAL"] as const;

  types.forEach((type) => {
    it(`returns hex for ${type}`, () => {
      expect(postTypeColor(type)).toMatch(/^#[0-9A-Fa-f]{6}$/);
    });
  });

  it("all types have distinct colors", () => {
    const colors = types.map(postTypeColor);
    const unique  = new Set(colors);
    expect(unique.size).toBe(types.length);
  });
});

// ── timeAgo ───────────────────────────────────────────────────────────────────

describe("timeAgo", () => {
  it("returns 'just now' for very recent timestamps", () => {
    const now = new Date().toISOString();
    expect(timeAgo(now)).toBe("just now");
  });

  it("returns minutes for 5-minute-old timestamp", () => {
    const fiveMinAgo = new Date(Date.now() - 5 * 60 * 1000).toISOString();
    expect(timeAgo(fiveMinAgo)).toContain("minute");
  });

  it("returns hours for 2-hour-old timestamp", () => {
    const twoHoursAgo = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();
    expect(timeAgo(twoHoursAgo)).toContain("hour");
  });
});
