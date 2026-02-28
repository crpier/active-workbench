import { useMemo } from "react";
import { Platform, Pressable, StyleSheet, Text, View } from "react-native";
import { WebView } from "react-native-webview";

import { useSettingsContext } from "@/state/settings-context";
import { useAppTheme } from "@/theme/use-app-theme";

export default function ChatScreen() {
  const { settings } = useSettingsContext();
  const { colors } = useAppTheme();
  const styles = useMemo(() => createStyles(colors), [colors]);
  const url = settings.chatBaseUrl.trim();

  if (!url) {
    return (
      <View style={styles.centered}>
        <Text style={styles.subtle}>Set Chat URL in Settings first.</Text>
      </View>
    );
  }

  if (Platform.OS === "web") {
    return (
      <View style={styles.screen}>
        <View style={styles.panel}>
          <Text style={styles.title}>Chat is available at:</Text>
          <Pressable
            onPress={() => {
              if (typeof window !== "undefined") {
                window.open(url, "_blank")?.focus();
              }
            }}
          >
            <Text style={styles.link}>{url}</Text>
          </Pressable>
        </View>
      </View>
    );
  }

  return <WebView source={{ uri: url }} style={{ flex: 1 }} />;
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
      padding: 16,
    },
    title: {
      color: colors.text,
      fontSize: 16,
      fontWeight: "700",
      marginBottom: 8,
    },
    link: {
      color: colors.primary,
      textDecorationLine: "underline",
    },
    centered: {
      flex: 1,
      backgroundColor: colors.background,
      alignItems: "center",
      justifyContent: "center",
      paddingHorizontal: 24,
    },
    subtle: {
      color: colors.subtleText,
      textAlign: "center",
    },
  });
}
