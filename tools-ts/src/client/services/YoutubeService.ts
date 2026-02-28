// @ts-nocheck
/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { WatchLaterSnapshotPushRequest } from '../models/WatchLaterSnapshotPushRequest';
import type { WatchLaterSnapshotPushResponse } from '../models/WatchLaterSnapshotPushResponse';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class YoutubeService {
    /**
     * Youtube Watch Later Snapshot Push
     * @param requestBody
     * @returns WatchLaterSnapshotPushResponse Successful Response
     * @throws ApiError
     */
    public static youtubeWatchLaterSnapshotPush(
        requestBody: WatchLaterSnapshotPushRequest,
    ): CancelablePromise<WatchLaterSnapshotPushResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/youtube/watch-later/snapshot',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
