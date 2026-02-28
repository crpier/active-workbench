export type ArticleStatus = "captured" | "processing" | "readable" | "failed";
export type ArticleReadState = "unread" | "in_progress" | "read";
export type ThemeMode = "light" | "dark" | "system";

export interface ArticleSummary {
  article_id: string;
  bucket_item_id: string;
  source_url: string;
  canonical_url: string;
  title: string | null;
  author: string | null;
  site_name: string | null;
  published_at: string | null;
  status: ArticleStatus;
  read_state: ArticleReadState;
  estimated_read_minutes: number | null;
  progress_percent: number;
  extraction_method: string | null;
  llm_polished: boolean;
  captured_at: string;
  updated_at: string;
  last_error_code: string | null;
  last_error_message: string | null;
}

export interface ArticleListResponse {
  count: number;
  items: ArticleSummary[];
  cursor: number;
  next_cursor: number | null;
}

export interface ArticleReadableResponse {
  article: ArticleSummary;
  source_markdown: string | null;
  llm_markdown: string | null;
  default_markdown: string | null;
}

export interface ArticleCaptureResponse {
  status: "saved" | "already_exists" | "failed";
  request_id: string;
  backend_status: string | null;
  article_id: string | null;
  article_status: ArticleStatus | null;
  readable_available: boolean;
  bucket_item_id: string | null;
  title: string | null;
  canonical_url: string | null;
  message: string | null;
}

export interface ArticleReadStateUpdateResponse {
  status: "updated";
  article: ArticleSummary;
}

export interface ArticleRetryResponse {
  status: "queued";
  article_id: string;
  article_status: ArticleStatus;
}

export interface AppSettings {
  backendBaseUrl: string;
  chatBaseUrl: string;
  mobileApiKey: string;
  themeMode: ThemeMode;
}

export interface ActivityEntry {
  id: string;
  createdAt: string;
  level: "info" | "error";
  title: string;
  detail: string;
}
