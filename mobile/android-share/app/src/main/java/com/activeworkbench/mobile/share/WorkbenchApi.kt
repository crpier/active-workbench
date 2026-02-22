package com.activeworkbench.mobile.share

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory
import retrofit2.http.Header
import retrofit2.http.Body
import retrofit2.http.POST

interface WorkbenchApi {
    @POST("mobile/v1/share/article")
    suspend fun shareArticle(
        @Header("Authorization") authorization: String?,
        @Body request: ShareArticleRequest,
    ): ShareArticleResponse
}

object WorkbenchApiFactory {
    fun create(baseUrl: String): WorkbenchApi {
        val logging = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BASIC
        }

        val okHttpClient = OkHttpClient.Builder()
            .addInterceptor(logging)
            .build()

        val moshi = Moshi.Builder()
            .add(KotlinJsonAdapterFactory())
            .build()

        val retrofit = Retrofit.Builder()
            .baseUrl(normalizeBaseUrl(baseUrl))
            .client(okHttpClient)
            .addConverterFactory(MoshiConverterFactory.create(moshi))
            .build()

        return retrofit.create(WorkbenchApi::class.java)
    }

    fun toAuthorizationHeader(mobileApiKey: String?): String? {
        val normalized = mobileApiKey?.trim().orEmpty()
        if (normalized.isEmpty()) {
            return null
        }
        return "Bearer $normalized"
    }

    private fun normalizeBaseUrl(baseUrl: String): String {
        val trimmed = baseUrl.trim()
        if (trimmed.endsWith('/')) {
            return trimmed
        }
        return "$trimmed/"
    }
}
