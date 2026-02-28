import type {
  ArticleCaptureResponse,
  ArticleListResponse,
  ArticleReadableResponse,
  ArticleReadState,
  ArticleReadStateUpdateResponse,
  ArticleRetryResponse,
} from "./types";

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export interface ApiClientOptions {
  baseUrl: string;
  mobileApiKey: string;
}

export class ApiClient {
  private readonly baseUrl: string;
  private readonly mobileApiKey: string;

  constructor(options: ApiClientOptions) {
    this.baseUrl = normalizeBaseUrl(options.baseUrl);
    this.mobileApiKey = options.mobileApiKey.trim();
  }

  async listArticles(readState: ArticleReadState | "all"): Promise<ArticleListResponse> {
    const search = new URLSearchParams();
    search.set("limit", "100");
    if (readState !== "all") {
      search.set("read_state", readState);
    }
    return this.request<ArticleListResponse>(`/articles?${search.toString()}`);
  }

  async getReadable(articleId: string): Promise<ArticleReadableResponse> {
    return this.request<ArticleReadableResponse>(`/articles/${encodeURIComponent(articleId)}/readable`);
  }

  async captureArticle(params: {
    url: string;
    sharedText?: string;
    processNow?: boolean;
  }): Promise<ArticleCaptureResponse> {
    return this.request<ArticleCaptureResponse>("/articles/capture", {
      method: "POST",
      body: JSON.stringify({
        url: params.url,
        source: "expo_app",
        shared_text: params.sharedText ?? null,
        process_now: params.processNow ?? true,
      }),
      headers: {
        "Content-Type": "application/json",
      },
    });
  }

  async markReadState(params: {
    articleId: string;
    readState: ArticleReadState;
    progressPercent: number;
  }): Promise<ArticleReadStateUpdateResponse> {
    return this.request<ArticleReadStateUpdateResponse>(
      `/articles/${encodeURIComponent(params.articleId)}/read-state`,
      {
        method: "PATCH",
        body: JSON.stringify({
          read_state: params.readState,
          progress_percent: params.progressPercent,
        }),
        headers: {
          "Content-Type": "application/json",
        },
      },
    );
  }

  async retryArticle(articleId: string): Promise<ArticleRetryResponse> {
    return this.request<ArticleRetryResponse>(`/articles/${encodeURIComponent(articleId)}/retry`, {
      method: "POST",
    });
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const headers = new Headers(init?.headers ?? {});
    if (this.mobileApiKey) {
      headers.set("Authorization", `Bearer ${this.mobileApiKey}`);
    }
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers,
    });

    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = null;
    }

    if (!response.ok) {
      const detail =
        typeof body === "object" && body !== null && "detail" in body
          ? String((body as { detail: unknown }).detail)
          : `Request failed (${response.status})`;
      throw new ApiError(detail, response.status);
    }

    return body as T;
  }
}

export function normalizeBaseUrl(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return defaultBackendBaseUrl();
  }
  return trimmed.endsWith("/") ? trimmed.slice(0, -1) : trimmed;
}

export function defaultBackendBaseUrl(): string {
  if (typeof window !== "undefined" && window.location?.origin) {
    return window.location.origin;
  }
  return "http://10.0.2.2:8000";
}
