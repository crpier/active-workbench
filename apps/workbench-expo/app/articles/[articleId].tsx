import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams } from "expo-router";
import { useMemo } from "react";
import {
  Linking,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from "react-native";
import Markdown from "react-native-markdown-display";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";

import { ApiError } from "@/api/client";
import { useApiClient } from "@/api/hooks";
import type { ArticleReadState, ArticleSummary } from "@/api/types";
import { useActivityContext } from "@/state/activity-context";
import {
  estimateReadProgress,
  humanizeReadState,
  humanizeStatus,
  mergeArticlePatch,
} from "@/utils/articles";
import { useAppTheme } from "@/theme/use-app-theme";

const DESKTOP_BREAKPOINT = 1024;
const WEB_READING_FONT =
  '"Iowan Old Style", "Palatino Linotype", Palatino, "Book Antiqua", Georgia, serif';

export default function ArticleReaderScreen() {
  const params = useLocalSearchParams<{ articleId?: string }>();
  const articleId = params.articleId?.trim() ?? "";
  const { width } = useWindowDimensions();
  const { colors, resolvedTheme } = useAppTheme();
  const styles = useMemo(() => createStyles(colors), [colors]);
  const api = useApiClient();
  const queryClient = useQueryClient();
  const { addEntry } = useActivityContext();
  const isDesktopWeb = Platform.OS === "web" && width >= DESKTOP_BREAKPOINT;

  const readableQuery = useQuery({
    queryKey: ["readable", articleId],
    enabled: articleId.length > 0,
    queryFn: () => api.getReadable(articleId),
  });

  const applyOptimisticPatch = (patch: Partial<ArticleSummary>) => {
    queryClient.setQueryData(["readable", articleId], (current: typeof readableQuery.data) => {
      if (!current) {
        return current;
      }
      return {
        ...current,
        article: mergeArticlePatch(current.article, patch),
      };
    });
  };

  const readMutation = useMutation({
    mutationFn: async (readState: ArticleReadState) =>
      api.markReadState({
        articleId,
        readState,
        progressPercent: estimateReadProgress(readState),
      }),
    onMutate: async (readState) => {
      await queryClient.cancelQueries({ queryKey: ["readable", articleId] });
      const previous = queryClient.getQueryData<typeof readableQuery.data>(["readable", articleId]);
      applyOptimisticPatch({
        read_state: readState,
        progress_percent: estimateReadProgress(readState),
      });
      return { previous };
    },
    onError: async (error, _state, context) => {
      if (context?.previous) {
        queryClient.setQueryData(["readable", articleId], context.previous);
      }
      await addEntry({
        level: "error",
        title: "Reader update failed",
        detail: error instanceof ApiError ? error.message : "Could not update read state.",
      });
    },
    onSuccess: (result) => {
      queryClient.setQueryData(["readable", articleId], (current: typeof readableQuery.data) => {
        if (!current) {
          return current;
        }
        return {
          ...current,
          article: result.article,
        };
      });
    },
  });

  const retryMutation = useMutation({
    mutationFn: () => api.retryArticle(articleId),
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: ["readable", articleId] });
      const previous = queryClient.getQueryData<typeof readableQuery.data>(["readable", articleId]);
      applyOptimisticPatch({ status: "processing" });
      return { previous };
    },
    onError: async (error, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(["readable", articleId], context.previous);
      }
      await addEntry({
        level: "error",
        title: "Retry failed",
        detail: error instanceof ApiError ? error.message : "Could not queue retry.",
      });
    },
    onSuccess: async () => {
      await addEntry({
        level: "info",
        title: "Retry queued",
        detail: articleId,
      });
      await queryClient.invalidateQueries({ queryKey: ["readable", articleId] });
    },
  });

  const readable = readableQuery.data;
  const article = readable?.article;
  const markdown =
    readable?.default_markdown ?? readable?.source_markdown ?? readable?.llm_markdown ?? "";

  const markdownTextStyle = {
    body: {
      color: colors.text,
      fontFamily: "serif",
      fontSize: 19,
      lineHeight: 32,
    },
    paragraph: {
      color: colors.text,
      fontFamily: "serif",
      fontSize: 19,
      lineHeight: 32,
      marginBottom: 16,
    },
    heading1: { color: colors.text, fontFamily: "serif", fontSize: 34, lineHeight: 44 },
    heading2: { color: colors.text, fontFamily: "serif", fontSize: 28, lineHeight: 38 },
    heading3: { color: colors.text, fontFamily: "serif", fontSize: 24, lineHeight: 33 },
    link: { color: colors.primary },
    list_item: {
      color: colors.text,
      fontFamily: "serif",
      fontSize: 19,
      lineHeight: 32,
    },
    code_inline: {
      color: colors.text,
      fontFamily: "monospace",
      fontSize: 17,
    },
    code_block: {
      color: colors.text,
      fontFamily: "monospace",
      fontSize: 16,
      lineHeight: 26,
    },
  };

  const markdownComponents = useMemo<Components>(() => {
    return {
      p: ({ children, ...props }) => (
        <p
          style={{
            color: colors.text,
            fontFamily: WEB_READING_FONT,
            fontSize: "1.2rem",
            lineHeight: 1.75,
            marginBottom: "1rem",
          }}
          {...props}
        >
          {children}
        </p>
      ),
      h1: ({ children, ...props }) => (
        <h1
          style={{
            color: colors.text,
            fontFamily: WEB_READING_FONT,
            fontSize: "2.4rem",
            lineHeight: 1.2,
            marginTop: "0.6rem",
            marginBottom: "1rem",
          }}
          {...props}
        >
          {children}
        </h1>
      ),
      h2: ({ children, ...props }) => (
        <h2
          style={{
            color: colors.text,
            fontFamily: WEB_READING_FONT,
            fontSize: "2rem",
            lineHeight: 1.25,
            marginTop: "0.5rem",
            marginBottom: "0.9rem",
          }}
          {...props}
        >
          {children}
        </h2>
      ),
      h3: ({ children, ...props }) => (
        <h3
          style={{
            color: colors.text,
            fontFamily: WEB_READING_FONT,
            fontSize: "1.6rem",
            lineHeight: 1.3,
            marginTop: "0.4rem",
            marginBottom: "0.8rem",
          }}
          {...props}
        >
          {children}
        </h3>
      ),
      li: ({ children, ...props }) => (
        <li
          style={{
            color: colors.text,
            fontFamily: WEB_READING_FONT,
            fontSize: "1.2rem",
            lineHeight: 1.75,
            marginBottom: "0.35rem",
          }}
          {...props}
        >
          {children}
        </li>
      ),
      a: ({ children, ...props }) => (
        <a style={{ color: colors.primary }} {...props}>
          {children}
        </a>
      ),
      strong: ({ children, ...props }) => (
        <strong style={{ color: colors.text, fontWeight: 700 }} {...props}>
          {children}
        </strong>
      ),
      code: ({ children, ...props }) => (
        <code style={{ color: colors.text, fontSize: "1.05rem" }} {...props}>
          {children}
        </code>
      ),
    };
  }, [colors.primary, colors.text]);

  const contentBody = (
    <>
      {readableQuery.isLoading ? <Text style={styles.subtle}>Loading readable content...</Text> : null}
      {!readableQuery.isLoading && markdown.length === 0 ? (
        <Text style={styles.subtle}>Readable content is not ready yet.</Text>
      ) : null}
      {markdown.length > 0 && Platform.OS === "web" ? (
        <View>
          <ReactMarkdown
            components={markdownComponents}
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeSanitize]}
          >
            {markdown}
          </ReactMarkdown>
        </View>
      ) : null}
      {markdown.length > 0 && Platform.OS !== "web" ? <Markdown style={markdownTextStyle}>{markdown}</Markdown> : null}
    </>
  );

  const desktopActions = (
    <View
      style={[
        styles.actionsPanel,
        styles.actionsPanelDesktop,
        Platform.OS === "web" ? ({ position: "sticky", top: 12 } as object) : null,
      ]}
    >
      <Text style={styles.actionsHeading}>Actions</Text>
      <Pressable
        style={[styles.secondaryAction, styles.sidebarAction]}
        onPress={() => {
          if (article?.canonical_url) {
            Linking.openURL(article.canonical_url).catch(() => undefined);
          }
        }}
      >
        <Text style={styles.actionLabel}>Open original</Text>
      </Pressable>
      <Pressable style={[styles.secondaryAction, styles.sidebarAction]} onPress={() => readableQuery.refetch()}>
        <Text style={styles.actionLabel}>Refresh</Text>
      </Pressable>
      <Pressable
        style={[styles.secondaryAction, styles.sidebarAction]}
        onPress={() => readMutation.mutate("in_progress")}
      >
        <Text style={styles.actionLabel}>Mark in progress</Text>
      </Pressable>
      <Pressable style={[styles.retryAction, styles.sidebarAction]} onPress={() => retryMutation.mutate()}>
        <Text style={styles.actionLabel}>Retry extraction</Text>
      </Pressable>
      <Pressable style={[styles.primaryAction, styles.sidebarAction]} onPress={() => readMutation.mutate("read")}>
        <Text style={styles.primaryActionLabel}>Mark read</Text>
      </Pressable>
    </View>
  );

  const mobileActions = (
    <View style={styles.actionsPanel}>
      <View style={styles.actionRow}>
        <Pressable
          style={styles.secondaryAction}
          onPress={() => {
            if (article?.canonical_url) {
              Linking.openURL(article.canonical_url).catch(() => undefined);
            }
          }}
        >
          <Text style={styles.actionLabel}>Open original</Text>
        </Pressable>
        <Pressable style={styles.secondaryAction} onPress={() => readableQuery.refetch()}>
          <Text style={styles.actionLabel}>Refresh</Text>
        </Pressable>
      </View>

      <View style={styles.actionRow}>
        <Pressable style={styles.secondaryAction} onPress={() => readMutation.mutate("in_progress")}>
          <Text style={styles.actionLabel}>Mark in progress</Text>
        </Pressable>
        <Pressable style={styles.primaryAction} onPress={() => readMutation.mutate("read")}>
          <Text style={styles.primaryActionLabel}>Mark read</Text>
        </Pressable>
      </View>

      <Pressable style={styles.retryAction} onPress={() => retryMutation.mutate()}>
        <Text style={styles.actionLabel}>Retry extraction</Text>
      </Pressable>
    </View>
  );

  if (isDesktopWeb) {
    return (
      <ScrollView style={styles.screen} contentContainerStyle={styles.desktopScrollContent}>
        <View style={[styles.contentWrap, styles.contentWrapDesktop]}>
          <View style={styles.headerPanel}>
            <Text style={styles.title}>{article?.title || "Article"}</Text>
            {article ? (
              <Text style={styles.subtle}>
                {humanizeStatus(article.status)} • {humanizeReadState(article.read_state)}
              </Text>
            ) : null}
          </View>

          <View style={styles.desktopBody}>
            <View style={styles.desktopArticleColumn}>
            <View style={[styles.contentPanel, styles.contentPanelDesktop]}>{contentBody}</View>
            </View>
            <View style={styles.desktopSidebar}>{desktopActions}</View>
          </View>
        </View>
      </ScrollView>
    );
  }

  return (
    <View style={[styles.screen, styles.screenContentPadding]}>
      <View style={styles.contentWrap}>
        <View style={styles.headerPanel}>
          <Text style={styles.title}>{article?.title || "Article"}</Text>
          {article ? (
            <Text style={styles.subtle}>
              {humanizeStatus(article.status)} • {humanizeReadState(article.read_state)}
            </Text>
          ) : null}
        </View>

        <ScrollView style={styles.contentPanel}>{contentBody}</ScrollView>
        {mobileActions}
      </View>
    </View>
  );
}

function createStyles(colors: ReturnType<typeof useAppTheme>["colors"]) {
  return StyleSheet.create({
    screen: {
      flex: 1,
      backgroundColor: colors.background,
    },
    screenContentPadding: {
      paddingHorizontal: 16,
      paddingVertical: 12,
    },
    desktopScrollContent: {
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
    desktopBody: {
      flexDirection: "row",
      alignItems: "flex-start",
      gap: 16,
    },
    desktopArticleColumn: {
      flex: 1,
      minWidth: 0,
    },
    desktopSidebar: {
      width: 280,
      alignSelf: "stretch",
    },
    headerPanel: {
      backgroundColor: colors.surface,
      borderRadius: 18,
      padding: 12,
      marginBottom: 12,
    },
    title: {
      color: colors.text,
      fontSize: 20,
      fontWeight: "700",
    },
    subtle: {
      color: colors.subtleText,
      fontSize: 12,
      marginTop: 4,
    },
    contentPanel: {
      flex: 1,
      backgroundColor: colors.surface,
      borderRadius: 18,
      paddingHorizontal: 12,
      paddingVertical: 10,
    },
    contentPanelDesktop: {
      flex: 0,
    },
    actionsPanel: {
      marginTop: 12,
      backgroundColor: colors.surface,
      borderRadius: 18,
      padding: 12,
      gap: 8,
    },
    actionsPanelDesktop: {
      marginTop: 0,
      borderWidth: 1,
      borderColor: colors.border,
      gap: 10,
    },
    actionsHeading: {
      color: colors.subtleText,
      fontSize: 11,
      fontWeight: "700",
      textTransform: "uppercase",
      letterSpacing: 0.3,
      marginBottom: 2,
    },
    actionRow: {
      flexDirection: "row",
      gap: 8,
    },
    actionRowDesktop: {
      flexDirection: "column",
    },
    secondaryAction: {
      flex: 1,
      borderWidth: 1,
      borderColor: colors.border,
      borderRadius: 10,
      backgroundColor: colors.inputBackground,
      paddingVertical: 10,
    },
    primaryAction: {
      flex: 1,
      borderRadius: 10,
      backgroundColor: colors.primary,
      paddingVertical: 10,
    },
    retryAction: {
      borderWidth: 1,
      borderColor: colors.border,
      borderRadius: 10,
      backgroundColor: colors.inputBackground,
      paddingVertical: 10,
    },
    sidebarAction: {
      flex: 0,
      width: "100%",
      minHeight: 42,
      justifyContent: "center",
      paddingHorizontal: 14,
    },
    actionLabel: {
      color: colors.text,
      textAlign: "center",
      fontSize: 13,
    },
    primaryActionLabel: {
      color: colors.primaryText,
      textAlign: "center",
      fontSize: 13,
      fontWeight: "700",
    },
  });
}
