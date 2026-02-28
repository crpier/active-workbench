import { Tabs } from "expo-router";

import { useAppTheme } from "@/theme/use-app-theme";

export default function TabsLayout() {
  const { colors } = useAppTheme();

  return (
    <Tabs
      screenOptions={{
        headerStyle: { backgroundColor: colors.surface },
        headerTintColor: colors.text,
        tabBarStyle: { backgroundColor: colors.surface },
        tabBarActiveTintColor: colors.primary,
        tabBarInactiveTintColor: colors.subtleText,
      }}
    >
      <Tabs.Screen name="articles" options={{ title: "Articles" }} />
      <Tabs.Screen name="history" options={{ title: "History" }} />
      <Tabs.Screen name="chat" options={{ title: "Chat" }} />
      <Tabs.Screen name="settings" options={{ title: "Settings" }} />
    </Tabs>
  );
}
