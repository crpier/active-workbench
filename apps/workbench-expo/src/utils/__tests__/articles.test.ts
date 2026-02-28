import { describe, expect, it } from "vitest";

import { estimateReadProgress, humanizeReadState, humanizeStatus, mergeArticlePatch } from "../articles";

describe("article utils", () => {
  it("humanizes read states", () => {
    expect(humanizeReadState("unread")).toBe("Unread");
    expect(humanizeReadState("in_progress")).toBe("In progress");
    expect(humanizeReadState("read")).toBe("Read");
  });

  it("humanizes pipeline statuses", () => {
    expect(humanizeStatus("captured")).toBe("Captured");
    expect(humanizeStatus("processing")).toBe("Processing");
    expect(humanizeStatus("readable")).toBe("Readable");
    expect(humanizeStatus("failed")).toBe("Failed");
  });

  it("merges patches while preserving identity fields", () => {
    const source = {
      article_id: "article_1",
      bucket_item_id: "bucket_1",
      source_url: "https://example.com/source",
      canonical_url: "https://example.com/canonical",
      title: "Before",
      author: null,
      site_name: "Example",
      published_at: null,
      status: "readable",
      read_state: "unread",
      estimated_read_minutes: 5,
      progress_percent: 0,
      extraction_method: "trafilatura",
      llm_polished: false,
      captured_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      last_error_code: null,
      last_error_message: null,
    } as const;
    const merged = mergeArticlePatch(source, { read_state: "read", progress_percent: 100 });
    expect(merged.article_id).toBe("article_1");
    expect(merged.read_state).toBe("read");
    expect(merged.progress_percent).toBe(100);
    expect(merged.updated_at).not.toBe(source.updated_at);
  });

  it("maps read-state to optimistic progress values", () => {
    expect(estimateReadProgress("unread")).toBe(0);
    expect(estimateReadProgress("in_progress")).toBe(40);
    expect(estimateReadProgress("read")).toBe(100);
  });
});
