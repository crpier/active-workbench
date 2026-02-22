package com.activeworkbench.mobile.share

import android.content.Context
import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import java.util.UUID

data class ShareQueueEntry(
    val id: String,
    val url: String,
    val sharedText: String? = null,
    val sourceApp: String? = null,
    val createdAtEpochMs: Long,
    val updatedAtEpochMs: Long,
    val status: String,
    val attemptCount: Int = 0,
    val nextAttemptAtEpochMs: Long? = null,
    val bucketItemId: String? = null,
    val title: String? = null,
    val canonicalUrl: String? = null,
    val message: String? = null,
    val canRetry: Boolean = true,
)

class ShareQueueStore(context: Context) {
    private val appContext = context.applicationContext
    private val prefs = appContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    private val adapter: JsonAdapter<List<ShareQueueEntry>> = Moshi.Builder()
        .add(KotlinJsonAdapterFactory())
        .build()
        .adapter(
            Types.newParameterizedType(
                List::class.java,
                ShareQueueEntry::class.java,
            ),
        )

    @Synchronized
    fun enqueue(
        url: String,
        sharedText: String?,
        sourceApp: String?,
    ): ShareQueueEntry {
        val now = System.currentTimeMillis()
        val entry = ShareQueueEntry(
            id = "q_${UUID.randomUUID()}",
            url = url,
            sharedText = sharedText,
            sourceApp = sourceApp,
            createdAtEpochMs = now,
            updatedAtEpochMs = now,
            status = STATUS_QUEUED,
            attemptCount = 0,
            nextAttemptAtEpochMs = now,
            canRetry = true,
        )
        val items = loadMutable()
        items.add(entry)
        save(items)
        return entry
    }

    @Synchronized
    fun listRecent(limit: Int = 50): List<ShareQueueEntry> {
        return loadMutable()
            .sortedByDescending { it.updatedAtEpochMs }
            .take(limit)
    }

    @Synchronized
    fun getEntry(entryId: String): ShareQueueEntry? {
        return loadMutable().firstOrNull { it.id == entryId }
    }

    @Synchronized
    fun markSyncing(entryId: String): ShareQueueEntry? {
        val items = loadMutable()
        val index = items.indexOfFirst { it.id == entryId }
        if (index < 0) {
            return null
        }
        val current = items[index]
        val updated = current.copy(
            status = STATUS_SYNCING,
            attemptCount = current.attemptCount + 1,
            updatedAtEpochMs = System.currentTimeMillis(),
            message = null,
        )
        items[index] = updated
        save(items)
        return updated
    }

    @Synchronized
    fun nextDueEntry(nowEpochMs: Long = System.currentTimeMillis()): ShareQueueEntry? {
        return loadMutable()
            .filter {
                (it.status == STATUS_QUEUED || it.status == STATUS_RETRY_WAIT) &&
                    it.canRetry &&
                    (it.nextAttemptAtEpochMs == null || it.nextAttemptAtEpochMs <= nowEpochMs)
            }
            .sortedBy { it.nextAttemptAtEpochMs ?: it.createdAtEpochMs }
            .firstOrNull()
    }

    @Synchronized
    fun markSuccess(entryId: String, response: ShareArticleResponse): ShareQueueEntry? {
        val items = loadMutable()
        val index = items.indexOfFirst { it.id == entryId }
        if (index < 0) {
            return null
        }
        val normalizedStatus = when (response.status) {
            "saved" -> STATUS_SAVED
            "already_exists" -> STATUS_ALREADY_EXISTS
            "needs_clarification" -> STATUS_NEEDS_CLARIFICATION
            else -> STATUS_FAILED
        }
        val updated = items[index].copy(
            status = normalizedStatus,
            updatedAtEpochMs = System.currentTimeMillis(),
            bucketItemId = response.bucketItemId,
            title = response.title,
            canonicalUrl = response.canonicalUrl,
            message = response.message,
            canRetry = false,
            nextAttemptAtEpochMs = null,
        )
        items[index] = updated
        save(items)
        return updated
    }

    @Synchronized
    fun markFailure(entryId: String, message: String, canRetry: Boolean): ShareQueueEntry? {
        val items = loadMutable()
        val index = items.indexOfFirst { it.id == entryId }
        if (index < 0) {
            return null
        }
        val current = items[index]
        val now = System.currentTimeMillis()
        val shouldRetry = canRetry && current.attemptCount < MAX_RETRY_ATTEMPTS
        val delayMs = if (shouldRetry) exponentialBackoffDelay(current.attemptCount) else null
        val updated = current.copy(
            status = if (shouldRetry) STATUS_RETRY_WAIT else STATUS_FAILED,
            updatedAtEpochMs = now,
            message = message,
            canRetry = shouldRetry,
            nextAttemptAtEpochMs = delayMs?.let { now + it },
        )
        items[index] = updated
        save(items)
        return updated
    }

    @Synchronized
    fun nextRetryDelayMs(nowEpochMs: Long = System.currentTimeMillis()): Long? {
        val nextEpoch = loadMutable()
            .filter { it.status == STATUS_RETRY_WAIT && it.canRetry }
            .mapNotNull { it.nextAttemptAtEpochMs }
            .minOrNull() ?: return null
        return (nextEpoch - nowEpochMs).coerceAtLeast(0L)
    }

    @Synchronized
    fun clearFinished(limitToMostRecent: Int = 200): Int {
        val items = loadMutable()
        val pending = items.filter {
            it.status == STATUS_QUEUED ||
                it.status == STATUS_SYNCING ||
                it.status == STATUS_RETRY_WAIT
        }
        val terminal = items.filterNot {
            it.status == STATUS_QUEUED ||
                it.status == STATUS_SYNCING ||
                it.status == STATUS_RETRY_WAIT
        }.sortedByDescending { it.updatedAtEpochMs }

        val keep = (pending + terminal.take(limitToMostRecent))
            .distinctBy { it.id }
            .sortedByDescending { it.updatedAtEpochMs }

        if (keep.size == items.size) {
            return 0
        }
        save(keep.toMutableList())
        return items.size - keep.size
    }

    private fun exponentialBackoffDelay(attemptCount: Int): Long {
        val power = (attemptCount - 1).coerceAtLeast(0).coerceAtMost(6)
        val multiplier = 1L shl power
        return (BASE_RETRY_DELAY_MS * multiplier).coerceAtMost(MAX_RETRY_DELAY_MS)
    }

    private fun loadMutable(): MutableList<ShareQueueEntry> {
        val raw = prefs.getString(KEY_ENTRIES, null) ?: return mutableListOf()
        return try {
            adapter.fromJson(raw).orEmpty().toMutableList()
        } catch (_: Exception) {
            mutableListOf()
        }
    }

    private fun save(entries: MutableList<ShareQueueEntry>) {
        val json = adapter.toJson(entries)
        prefs.edit().putString(KEY_ENTRIES, json).apply()
    }

    companion object {
        private const val PREFS_NAME = "active_workbench_share_queue"
        private const val KEY_ENTRIES = "entries_json"
        private const val BASE_RETRY_DELAY_MS = 30_000L
        private const val MAX_RETRY_DELAY_MS = 6 * 60 * 60 * 1000L
        private const val MAX_RETRY_ATTEMPTS = 8

        const val STATUS_QUEUED = "queued"
        const val STATUS_SYNCING = "syncing"
        const val STATUS_RETRY_WAIT = "retry_wait"
        const val STATUS_SAVED = "saved"
        const val STATUS_ALREADY_EXISTS = "already_exists"
        const val STATUS_NEEDS_CLARIFICATION = "needs_clarification"
        const val STATUS_FAILED = "failed"
    }
}
