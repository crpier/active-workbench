// @ts-nocheck
/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ToolCatalogEntry } from '../models/ToolCatalogEntry';
import type { ToolRequest } from '../models/ToolRequest';
import type { ToolResponse } from '../models/ToolResponse';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class ToolsService {
    /**
     * List Tools
     * @returns ToolCatalogEntry Successful Response
     * @throws ApiError
     */
    public static listTools(): CancelablePromise<Array<ToolCatalogEntry>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/tools',
        });
    }
    /**
     * Youtube History List Recent
     * @param requestBody
     * @returns ToolResponse Successful Response
     * @throws ApiError
     */
    public static youtubeHistoryListRecent(
        requestBody: ToolRequest,
    ): CancelablePromise<ToolResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/tools/youtube.history.list_recent',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Youtube Transcript Get
     * @param requestBody
     * @returns ToolResponse Successful Response
     * @throws ApiError
     */
    public static youtubeTranscriptGet(
        requestBody: ToolRequest,
    ): CancelablePromise<ToolResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/tools/youtube.transcript.get',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Vault Recipe Save
     * @param requestBody
     * @returns ToolResponse Successful Response
     * @throws ApiError
     */
    public static vaultRecipeSave(
        requestBody: ToolRequest,
    ): CancelablePromise<ToolResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/tools/vault.recipe.save',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Vault Note Save
     * @param requestBody
     * @returns ToolResponse Successful Response
     * @throws ApiError
     */
    public static vaultNoteSave(
        requestBody: ToolRequest,
    ): CancelablePromise<ToolResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/tools/vault.note.save',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Vault Bucket List Add
     * @param requestBody
     * @returns ToolResponse Successful Response
     * @throws ApiError
     */
    public static vaultBucketListAdd(
        requestBody: ToolRequest,
    ): CancelablePromise<ToolResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/tools/vault.bucket_list.add',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Memory Create
     * @param requestBody
     * @returns ToolResponse Successful Response
     * @throws ApiError
     */
    public static memoryCreate(
        requestBody: ToolRequest,
    ): CancelablePromise<ToolResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/tools/memory.create',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Memory Undo
     * @param requestBody
     * @returns ToolResponse Successful Response
     * @throws ApiError
     */
    public static memoryUndo(
        requestBody: ToolRequest,
    ): CancelablePromise<ToolResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/tools/memory.undo',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Reminder Schedule
     * @param requestBody
     * @returns ToolResponse Successful Response
     * @throws ApiError
     */
    public static reminderSchedule(
        requestBody: ToolRequest,
    ): CancelablePromise<ToolResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/tools/reminder.schedule',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Context Suggest For Query
     * @param requestBody
     * @returns ToolResponse Successful Response
     * @throws ApiError
     */
    public static contextSuggestForQuery(
        requestBody: ToolRequest,
    ): CancelablePromise<ToolResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/tools/context.suggest_for_query',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Digest Weekly Learning Generate
     * @param requestBody
     * @returns ToolResponse Successful Response
     * @throws ApiError
     */
    public static digestWeeklyLearningGenerate(
        requestBody: ToolRequest,
    ): CancelablePromise<ToolResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/tools/digest.weekly_learning.generate',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Review Routine Generate
     * @param requestBody
     * @returns ToolResponse Successful Response
     * @throws ApiError
     */
    public static reviewRoutineGenerate(
        requestBody: ToolRequest,
    ): CancelablePromise<ToolResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/tools/review.routine.generate',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Recipe Extract From Transcript
     * @param requestBody
     * @returns ToolResponse Successful Response
     * @throws ApiError
     */
    public static recipeExtractFromTranscript(
        requestBody: ToolRequest,
    ): CancelablePromise<ToolResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/tools/recipe.extract_from_transcript',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Summary Extract Key Ideas
     * @param requestBody
     * @returns ToolResponse Successful Response
     * @throws ApiError
     */
    public static summaryExtractKeyIdeas(
        requestBody: ToolRequest,
    ): CancelablePromise<ToolResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/tools/summary.extract_key_ideas',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Actions Extract From Notes
     * @param requestBody
     * @returns ToolResponse Successful Response
     * @throws ApiError
     */
    public static actionsExtractFromNotes(
        requestBody: ToolRequest,
    ): CancelablePromise<ToolResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/tools/actions.extract_from_notes',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
