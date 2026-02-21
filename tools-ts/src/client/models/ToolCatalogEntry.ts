// @ts-nocheck
/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type ToolCatalogEntry = {
    name: 'youtube.likes.list_recent' | 'youtube.likes.search_recent_content' | 'youtube.transcript.get' | 'vault.recipe.save' | 'vault.note.save' | 'bucket.item.add' | 'bucket.item.update' | 'bucket.item.complete' | 'bucket.item.search' | 'bucket.item.recommend' | 'bucket.health.report' | 'memory.create' | 'memory.undo' | 'reminder.schedule' | 'context.suggest_for_query' | 'digest.weekly_learning.generate' | 'review.routine.generate' | 'recipe.extract_from_transcript' | 'summary.extract_key_ideas' | 'actions.extract_from_notes';
    description: string;
    write_operation: boolean;
    ready_for_use: boolean;
    readiness_note?: (string | null);
};

