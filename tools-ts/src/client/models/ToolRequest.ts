// @ts-nocheck
/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ToolContext } from './ToolContext';
export type ToolRequest = {
    tool: 'youtube.likes.list_recent' | 'youtube.transcript.get' | 'vault.recipe.save' | 'vault.note.save' | 'vault.bucket_list.add' | 'vault.bucket_list.prioritize' | 'memory.create' | 'memory.undo' | 'reminder.schedule' | 'context.suggest_for_query' | 'digest.weekly_learning.generate' | 'review.routine.generate' | 'recipe.extract_from_transcript' | 'summary.extract_key_ideas' | 'actions.extract_from_notes';
    request_id: string;
    idempotency_key?: (string | null);
    payload?: Record<string, any>;
    context?: ToolContext;
};

