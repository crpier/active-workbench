import { describe, expect, it } from "vitest";

import {
  computeRetryDelaySeconds,
  dedupeInsert,
  isDue,
  withRetryScheduled,
  type PendingShareCapture,
} from "@/state/share-queue";

function item(overrides: Partial<PendingShareCapture> = {}): PendingShareCapture {
  return {
    id: "share_1",
    url: "https://example.com/article-1",
    sharedText: null,
    source: "android_share",
    createdAt: "2026-02-28T12:00:00.000Z",
    attempts: 0,
    nextAttemptAt: "2026-02-28T12:00:00.000Z",
    lastError: null,
    ...overrides,
  };
}

describe("share queue helpers", () => {
  it("computes capped exponential retry delays", () => {
    expect(computeRetryDelaySeconds(1)).toBe(10);
    expect(computeRetryDelaySeconds(2)).toBe(20);
    expect(computeRetryDelaySeconds(3)).toBe(40);
    expect(computeRetryDelaySeconds(10)).toBe(15 * 60);
  });

  it("marks items as due at or after next attempt timestamp", () => {
    const current = item({ nextAttemptAt: "2026-02-28T12:00:10.000Z" });
    expect(isDue(current, new Date("2026-02-28T12:00:09.000Z"))).toBe(false);
    expect(isDue(current, new Date("2026-02-28T12:00:10.000Z"))).toBe(true);
  });

  it("increments attempts and schedules the next retry time", () => {
    const current = item({ attempts: 1 });
    const updated = withRetryScheduled(current, new Date("2026-02-28T12:00:00.000Z"), "offline");
    expect(updated.attempts).toBe(2);
    expect(updated.lastError).toBe("offline");
    expect(updated.nextAttemptAt).toBe("2026-02-28T12:00:20.000Z");
  });

  it("deduplicates queue entries by URL", () => {
    const existing = item();
    const duplicate = item({ id: "share_2" });
    const inserted = dedupeInsert([existing], duplicate);
    expect(inserted).toHaveLength(1);
    expect(inserted[0].id).toBe("share_1");
  });
});

