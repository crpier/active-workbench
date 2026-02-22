package com.activeworkbench.mobile.share

import com.squareup.moshi.Json

data class ShareArticleRequest(
    @Json(name = "url")
    val url: String,
    @Json(name = "shared_text")
    val sharedText: String? = null,
    @Json(name = "source_app")
    val sourceApp: String? = null,
    @Json(name = "timezone")
    val timezone: String? = null,
)

data class ShareArticleResponse(
    @Json(name = "status")
    val status: String,
    @Json(name = "request_id")
    val requestId: String,
    @Json(name = "backend_status")
    val backendStatus: String? = null,
    @Json(name = "bucket_item_id")
    val bucketItemId: String? = null,
    @Json(name = "title")
    val title: String? = null,
    @Json(name = "canonical_url")
    val canonicalUrl: String? = null,
    @Json(name = "message")
    val message: String? = null,
    @Json(name = "candidates")
    val candidates: List<Map<String, Any?>> = emptyList(),
    @Json(name = "error")
    val error: ToolError? = null,
)

data class ToolError(
    @Json(name = "code")
    val code: String,
    @Json(name = "message")
    val message: String,
    @Json(name = "retryable")
    val retryable: Boolean = false,
)
