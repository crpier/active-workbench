// @ts-nocheck
/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ShareArticleRequest } from '../models/ShareArticleRequest';
import type { ShareArticleResponse } from '../models/ShareArticleResponse';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class MobileService {
    /**
     * Mobile Share Article
     * @param requestBody
     * @returns ShareArticleResponse Successful Response
     * @throws ApiError
     */
    public static mobileShareArticle(
        requestBody: ShareArticleRequest,
    ): CancelablePromise<ShareArticleResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/mobile/v1/share/article',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
