// @ts-nocheck
/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ToolError } from './ToolError';
export type ShareArticleResponse = {
    status: 'saved' | 'already_exists' | 'needs_clarification' | 'failed';
    request_id: string;
    backend_status?: (string | null);
    article_id?: (string | null);
    article_status?: ('captured' | 'processing' | 'readable' | 'failed' | null);
    readable_available?: boolean;
    bucket_item_id?: (string | null);
    title?: (string | null);
    canonical_url?: (string | null);
    message?: (string | null);
    candidates?: Array<Record<string, any>>;
    error?: (ToolError | null);
};

