import { useMemo } from "react";
import { useColorScheme } from "react-native";

import type { ThemeMode } from "@/api/types";
import { useSettingsContext } from "@/state/settings-context";

export type ResolvedTheme = "light" | "dark";

export interface AppColors {
  background: string;
  surface: string;
  text: string;
  subtleText: string;
  border: string;
  inputBackground: string;
  primary: string;
  primaryText: string;
  secondarySurface: string;
  accentText: string;
  errorSurface: string;
  errorBorder: string;
  errorText: string;
}

const lightColors: AppColors = {
  background: "#f3efe6",
  surface: "#fff8ec",
  text: "#1f2937",
  subtleText: "#6b7280",
  border: "#cbd5e1",
  inputBackground: "#ffffff",
  primary: "#0a7ea4",
  primaryText: "#ffffff",
  secondarySurface: "#d6eef7",
  accentText: "#1e3a8a",
  errorSurface: "#fff1f2",
  errorBorder: "#fecdd3",
  errorText: "#9b2226",
};

const darkColors: AppColors = {
  background: "#0f172a",
  surface: "#111827",
  text: "#e5e7eb",
  subtleText: "#9ca3af",
  border: "#334155",
  inputBackground: "#0b1220",
  primary: "#38bdf8",
  primaryText: "#ffffff",
  secondarySurface: "#1e293b",
  accentText: "#93c5fd",
  errorSurface: "#3f1d24",
  errorBorder: "#7f1d1d",
  errorText: "#fecaca",
};

export function resolveThemeMode(mode: ThemeMode, systemScheme: string | null): ResolvedTheme {
  if (mode === "light" || mode === "dark") {
    return mode;
  }
  return systemScheme === "dark" ? "dark" : "light";
}

export function useAppTheme(): { mode: ThemeMode; resolvedTheme: ResolvedTheme; colors: AppColors } {
  const { settings } = useSettingsContext();
  const systemScheme = useColorScheme();

  return useMemo(() => {
    const resolvedTheme = resolveThemeMode(settings.themeMode, systemScheme);
    return {
      mode: settings.themeMode,
      resolvedTheme,
      colors: resolvedTheme === "dark" ? darkColors : lightColors,
    };
  }, [settings.themeMode, systemScheme]);
}
