package com.activeworkbench.mobile.share

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters

class ShareSyncWorker(
    appContext: Context,
    workerParams: WorkerParameters,
) : CoroutineWorker(appContext, workerParams) {
    private val queueStore = ShareQueueStore(appContext)
    private val endpointConfigStore = EndpointConfigStore(appContext)

    override suspend fun doWork(): Result {
        processDueQueueItems()

        val retryDelay = queueStore.nextRetryDelayMs()
        if (retryDelay != null) {
            ShareSyncScheduler.scheduleDelayed(applicationContext, retryDelay)
        }
        queueStore.clearFinished()
        return Result.success()
    }

    private suspend fun processDueQueueItems() {
        val repository = ShareArticleRepository(
            api = WorkbenchApiFactory.create(endpointConfigStore.getBackendBaseUrl()),
        )
        while (true) {
            val due = queueStore.nextDueEntry() ?: break
            val syncing = queueStore.markSyncing(due.id) ?: continue

            when (
                val result = repository.submit(
                    url = syncing.url,
                    sharedText = syncing.sharedText,
                    sourceApp = syncing.sourceApp,
                )
            ) {
                is ShareSubmissionResult.Success -> {
                    queueStore.markSuccess(syncing.id, result.response)
                }
                is ShareSubmissionResult.Failure -> {
                    queueStore.markFailure(
                        entryId = syncing.id,
                        message = result.message,
                        canRetry = result.canRetry,
                    )
                }
            }
        }
    }
}
