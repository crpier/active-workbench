import { useMemo, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import { defaultBackendBaseUrl, normalizeBaseUrl } from "@/api/client";
import type { ThemeMode } from "@/api/types";
import { useActivityContext } from "@/state/activity-context";
import { useSettingsContext } from "@/state/settings-context";
import { useAppTheme } from "@/theme/use-app-theme";

const THEME_OPTIONS: ReadonlyArray<{ key: ThemeMode; label: string }> = [
  { key: "light", label: "Light" },
  { key: "dark", label: "Dark" },
  { key: "system", label: "System" },
];

export default function SettingsScreen() {
  const { settings, save } = useSettingsContext();
  const { addEntry } = useActivityContext();
  const { colors } = useAppTheme();
  const styles = useMemo(() => createStyles(colors), [colors]);

  const [backendBaseUrl, setBackendBaseUrl] = useState(settings.backendBaseUrl || defaultBackendBaseUrl());
  const [chatBaseUrl, setChatBaseUrl] = useState(settings.chatBaseUrl);
  const [mobileApiKey, setMobileApiKey] = useState(settings.mobileApiKey);
  const [themeMode, setThemeMode] = useState<ThemeMode>(settings.themeMode);
  const [error, setError] = useState<string | null>(null);

  return (
    <ScrollView style={styles.screen}>
      <View style={styles.panel}>
        <Text style={styles.title}>App settings</Text>

        <Text style={styles.label}>Backend URL</Text>
        <TextInput
          value={backendBaseUrl}
          onChangeText={setBackendBaseUrl}
          autoCapitalize="none"
          style={styles.input}
          placeholder="http://10.0.2.2:8000"
        />

        <Text style={styles.label}>Chat URL</Text>
        <TextInput
          value={chatBaseUrl}
          onChangeText={setChatBaseUrl}
          autoCapitalize="none"
          style={styles.input}
          placeholder="http://10.0.2.2:4096"
        />

        <Text style={styles.label}>Mobile API key (optional)</Text>
        <TextInput
          value={mobileApiKey}
          onChangeText={setMobileApiKey}
          autoCapitalize="none"
          style={styles.input}
          placeholder="mkey_xxx.secret"
        />

        <Text style={styles.label}>Theme</Text>
        <View style={styles.optionRow}>
          {THEME_OPTIONS.map((option) => (
            <Pressable
              key={option.key}
              onPress={() => setThemeMode(option.key)}
              style={[
                styles.optionButton,
                option.key === themeMode ? styles.optionButtonActive : null,
              ]}
            >
              <Text
                style={[
                  styles.optionLabel,
                  option.key === themeMode ? styles.optionLabelActive : null,
                ]}
              >
                {option.label}
              </Text>
            </Pressable>
          ))}
        </View>

        {error ? (
          <View style={styles.errorPanel}>
            <Text style={styles.errorText}>{error}</Text>
          </View>
        ) : null}

        <Pressable
          style={styles.primaryButton}
          onPress={async () => {
            setError(null);
            const normalizedBackend = normalizeBaseUrl(backendBaseUrl);
            if (!normalizedBackend.startsWith("http://") && !normalizedBackend.startsWith("https://")) {
              setError("Backend URL must start with http:// or https://");
              return;
            }
            if (
              chatBaseUrl.trim().length > 0 &&
              !chatBaseUrl.startsWith("http://") &&
              !chatBaseUrl.startsWith("https://")
            ) {
              setError("Chat URL must start with http:// or https://");
              return;
            }
            await save({
              backendBaseUrl: normalizedBackend,
              chatBaseUrl: chatBaseUrl.trim(),
              mobileApiKey: mobileApiKey.trim(),
              themeMode,
            });
            await addEntry({
              level: "info",
              title: "Settings saved",
              detail: normalizedBackend,
            });
          }}
        >
          <Text style={styles.primaryButtonText}>Save settings</Text>
        </Pressable>
      </View>
    </ScrollView>
  );
}

function createStyles(colors: ReturnType<typeof useAppTheme>["colors"]) {
  return StyleSheet.create({
    screen: {
      flex: 1,
      backgroundColor: colors.background,
      paddingHorizontal: 16,
      paddingVertical: 12,
    },
    panel: {
      backgroundColor: colors.surface,
      borderRadius: 18,
      padding: 12,
    },
    title: {
      color: colors.text,
      fontSize: 18,
      fontWeight: "700",
      marginBottom: 10,
    },
    label: {
      color: colors.subtleText,
      fontSize: 11,
      fontWeight: "700",
      textTransform: "uppercase",
      marginBottom: 6,
    },
    input: {
      borderWidth: 1,
      borderColor: colors.border,
      borderRadius: 12,
      backgroundColor: colors.inputBackground,
      color: colors.text,
      marginBottom: 10,
      paddingHorizontal: 12,
      paddingVertical: 8,
    },
    optionRow: {
      flexDirection: "row",
      gap: 8,
      marginBottom: 10,
    },
    optionButton: {
      borderWidth: 1,
      borderColor: colors.border,
      borderRadius: 999,
      backgroundColor: colors.inputBackground,
      paddingHorizontal: 12,
      paddingVertical: 6,
    },
    optionButtonActive: {
      borderColor: colors.primary,
      backgroundColor: colors.secondarySurface,
    },
    optionLabel: {
      color: colors.text,
      fontSize: 12,
    },
    optionLabelActive: {
      color: colors.primary,
      fontWeight: "700",
    },
    errorPanel: {
      borderWidth: 1,
      borderColor: colors.errorBorder,
      backgroundColor: colors.errorSurface,
      borderRadius: 12,
      paddingHorizontal: 12,
      paddingVertical: 8,
      marginBottom: 10,
    },
    errorText: {
      color: colors.errorText,
      fontSize: 13,
    },
    primaryButton: {
      borderRadius: 12,
      backgroundColor: colors.primary,
      paddingVertical: 10,
    },
    primaryButtonText: {
      color: colors.primaryText,
      textAlign: "center",
      fontWeight: "700",
    },
  });
}
