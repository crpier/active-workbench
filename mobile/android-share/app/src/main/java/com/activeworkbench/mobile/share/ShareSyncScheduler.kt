package com.activeworkbench.mobile.share

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

object ShareSyncScheduler {
    private const val UNIQUE_WORK_NAME = "active_workbench_share_sync"

    fun scheduleNow(context: Context) {
        val request = OneTimeWorkRequestBuilder<ShareSyncWorker>()
            .setConstraints(defaultConstraints())
            .build()
        WorkManager.getInstance(context.applicationContext).enqueueUniqueWork(
            UNIQUE_WORK_NAME,
            ExistingWorkPolicy.KEEP,
            request,
        )
    }

    fun scheduleDelayed(context: Context, delayMs: Long) {
        val request = OneTimeWorkRequestBuilder<ShareSyncWorker>()
            .setConstraints(defaultConstraints())
            .setInitialDelay(delayMs.coerceAtLeast(0L), TimeUnit.MILLISECONDS)
            .build()
        WorkManager.getInstance(context.applicationContext).enqueueUniqueWork(
            UNIQUE_WORK_NAME,
            ExistingWorkPolicy.REPLACE,
            request,
        )
    }

    private fun defaultConstraints(): Constraints {
        return Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
    }
}
