import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSegments } from "expo-router";
import { useShareIntent } from "expo-share-intent";
import { useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  useWindowDimensions,
  View,
} from "react-native";

import { ApiError } from "@/api/client";
import { useApiClient } from "@/api/hooks";
import type { ArticleReadState, ArticleSummary } from "@/api/types";
import { useActivityContext } from "@/state/activity-context";
import { useShareQueueContext } from "@/state/share-queue-context";
import {
  estimateReadProgress,
  humanizeReadState,
  humanizeStatus,
  mergeArticlePatch,
} from "@/utils/articles";
import { useAppTheme } from "@/theme/use-app-theme";

const FILTERS: ReadonlyArray<{ key: ArticleReadState | "all"; label: string }> = [
  { key: "all", label: "All" },
  { key: "unread", label: "Unread" },
  { key: "in_progress", label: "In progress" },
  { key: "read", label: "Read" },
];
const DESKTOP_BREAKPOINT = 1024;

export default function ArticlesScreen() {
  const router = useRouter();
  const segments = useSegments();
  const { width } = useWindowDimensions();
  const { colors } = useAppTheme();
  const styles = useMemo(() => createStyles(colors), [colors]);
  const api = useApiClient();
  const queryClient = useQueryClient();
  const { addEntry } = useActivityContext();
  const { pendingCount, isFlushing, submitShare, flushNow } = useShareQueueContext();
  const isDesktopWeb = Platform.OS === "web" && width >= DESKTOP_BREAKPOINT;

  const [filter, setFilter] = useState<ArticleReadState | "all">("all");
  const [captureUrl, setCaptureUrl] = useState("");
  const [captureNote, setCaptureNote] = useState("");
  const [inlineError, setInlineError] = useState<string | null>(null);

  const listKey = useMemo(() => ["articles", filter] as const, [filter]);

  const listQuery = useQuery({
    queryKey: listKey,
    queryFn: () => api.listArticles(filter),
  });

  const readStateMutation = useMutation({
    mutationFn: async ({ articleId, readState }: { articleId: string; readState: ArticleReadState }) =>
      api.markReadState({
        articleId,
        readState,
        progressPercent: estimateReadProgress(readState),
      }),
    onMutate: async ({ articleId, readState }) => {
      await queryClient.cancelQueries({ queryKey: listKey });
      const previous = queryClient.getQueryData<typeof listQuery.data>(listKey);
      queryClient.setQueryData(listKey, (current: typeof listQuery.data) => {
        if (!current) {
          return current;
        }
        return {
          ...current,
          items: current.items.map((item) =>
            item.article_id === articleId
              ? mergeArticlePatch(item, {
                  read_state: readState,
                  progress_percent: estimateReadProgress(readState),
                })
              : item,
          ),
        };
      });
      return { previous };
    },
    onError: async (error, _variables, context) => {
      if (context?.previous) {
        queryClient.setQueryData(listKey, context.previous);
      }
      const message = error instanceof ApiError ? error.message : "Could not update read state.";
      setInlineError(message);
      await addEntry({
        level: "error",
        title: "Read-state update failed",
        detail: message,
      });
    },
    onSuccess: (result) => {
      queryClient.setQueryData(listKey, (current: typeof listQuery.data) => {
        if (!current) {
          return current;
        }
        return {
          ...current,
          items: current.items.map((item) =>
            item.article_id === result.article.article_id ? result.article : item,
          ),
        };
      });
    },
  });

  const captureMutation = useMutation({
    mutationFn: async ({ url, note }: { url: string; note: string }) =>
      api.captureArticle({
        url,
        sharedText: note || undefined,
        processNow: true,
      }),
    onMutate: async ({ url }) => {
      await queryClient.cancelQueries({ queryKey: listKey });
      const previous = queryClient.getQueryData<typeof listQuery.data>(listKey);
      const optimistic: ArticleSummary = {
        article_id: `article_temp_${Date.now()}`,
        bucket_item_id: "bucket_temp",
        source_url: url,
        canonical_url: url,
        title: "Saving article...",
        author: null,
        site_name: null,
        published_at: null,
        status: "captured",
        read_state: "unread",
        estimated_read_minutes: null,
        progress_percent: 0,
        extraction_method: null,
        llm_polished: false,
        captured_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        last_error_code: null,
        last_error_message: null,
      };
      queryClient.setQueryData(listKey, (current: typeof listQuery.data) => {
        if (!current) {
          return {
            count: 1,
            cursor: 0,
            next_cursor: null,
            items: [optimistic],
          };
        }
        return {
          ...current,
          count: current.count + 1,
          items: [optimistic, ...current.items],
        };
      });
      return { previous };
    },
    onError: async (error, _variables, context) => {
      if (context?.previous) {
        queryClient.setQueryData(listKey, context.previous);
      }
      const message = error instanceof ApiError ? error.message : "Article capture failed.";
      setInlineError(message);
      await addEntry({
        level: "error",
        title: "Capture failed",
        detail: message,
      });
    },
    onSuccess: async (result) => {
      if (result.status === "failed") {
        const message = result.message ?? "Article capture failed.";
        setInlineError(message);
        await addEntry({
          level: "error",
          title: "Capture failed",
          detail: message,
        });
      } else {
        setInlineError(null);
        setCaptureUrl("");
        setCaptureNote("");
        await addEntry({
          level: "info",
          title: result.status === "saved" ? "Article saved" : "Article already existed",
          detail: result.canonical_url ?? "",
        });
      }
      await queryClient.invalidateQueries({ queryKey: listKey });
    },
  });

  const shareIntent = useShareIntent({ disabled: Platform.OS === "web" });
  useEffect(() => {
    if (!shareIntent.hasShareIntent) {
      return;
    }
    const sharedUrl = shareIntent.shareIntent.webUrl ?? shareIntent.shareIntent.text;
    if (!sharedUrl) {
      return;
    }
    setCaptureUrl(sharedUrl);
    const run = async () => {
      const result = await submitShare({
        url: sharedUrl,
        sharedText: shareIntent.shareIntent.text ?? "",
        source: "android_share",
      });
      if (result.queued) {
        await addEntry({
          level: "info",
          title: "Share queued",
          detail: "Will retry automatically when app is active.",
        });
      } else {
        await addEntry({
          level: "info",
          title: "Article saved",
          detail: sharedUrl,
        });
      }
      await queryClient.invalidateQueries({ queryKey: listKey });
    };
    run().catch(() => undefined);
    shareIntent.resetShareIntent();
  }, [addEntry, listKey, queryClient, shareIntent, submitShare]);

  const items = listQuery.data?.items ?? [];

  return (
    <View style={styles.screen}>
      <View style={[styles.contentWrap, isDesktopWeb ? styles.contentWrapDesktop : null]}>
        <View style={styles.panel}>
          <Text style={styles.title}>Capture article</Text>
          <TextInput
            value={captureUrl}
            onChangeText={setCaptureUrl}
            autoCapitalize="none"
            placeholder="https://example.com/article"
            style={styles.input}
            placeholderTextColor={colors.subtleText}
          />
          <TextInput
            value={captureNote}
            onChangeText={setCaptureNote}
            placeholder="Optional note"
            style={styles.input}
            placeholderTextColor={colors.subtleText}
          />
          <Pressable
            disabled={captureMutation.isPending || captureUrl.trim().length === 0}
            onPress={() => {
              setInlineError(null);
              captureMutation.mutate({ url: captureUrl.trim(), note: captureNote.trim() });
            }}
            style={[styles.primaryButton, isDesktopWeb ? styles.desktopPrimaryButton : null]}
          >
            <Text style={styles.primaryButtonText}>
              {captureMutation.isPending ? "Saving..." : "Save article"}
            </Text>
          </Pressable>
        </View>

        {pendingCount > 0 ? (
          <View style={styles.queuePanel}>
            <Text style={styles.queueText}>
              {pendingCount} pending {pendingCount === 1 ? "share" : "shares"}
              {isFlushing ? " • syncing..." : ""}
            </Text>
            <Pressable
              onPress={() => {
                flushNow()
                  .then(() => queryClient.invalidateQueries({ queryKey: listKey }))
                  .catch(() => undefined);
              }}
              style={styles.queueAction}
            >
              <Text style={styles.queueActionLabel}>Sync now</Text>
            </Pressable>
          </View>
        ) : null}

        <ScrollView
          style={styles.listContainer}
          refreshControl={
            <RefreshControl refreshing={listQuery.isRefetching} onRefresh={listQuery.refetch} />
          }
        >
          <View style={styles.filterRow}>
            {FILTERS.map((option) => (
              <Pressable
                key={option.key}
                onPress={() => setFilter(option.key)}
                style={[styles.filterButton, option.key === filter ? styles.filterButtonActive : null]}
              >
                <Text style={styles.filterLabel}>{option.label}</Text>
              </Pressable>
            ))}
          </View>

          {inlineError ? (
            <View style={styles.errorPanel}>
              <Text style={styles.errorText}>{inlineError}</Text>
            </View>
          ) : null}

          {listQuery.isLoading ? (
            <View style={styles.loadingWrap}>
              <ActivityIndicator size="small" color={colors.primary} />
              <Text style={styles.subtle}>Loading articles...</Text>
            </View>
          ) : null}

          {items.map((item) => (
            <Pressable
              key={item.article_id}
              onPress={() => {
                if (!item.article_id.startsWith("article_temp_")) {
                  const scopedPrefix = segments[0] === "app" ? "/app" : "";
                  router.push(`${scopedPrefix}/articles/${item.article_id}`);
                }
              }}
              style={styles.panel}
            >
              <Text style={styles.itemTitle}>{item.title || "Untitled article"}</Text>
              <Text style={styles.subtle}>
                {humanizeStatus(item.status)} • {humanizeReadState(item.read_state)}
              </Text>
              <Text style={styles.url}>{item.canonical_url}</Text>
              <View style={styles.actionRow}>
                <Pressable
                  onPress={() =>
                    readStateMutation.mutate({ articleId: item.article_id, readState: "in_progress" })
                  }
                  disabled={item.article_id.startsWith("article_temp_")}
                  style={[styles.secondaryAction, isDesktopWeb ? styles.desktopInlineAction : null]}
                >
                  <Text style={styles.actionLabel}>In progress</Text>
                </Pressable>
                <Pressable
                  onPress={() => readStateMutation.mutate({ articleId: item.article_id, readState: "read" })}
                  disabled={item.article_id.startsWith("article_temp_")}
                  style={[styles.primaryAction, isDesktopWeb ? styles.desktopInlineAction : null]}
                >
                  <Text style={styles.primaryActionLabel}>Read</Text>
                </Pressable>
              </View>
            </Pressable>
          ))}

          {!listQuery.isLoading && items.length === 0 ? (
            <View style={styles.panel}>
              <Text style={styles.subtle}>No articles for this filter yet.</Text>
            </View>
          ) : null}
        </ScrollView>
      </View>
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
    contentWrap: {
      flex: 1,
    },
    contentWrapDesktop: {
      width: "100%",
      maxWidth: 1040,
      alignSelf: "center",
    },
    panel: {
      backgroundColor: colors.surface,
      borderRadius: 18,
      padding: 12,
      marginBottom: 12,
    },
    title: {
      color: colors.text,
      fontSize: 18,
      fontWeight: "700",
      marginBottom: 8,
    },
    input: {
      borderWidth: 1,
      borderColor: colors.border,
      borderRadius: 12,
      backgroundColor: colors.inputBackground,
      color: colors.text,
      marginBottom: 8,
      paddingHorizontal: 12,
      paddingVertical: 8,
    },
    primaryButton: {
      backgroundColor: colors.primary,
      borderRadius: 12,
      paddingVertical: 10,
      paddingHorizontal: 16,
    },
    desktopPrimaryButton: {
      alignSelf: "flex-start",
      minWidth: 200,
      paddingHorizontal: 24,
    },
    primaryButtonText: {
      color: colors.primaryText,
      textAlign: "center",
      fontWeight: "700",
    },
    listContainer: {
      flex: 1,
    },
    filterRow: {
      flexDirection: "row",
      flexWrap: "wrap",
      gap: 8,
      marginBottom: 12,
    },
    filterButton: {
      borderWidth: 1,
      borderColor: colors.border,
      borderRadius: 999,
      backgroundColor: colors.inputBackground,
      paddingHorizontal: 12,
      paddingVertical: 4,
    },
    filterButtonActive: {
      borderColor: colors.primary,
      backgroundColor: colors.secondarySurface,
    },
    filterLabel: {
      color: colors.text,
      fontSize: 12,
    },
    errorPanel: {
      borderWidth: 1,
      borderColor: colors.errorBorder,
      backgroundColor: colors.errorSurface,
      borderRadius: 12,
      paddingHorizontal: 12,
      paddingVertical: 8,
      marginBottom: 12,
    },
    errorText: {
      color: colors.errorText,
      fontSize: 13,
    },
    queuePanel: {
      borderWidth: 1,
      borderColor: colors.border,
      backgroundColor: colors.secondarySurface,
      borderRadius: 12,
      paddingHorizontal: 12,
      paddingVertical: 8,
      marginBottom: 12,
      flexDirection: "row",
      alignItems: "center",
      justifyContent: "space-between",
      gap: 12,
    },
    queueText: {
      color: colors.accentText,
      fontSize: 13,
    },
    queueAction: {
      borderRadius: 8,
      backgroundColor: colors.inputBackground,
      paddingHorizontal: 10,
      paddingVertical: 6,
    },
    queueActionLabel: {
      color: colors.accentText,
      fontWeight: "700",
      fontSize: 12,
    },
    loadingWrap: {
      alignItems: "center",
      paddingVertical: 20,
      gap: 8,
    },
    itemTitle: {
      color: colors.text,
      fontSize: 16,
      fontWeight: "700",
      marginBottom: 4,
    },
    subtle: {
      color: colors.subtleText,
      fontSize: 12,
    },
    url: {
      color: colors.subtleText,
      fontSize: 12,
      marginTop: 4,
    },
    actionRow: {
      flexDirection: "row",
      gap: 8,
      marginTop: 10,
    },
    secondaryAction: {
      flex: 1,
      borderWidth: 1,
      borderColor: colors.border,
      borderRadius: 10,
      backgroundColor: colors.inputBackground,
      paddingVertical: 6,
    },
    primaryAction: {
      flex: 1,
      borderRadius: 10,
      backgroundColor: colors.primary,
      paddingVertical: 6,
    },
    actionLabel: {
      color: colors.text,
      textAlign: "center",
      fontSize: 12,
    },
    primaryActionLabel: {
      color: colors.primaryText,
      textAlign: "center",
      fontSize: 12,
      fontWeight: "700",
    },
    desktopInlineAction: {
      flex: 0,
      minWidth: 150,
      paddingHorizontal: 16,
    },
  });
}
