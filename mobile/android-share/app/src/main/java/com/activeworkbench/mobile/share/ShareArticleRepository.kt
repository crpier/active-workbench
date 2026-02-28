package com.activeworkbench.mobile.share

import java.io.IOException
import java.util.TimeZone
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

sealed interface ShareSubmissionResult {
    data class Success(val response: ShareArticleResponse) : ShareSubmissionResult
    data class Failure(val message: String, val canRetry: Boolean) : ShareSubmissionResult
}

class ShareArticleRepository(
    private val api: WorkbenchApi,
    private val mobileApiKey: String?,
) {
    suspend fun submit(
        url: String,
        sharedText: String?,
        sourceApp: String?,
    ): ShareSubmissionResult {
        return try {
            val response = api.shareArticle(
                authorization = WorkbenchApiFactory.toAuthorizationHeader(mobileApiKey),
                request = ShareArticleRequest(
                    url = url,
                    sharedText = sharedText,
                    sourceApp = sourceApp,
                    timezone = TimeZone.getDefault().id,
                ),
            )
            if (response.status == "failed") {
                ShareSubmissionResult.Failure(
                    message = response.message ?: response.error?.message ?: "Share failed.",
                    canRetry = response.error?.retryable ?: false,
                )
            } else {
                ShareSubmissionResult.Success(response)
            }
        } catch (exception: CancellationException) {
            throw exception
        } catch (exception: HttpException) {
            when (exception.code()) {
                401 -> ShareSubmissionResult.Failure(
                    message = "Unauthorized. Check the mobile API key in app settings.",
                    canRetry = false,
                )
                429 -> ShareSubmissionResult.Failure(
                    message = "Rate limit reached. The app will retry automatically.",
                    canRetry = true,
                )
                else -> ShareSubmissionResult.Failure(
                    message = "Server error (${exception.code()}) while saving the article.",
                    canRetry = exception.code() >= 500,
                )
            }
        } catch (_: IOException) {
            ShareSubmissionResult.Failure(
                message = "Network error while contacting Active Workbench.",
                canRetry = true,
            )
        } catch (_: Exception) {
            ShareSubmissionResult.Failure(
                message = "Unexpected error while saving the article.",
                canRetry = true,
            )
        }
    }
}
