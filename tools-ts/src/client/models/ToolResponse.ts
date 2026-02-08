// @ts-nocheck
/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ProvenanceRef } from './ProvenanceRef';
import type { ToolError } from './ToolError';
export type ToolResponse = {
    ok: boolean;
    request_id: string;
    result?: Record<string, any>;
    provenance?: Array<ProvenanceRef>;
    audit_event_id?: (string | null);
    undo_token?: (string | null);
    error?: (ToolError | null);
};

