package com.activeworkbench.mobile.share

import android.content.Context
import android.content.SharedPreferences
import android.net.Uri
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

class EndpointConfigStore(context: Context) {
    private val plainPrefs = context.applicationContext.getSharedPreferences(
        PREFS_NAME,
        Context.MODE_PRIVATE,
    )
    private val securePrefs: SharedPreferences = createSecurePrefs(context.applicationContext)

    init {
        migrateLegacyApiKeyIfNeeded()
    }

    fun getBackendBaseUrl(): String {
        val stored = plainPrefs.getString(KEY_BACKEND_BASE_URL, null)
        val normalized = stored?.trim()
        if (isValidHttpUrl(normalized)) {
            return normalized.orEmpty()
        }
        return BuildConfig.WORKBENCH_BASE_URL
    }

    fun getOpencodeWebUrl(): String {
        val stored = plainPrefs.getString(KEY_OPENCODE_WEB_URL, null)
        val normalized = stored?.trim()
        if (isValidHttpUrl(normalized)) {
            return normalized.orEmpty()
        }
        return BuildConfig.OPENCODE_WEB_URL
    }

    fun getMobileApiKey(): String? {
        val stored = securePrefs.getString(KEY_MOBILE_API_KEY, null)
        val normalizedStored = stored?.trim()
        if (!normalizedStored.isNullOrEmpty()) {
            return normalizedStored
        }
        val defaultKey = BuildConfig.WORKBENCH_MOBILE_API_KEY.trim()
        return defaultKey.ifEmpty { null }
    }

    fun saveConfig(backendBaseUrl: String, opencodeWebUrl: String, mobileApiKey: String): SaveResult {
        if (!isValidHttpUrl(backendBaseUrl)) {
            return SaveResult.InvalidBackendUrl
        }
        if (!isValidHttpUrl(opencodeWebUrl)) {
            return SaveResult.InvalidOpenCodeUrl
        }

        val normalizedApiKey = mobileApiKey.trim()
        plainPrefs.edit()
            .putString(KEY_BACKEND_BASE_URL, backendBaseUrl.trim())
            .putString(KEY_OPENCODE_WEB_URL, opencodeWebUrl.trim())
            .apply()
        securePrefs.edit()
            .apply {
                if (normalizedApiKey.isEmpty()) {
                    remove(KEY_MOBILE_API_KEY)
                } else {
                    putString(KEY_MOBILE_API_KEY, normalizedApiKey)
                }
            }
            .apply()
        return SaveResult.Saved
    }

    private fun migrateLegacyApiKeyIfNeeded() {
        if (securePrefs === plainPrefs) {
            return
        }
        val secureCurrent = securePrefs.getString(KEY_MOBILE_API_KEY, null)?.trim().orEmpty()
        if (secureCurrent.isNotEmpty()) {
            return
        }
        val legacy = plainPrefs.getString(KEY_MOBILE_API_KEY, null)?.trim().orEmpty()
        if (legacy.isEmpty()) {
            return
        }
        securePrefs.edit().putString(KEY_MOBILE_API_KEY, legacy).apply()
        plainPrefs.edit().remove(KEY_MOBILE_API_KEY).apply()
    }

    private fun createSecurePrefs(context: Context): SharedPreferences {
        return try {
            val masterKey = MasterKey.Builder(context)
                .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                .build()
            EncryptedSharedPreferences.create(
                context,
                SECURE_PREFS_NAME,
                masterKey,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
            )
        } catch (_: Exception) {
            plainPrefs
        }
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
        private const val SECURE_PREFS_NAME = "active_workbench_secure_config"
        private const val KEY_BACKEND_BASE_URL = "backend_base_url"
        private const val KEY_OPENCODE_WEB_URL = "opencode_web_url"
        private const val KEY_MOBILE_API_KEY = "mobile_api_key"
    }
}

sealed interface SaveResult {
    data object Saved : SaveResult
    data object InvalidBackendUrl : SaveResult
    data object InvalidOpenCodeUrl : SaveResult
}
