// @ts-nocheck
/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ArticleSummary } from './ArticleSummary';
export type ArticleListResponse = {
    count: number;
    items: Array<ArticleSummary>;
    cursor: number;
    next_cursor?: (number | null);
};

