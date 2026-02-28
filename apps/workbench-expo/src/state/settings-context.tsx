import AsyncStorage from "@react-native-async-storage/async-storage";
import { createContext, useContext, useEffect, useMemo, useState } from "react";

import { defaultBackendBaseUrl, normalizeBaseUrl } from "@/api/client";
import type { AppSettings, ThemeMode } from "@/api/types";

const SETTINGS_KEY = "active_workbench.expo.settings.v1";

const defaultSettings: AppSettings = {
  backendBaseUrl: defaultBackendBaseUrl(),
  chatBaseUrl: typeof window !== "undefined" ? window.location.origin : "http://10.0.2.2:4096",
  mobileApiKey: "",
  themeMode: "system",
};

function normalizeThemeMode(value: unknown): ThemeMode {
  if (value === "light" || value === "dark" || value === "system") {
    return value;
  }
  return "system";
}

interface SettingsContextValue {
  settings: AppSettings;
  ready: boolean;
  save: (next: AppSettings) => Promise<void>;
}

const SettingsContext = createContext<SettingsContextValue | null>(null);

export function SettingsProvider({ children }: { children: React.ReactNode }) {
  const [settings, setSettings] = useState<AppSettings>(defaultSettings);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      try {
        const raw = await AsyncStorage.getItem(SETTINGS_KEY);
        if (!raw) {
          return;
        }
        const parsed = JSON.parse(raw) as Partial<AppSettings>;
        if (cancelled) {
          return;
        }
        setSettings({
          backendBaseUrl: normalizeBaseUrl(parsed.backendBaseUrl ?? defaultSettings.backendBaseUrl),
          chatBaseUrl: (parsed.chatBaseUrl ?? defaultSettings.chatBaseUrl).trim(),
          mobileApiKey: (parsed.mobileApiKey ?? "").trim(),
          themeMode: normalizeThemeMode(parsed.themeMode),
        });
      } finally {
        if (!cancelled) {
          setReady(true);
        }
      }
    };
    run().catch(() => setReady(true));
    return () => {
      cancelled = true;
    };
  }, []);

  const value = useMemo<SettingsContextValue>(
    () => ({
      settings,
      ready,
      save: async (next: AppSettings) => {
        const normalized: AppSettings = {
          backendBaseUrl: normalizeBaseUrl(next.backendBaseUrl),
          chatBaseUrl: next.chatBaseUrl.trim(),
          mobileApiKey: next.mobileApiKey.trim(),
          themeMode: normalizeThemeMode(next.themeMode),
        };
        await AsyncStorage.setItem(SETTINGS_KEY, JSON.stringify(normalized));
        setSettings(normalized);
      },
    }),
    [ready, settings],
  );

  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}

export function useSettingsContext(): SettingsContextValue {
  const context = useContext(SettingsContext);
  if (!context) {
    throw new Error("useSettingsContext must be used within SettingsProvider");
  }
  return context;
}
