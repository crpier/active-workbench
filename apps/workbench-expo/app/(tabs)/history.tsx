import { useMemo } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { useActivityContext } from "@/state/activity-context";
import { useAppTheme } from "@/theme/use-app-theme";

export default function HistoryScreen() {
  const { entries, clear } = useActivityContext();
  const { colors } = useAppTheme();
  const styles = useMemo(() => createStyles(colors), [colors]);

  return (
    <View style={styles.screen}>
      <View style={styles.header}>
        <Text style={styles.title}>Recent activity</Text>
        <Pressable onPress={() => clear()} style={styles.clearButton}>
          <Text style={styles.clearLabel}>Clear</Text>
        </Pressable>
      </View>

      <ScrollView>
        {entries.map((entry) => (
          <View key={entry.id} style={styles.item}>
            <Text style={entry.level === "error" ? styles.errorTag : styles.infoTag}>
              {entry.level === "error" ? "ERROR" : "INFO"}
            </Text>
            <Text style={styles.itemTitle}>{entry.title}</Text>
            <Text style={styles.detail}>{entry.detail}</Text>
            <Text style={styles.detail}>{new Date(entry.createdAt).toLocaleString()}</Text>
          </View>
        ))}

        {entries.length === 0 ? (
          <View style={styles.item}>
            <Text style={styles.detail}>No activity yet.</Text>
          </View>
        ) : null}
      </ScrollView>
    </View>
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
    header: {
      flexDirection: "row",
      justifyContent: "space-between",
      alignItems: "center",
      backgroundColor: colors.surface,
      borderRadius: 18,
      padding: 12,
      marginBottom: 12,
    },
    title: {
      color: colors.text,
      fontSize: 18,
      fontWeight: "700",
    },
    clearButton: {
      borderWidth: 1,
      borderColor: colors.border,
      borderRadius: 10,
      backgroundColor: colors.inputBackground,
      paddingHorizontal: 12,
      paddingVertical: 6,
    },
    clearLabel: {
      color: colors.text,
      fontSize: 12,
    },
    item: {
      backgroundColor: colors.surface,
      borderRadius: 18,
      padding: 12,
      marginBottom: 12,
    },
    infoTag: {
      color: colors.primary,
      fontSize: 11,
      fontWeight: "700",
    },
    errorTag: {
      color: colors.errorText,
      fontSize: 11,
      fontWeight: "700",
    },
    itemTitle: {
      color: colors.text,
      fontSize: 16,
      fontWeight: "700",
      marginTop: 4,
    },
    detail: {
      color: colors.subtleText,
      fontSize: 13,
      marginTop: 4,
    },
  });
}
