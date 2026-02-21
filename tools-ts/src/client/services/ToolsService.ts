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
     * Youtube Likes List Recent
     * @param requestBody
     * @returns ToolResponse Successful Response
     * @throws ApiError
     */
    public static youtubeLikesListRecent(
        requestBody: ToolRequest,
    ): CancelablePromise<ToolResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/tools/youtube.likes.list_recent',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Youtube Likes Search Recent Content
     * @param requestBody
     * @returns ToolResponse Successful Response
     * @throws ApiError
     */
    public static youtubeLikesSearchRecentContent(
        requestBody: ToolRequest,
    ): CancelablePromise<ToolResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/tools/youtube.likes.search_recent_content',
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
     * Bucket Item Add
     * @param requestBody
     * @returns ToolResponse Successful Response
     * @throws ApiError
     */
    public static bucketItemAdd(
        requestBody: ToolRequest,
    ): CancelablePromise<ToolResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/tools/bucket.item.add',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Bucket Item Update
     * @param requestBody
     * @returns ToolResponse Successful Response
     * @throws ApiError
     */
    public static bucketItemUpdate(
        requestBody: ToolRequest,
    ): CancelablePromise<ToolResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/tools/bucket.item.update',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Bucket Item Complete
     * @param requestBody
     * @returns ToolResponse Successful Response
     * @throws ApiError
     */
    public static bucketItemComplete(
        requestBody: ToolRequest,
    ): CancelablePromise<ToolResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/tools/bucket.item.complete',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Bucket Item Search
     * @param requestBody
     * @returns ToolResponse Successful Response
     * @throws ApiError
     */
    public static bucketItemSearch(
        requestBody: ToolRequest,
    ): CancelablePromise<ToolResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/tools/bucket.item.search',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Bucket Item Recommend
     * @param requestBody
     * @returns ToolResponse Successful Response
     * @throws ApiError
     */
    public static bucketItemRecommend(
        requestBody: ToolRequest,
    ): CancelablePromise<ToolResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/tools/bucket.item.recommend',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Bucket Health Report
     * @param requestBody
     * @returns ToolResponse Successful Response
     * @throws ApiError
     */
    public static bucketHealthReport(
        requestBody: ToolRequest,
    ): CancelablePromise<ToolResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/tools/bucket.health.report',
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
     * Memory List
     * @param requestBody
     * @returns ToolResponse Successful Response
     * @throws ApiError
     */
    public static memoryList(
        requestBody: ToolRequest,
    ): CancelablePromise<ToolResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/tools/memory.list',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Memory Search
     * @param requestBody
     * @returns ToolResponse Successful Response
     * @throws ApiError
     */
    public static memorySearch(
        requestBody: ToolRequest,
    ): CancelablePromise<ToolResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/tools/memory.search',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Memory Delete
     * @param requestBody
     * @returns ToolResponse Successful Response
     * @throws ApiError
     */
    public static memoryDelete(
        requestBody: ToolRequest,
    ): CancelablePromise<ToolResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/tools/memory.delete',
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
}
