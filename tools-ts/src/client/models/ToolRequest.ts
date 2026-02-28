// @ts-nocheck
/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ToolContext } from './ToolContext';
export type ToolRequest = {
    tool: 'youtube.likes.list_recent' | 'youtube.likes.search_recent_content' | 'youtube.watch_later.list' | 'youtube.watch_later.search_content' | 'youtube.watch_later.recommend' | 'youtube.transcript.get' | 'bucket.item.add' | 'bucket.item.update' | 'bucket.item.complete' | 'bucket.item.search' | 'bucket.item.recommend' | 'bucket.health.report' | 'memory.create' | 'memory.list' | 'memory.search' | 'memory.delete' | 'memory.undo';
    request_id: string;
    idempotency_key?: (string | null);
    payload?: Record<string, any>;
    context?: ToolContext;
};

