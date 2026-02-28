export interface PendingShareCapture {
  id: string;
  url: string;
  sharedText: string | null;
  source: string;
  createdAt: string;
  attempts: number;
  nextAttemptAt: string;
  lastError: string | null;
}

const BASE_RETRY_SECONDS = 10;
const MAX_RETRY_SECONDS = 15 * 60;

export function computeRetryDelaySeconds(attempts: number): number {
  const exponent = Math.max(0, attempts - 1);
  const computed = BASE_RETRY_SECONDS * 2 ** exponent;
  return Math.min(MAX_RETRY_SECONDS, computed);
}

export function withRetryScheduled(
  item: PendingShareCapture,
  now: Date,
  error: string,
): PendingShareCapture {
  const attempts = item.attempts + 1;
  const delaySeconds = computeRetryDelaySeconds(attempts);
  return {
    ...item,
    attempts,
    nextAttemptAt: new Date(now.getTime() + delaySeconds * 1000).toISOString(),
    lastError: error,
  };
}

export function isDue(item: PendingShareCapture, now: Date): boolean {
  const dueAt = Date.parse(item.nextAttemptAt);
  return Number.isNaN(dueAt) || dueAt <= now.getTime();
}

export function dedupeInsert(
  queue: PendingShareCapture[],
  incoming: PendingShareCapture,
): PendingShareCapture[] {
  const existing = queue.find((item) => item.url === incoming.url);
  if (existing) {
    return queue;
  }
  return [incoming, ...queue].sort((left, right) => left.createdAt.localeCompare(right.createdAt));
}

