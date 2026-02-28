import AsyncStorage from "@react-native-async-storage/async-storage";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { AppState } from "react-native";

import { ApiClient } from "@/api/client";
import { useSettingsContext } from "@/state/settings-context";
import { dedupeInsert, isDue, withRetryScheduled, type PendingShareCapture } from "@/state/share-queue";

const SHARE_QUEUE_KEY = "active_workbench.expo.share_queue.v1";
const FLUSH_INTERVAL_MS = 20_000;

interface SubmitShareInput {
  url: string;
  sharedText?: string | null;
  source?: string;
}

interface ShareQueueContextValue {
  ready: boolean;
  pendingCount: number;
  isFlushing: boolean;
  submitShare: (input: SubmitShareInput) => Promise<{ queued: boolean }>;
  flushNow: () => Promise<void>;
}

const ShareQueueContext = createContext<ShareQueueContextValue | null>(null);

function buildPendingItem(input: SubmitShareInput): PendingShareCapture {
  const now = new Date().toISOString();
  return {
    id: `share_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`,
    url: input.url.trim(),
    sharedText: input.sharedText?.trim() || null,
    source: input.source?.trim() || "android_share",
    createdAt: now,
    attempts: 0,
    nextAttemptAt: now,
    lastError: null,
  };
}

export function ShareQueueProvider({ children }: { children: React.ReactNode }) {
  const { settings } = useSettingsContext();
  const api = useMemo(
    () =>
      new ApiClient({
        baseUrl: settings.backendBaseUrl,
        mobileApiKey: settings.mobileApiKey,
      }),
    [settings.backendBaseUrl, settings.mobileApiKey],
  );

  const [ready, setReady] = useState(false);
  const [queue, setQueue] = useState<PendingShareCapture[]>([]);
  const [isFlushing, setIsFlushing] = useState(false);
  const flushInFlight = useRef<Promise<void> | null>(null);
  const queueRef = useRef<PendingShareCapture[]>([]);

  const persistQueue = useCallback(async (next: PendingShareCapture[]) => {
    queueRef.current = next;
    setQueue(next);
    await AsyncStorage.setItem(SHARE_QUEUE_KEY, JSON.stringify(next));
  }, []);

  useEffect(() => {
    let cancelled = false;
    AsyncStorage.getItem(SHARE_QUEUE_KEY)
      .then((raw) => {
        if (cancelled || !raw) {
          return;
        }
        const parsed = JSON.parse(raw) as unknown;
        if (!Array.isArray(parsed)) {
          return;
        }
        const normalized = parsed
          .filter((item): item is PendingShareCapture => {
            if (typeof item !== "object" || item === null) {
              return false;
            }
            const value = item as Record<string, unknown>;
            return (
              typeof value.id === "string" &&
              typeof value.url === "string" &&
              typeof value.source === "string" &&
              typeof value.createdAt === "string" &&
              typeof value.nextAttemptAt === "string" &&
              typeof value.attempts === "number"
            );
          })
          .map((item) => ({
            ...item,
            sharedText: item.sharedText ?? null,
            lastError: item.lastError ?? null,
          }));
        queueRef.current = normalized;
        setQueue(normalized);
      })
      .finally(() => {
        if (!cancelled) {
          setReady(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const flushNow = useCallback(async () => {
    if (flushInFlight.current) {
      return flushInFlight.current;
    }

    const run = (async () => {
      setIsFlushing(true);
      try {
        let current = [...queueRef.current];
        const now = new Date();
        const due = current.filter((item) => isDue(item, now));
        for (const pending of due) {
          try {
            const result = await api.captureArticle({
              url: pending.url,
              sharedText: pending.sharedText ?? undefined,
              processNow: true,
            });
            if (result.status === "failed") {
              throw new Error(result.message ?? "Capture failed.");
            }
            current = current.filter((item) => item.id !== pending.id);
            await persistQueue(current);
          } catch (error) {
            const message = error instanceof Error ? error.message : "Capture failed";
            current = current.map((item) =>
              item.id === pending.id ? withRetryScheduled(item, new Date(), message) : item,
            );
            await persistQueue(current);
          }
        }
      } finally {
        setIsFlushing(false);
        flushInFlight.current = null;
      }
    })();

    flushInFlight.current = run;
    return run;
  }, [api, persistQueue]);

  const submitShare = useCallback(
    async (input: SubmitShareInput): Promise<{ queued: boolean }> => {
      const pending = buildPendingItem(input);
      const nextQueue = dedupeInsert(queueRef.current, pending);
      await persistQueue(nextQueue);

      await flushNow();
      const stillPending = queueRef.current.some((item) => item.id === pending.id);
      return { queued: stillPending };
    },
    [flushNow, persistQueue],
  );

  useEffect(() => {
    if (!ready) {
      return;
    }
    flushNow().catch(() => undefined);
    const interval = setInterval(() => {
      flushNow().catch(() => undefined);
    }, FLUSH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [flushNow, ready]);

  useEffect(() => {
    const subscription = AppState.addEventListener("change", (nextState) => {
      if (nextState === "active") {
        flushNow().catch(() => undefined);
      }
    });
    return () => {
      subscription.remove();
    };
  }, [flushNow]);

  const value = useMemo<ShareQueueContextValue>(
    () => ({
      ready,
      pendingCount: queue.length,
      isFlushing,
      submitShare,
      flushNow,
    }),
    [flushNow, isFlushing, queue.length, ready, submitShare],
  );

  return <ShareQueueContext.Provider value={value}>{children}</ShareQueueContext.Provider>;
}

export function useShareQueueContext(): ShareQueueContextValue {
  const context = useContext(ShareQueueContext);
  if (!context) {
    throw new Error("useShareQueueContext must be used within ShareQueueProvider");
  }
  return context;
}
