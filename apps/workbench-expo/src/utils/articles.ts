import type { ArticleReadState, ArticleStatus, ArticleSummary } from "@/api/types";

export function humanizeReadState(value: ArticleReadState): string {
  if (value === "in_progress") {
    return "In progress";
  }
  if (value === "read") {
    return "Read";
  }
  return "Unread";
}

export function humanizeStatus(value: ArticleStatus): string {
  if (value === "captured") {
    return "Captured";
  }
  if (value === "processing") {
    return "Processing";
  }
  if (value === "readable") {
    return "Readable";
  }
  return "Failed";
}

export function mergeArticlePatch(
  article: ArticleSummary,
  patch: Partial<ArticleSummary>,
): ArticleSummary {
  return {
    ...article,
    ...patch,
    updated_at: patch.updated_at ?? new Date().toISOString(),
  };
}

export function estimateReadProgress(readState: ArticleReadState): number {
  if (readState === "read") {
    return 100;
  }
  if (readState === "in_progress") {
    return 40;
  }
  return 0;
}
