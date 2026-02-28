import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Stack } from "expo-router";
import { useState } from "react";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { ActivityProvider } from "@/state/activity-context";
import { SettingsProvider } from "@/state/settings-context";
import { ShareQueueProvider } from "@/state/share-queue-context";
import { useAppTheme } from "@/theme/use-app-theme";

function ThemedRootStack() {
  const { colors } = useAppTheme();

  return (
    <Stack
      screenOptions={{
        headerStyle: { backgroundColor: colors.surface },
        headerTintColor: colors.text,
        contentStyle: { backgroundColor: colors.background },
      }}
    >
      <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
      <Stack.Screen name="articles/[articleId]" options={{ title: "Article" }} />
    </Stack>
  );
}

export default function RootLayout() {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            gcTime: 5 * 60_000,
            retry: 1,
            refetchOnReconnect: true,
          },
        },
      }),
  );

  return (
    <SafeAreaProvider>
      <SettingsProvider>
        <ShareQueueProvider>
          <ActivityProvider>
            <QueryClientProvider client={queryClient}>
              <ThemedRootStack />
            </QueryClientProvider>
          </ActivityProvider>
        </ShareQueueProvider>
      </SettingsProvider>
    </SafeAreaProvider>
  );
}
