// @ts-nocheck
/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ArticleCaptureRequest } from '../models/ArticleCaptureRequest';
import type { ArticleCaptureResponse } from '../models/ArticleCaptureResponse';
import type { ArticleDeleteResponse } from '../models/ArticleDeleteResponse';
import type { ArticleListResponse } from '../models/ArticleListResponse';
import type { ArticleReadableResponse } from '../models/ArticleReadableResponse';
import type { ArticleReadStateUpdateRequest } from '../models/ArticleReadStateUpdateRequest';
import type { ArticleReadStateUpdateResponse } from '../models/ArticleReadStateUpdateResponse';
import type { ArticleRetryResponse } from '../models/ArticleRetryResponse';
import type { ArticleSummary } from '../models/ArticleSummary';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class ArticlesService {
    /**
     * Article Capture
     * @param requestBody
     * @returns ArticleCaptureResponse Successful Response
     * @throws ApiError
     */
    public static articleCapture(
        requestBody: ArticleCaptureRequest,
    ): CancelablePromise<ArticleCaptureResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/articles/capture',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Article List
     * @param status
     * @param readState
     * @param domainHost
     * @param limit
     * @param cursor
     * @returns ArticleListResponse Successful Response
     * @throws ApiError
     */
    public static articleList(
        status?: (string | null),
        readState?: (string | null),
        domainHost?: (string | null),
        limit: number = 30,
        cursor?: number,
    ): CancelablePromise<ArticleListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/articles',
            query: {
                'status': status,
                'read_state': readState,
                'domain_host': domainHost,
                'limit': limit,
                'cursor': cursor,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Article Get
     * @param articleId
     * @returns ArticleSummary Successful Response
     * @throws ApiError
     */
    public static articleGet(
        articleId: string,
    ): CancelablePromise<ArticleSummary> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/articles/{article_id}',
            path: {
                'article_id': articleId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Article Delete
     * @param articleId
     * @returns ArticleDeleteResponse Successful Response
     * @throws ApiError
     */
    public static articleDelete(
        articleId: string,
    ): CancelablePromise<ArticleDeleteResponse> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/articles/{article_id}',
            path: {
                'article_id': articleId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Article Readable Get
     * @param articleId
     * @returns ArticleReadableResponse Successful Response
     * @throws ApiError
     */
    public static articleReadableGet(
        articleId: string,
    ): CancelablePromise<ArticleReadableResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/articles/{article_id}/readable',
            path: {
                'article_id': articleId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Article Retry
     * @param articleId
     * @returns ArticleRetryResponse Successful Response
     * @throws ApiError
     */
    public static articleRetry(
        articleId: string,
    ): CancelablePromise<ArticleRetryResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/articles/{article_id}/retry',
            path: {
                'article_id': articleId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Article Read State Update
     * @param articleId
     * @param requestBody
     * @returns ArticleReadStateUpdateResponse Successful Response
     * @throws ApiError
     */
    public static articleReadStateUpdate(
        articleId: string,
        requestBody: ArticleReadStateUpdateRequest,
    ): CancelablePromise<ArticleReadStateUpdateResponse> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/articles/{article_id}/read-state',
            path: {
                'article_id': articleId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
