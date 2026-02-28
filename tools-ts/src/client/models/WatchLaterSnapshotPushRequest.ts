// @ts-nocheck
/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { WatchLaterSnapshotVideo } from './WatchLaterSnapshotVideo';
export type WatchLaterSnapshotPushRequest = {
    generated_at_utc?: (string | null);
    source_client?: string;
    videos?: Array<WatchLaterSnapshotVideo>;
    allow_empty_snapshot?: boolean;
};

