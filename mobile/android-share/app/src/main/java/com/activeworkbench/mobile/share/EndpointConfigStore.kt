package com.activeworkbench.mobile.share

import android.content.Context
import android.net.Uri

class EndpointConfigStore(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun getBackendBaseUrl(): String {
        val stored = prefs.getString(KEY_BACKEND_BASE_URL, null)
        val normalized = stored?.trim()
        if (isValidHttpUrl(normalized)) {
            return normalized.orEmpty()
        }
        return BuildConfig.WORKBENCH_BASE_URL
    }

    fun getOpencodeWebUrl(): String {
        val stored = prefs.getString(KEY_OPENCODE_WEB_URL, null)
        val normalized = stored?.trim()
        if (isValidHttpUrl(normalized)) {
            return normalized.orEmpty()
        }
        return BuildConfig.OPENCODE_WEB_URL
    }

    fun saveUrls(backendBaseUrl: String, opencodeWebUrl: String): SaveResult {
        if (!isValidHttpUrl(backendBaseUrl)) {
            return SaveResult.InvalidBackendUrl
        }
        if (!isValidHttpUrl(opencodeWebUrl)) {
            return SaveResult.InvalidOpenCodeUrl
        }

        prefs.edit()
            .putString(KEY_BACKEND_BASE_URL, backendBaseUrl.trim())
            .putString(KEY_OPENCODE_WEB_URL, opencodeWebUrl.trim())
            .apply()
        return SaveResult.Saved
    }

    private fun isValidHttpUrl(value: String?): Boolean {
        if (value.isNullOrBlank()) {
            return false
        }
        val parsed = try {
            Uri.parse(value.trim())
        } catch (_: Exception) {
            return false
        }

        val scheme = parsed.scheme?.lowercase()
        return (scheme == "http" || scheme == "https") && !parsed.host.isNullOrBlank()
    }

    companion object {
        private const val PREFS_NAME = "active_workbench_endpoint_config"
        private const val KEY_BACKEND_BASE_URL = "backend_base_url"
        private const val KEY_OPENCODE_WEB_URL = "opencode_web_url"
    }
}

sealed interface SaveResult {
    data object Saved : SaveResult
    data object InvalidBackendUrl : SaveResult
    data object InvalidOpenCodeUrl : SaveResult
}
