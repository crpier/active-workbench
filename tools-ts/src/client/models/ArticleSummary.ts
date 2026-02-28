// @ts-nocheck
/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type ArticleSummary = {
    article_id: string;
    bucket_item_id: string;
    source_url: string;
    canonical_url: string;
    title?: (string | null);
    author?: (string | null);
    site_name?: (string | null);
    published_at?: (string | null);
    status: 'captured' | 'processing' | 'readable' | 'failed';
    read_state: 'unread' | 'in_progress' | 'read';
    estimated_read_minutes?: (number | null);
    progress_percent: number;
    extraction_method?: (string | null);
    llm_polished: boolean;
    captured_at: string;
    updated_at: string;
    last_error_code?: (string | null);
    last_error_message?: (string | null);
};

