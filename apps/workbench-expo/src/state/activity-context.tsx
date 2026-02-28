import AsyncStorage from "@react-native-async-storage/async-storage";
import { createContext, useContext, useEffect, useMemo, useState } from "react";

import type { ActivityEntry } from "@/api/types";

const ACTIVITY_KEY = "active_workbench.expo.activity.v1";
const MAX_ITEMS = 200;

interface ActivityContextValue {
  entries: ActivityEntry[];
  addEntry: (entry: Omit<ActivityEntry, "id" | "createdAt">) => Promise<void>;
  clear: () => Promise<void>;
}

const ActivityContext = createContext<ActivityContextValue | null>(null);

export function ActivityProvider({ children }: { children: React.ReactNode }) {
  const [entries, setEntries] = useState<ActivityEntry[]>([]);

  useEffect(() => {
    let cancelled = false;
    AsyncStorage.getItem(ACTIVITY_KEY)
      .then((raw) => {
        if (!raw || cancelled) {
          return;
        }
        const parsed = JSON.parse(raw) as ActivityEntry[];
        if (Array.isArray(parsed)) {
          setEntries(parsed);
        }
      })
      .catch(() => {
        // Best effort only.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const value = useMemo<ActivityContextValue>(
    () => ({
      entries,
      addEntry: async (entry) => {
        const next: ActivityEntry = {
          ...entry,
          id: `evt_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
          createdAt: new Date().toISOString(),
        };
        const updated = [next, ...entries].slice(0, MAX_ITEMS);
        setEntries(updated);
        await AsyncStorage.setItem(ACTIVITY_KEY, JSON.stringify(updated));
      },
      clear: async () => {
        setEntries([]);
        await AsyncStorage.removeItem(ACTIVITY_KEY);
      },
    }),
    [entries],
  );

  return <ActivityContext.Provider value={value}>{children}</ActivityContext.Provider>;
}

export function useActivityContext(): ActivityContextValue {
  const context = useContext(ActivityContext);
  if (!context) {
    throw new Error("useActivityContext must be used within ActivityProvider");
  }
  return context;
}
