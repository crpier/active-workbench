package com.activeworkbench.mobile.share

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.activity.ComponentActivity

class ShareReceiverActivity : ComponentActivity() {
    private val queueStore: ShareQueueStore by lazy { ShareQueueStore(this) }

    private lateinit var statusText: TextView
    private lateinit var detailText: TextView
    private lateinit var retryButton: Button
    private lateinit var doneButton: Button
    private lateinit var openHistoryButton: Button

    private var pendingEntry: ShareQueueEntry? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_share_receiver)

        statusText = findViewById(R.id.statusText)
        detailText = findViewById(R.id.detailText)
        retryButton = findViewById(R.id.retryButton)
        doneButton = findViewById(R.id.doneButton)
        openHistoryButton = findViewById(R.id.openHistoryButton)

        retryButton.setOnClickListener { syncNow() }
        doneButton.setOnClickListener { finish() }
        openHistoryButton.setOnClickListener {
            startActivity(Intent(this, MainActivity::class.java))
            finish()
        }

        val restoredEntryId = savedInstanceState?.getString(STATE_PENDING_ENTRY_ID)
        if (!restoredEntryId.isNullOrBlank()) {
            pendingEntry = queueStore.getEntry(restoredEntryId)
            val restored = pendingEntry
            if (restored != null) {
                renderQueued(restored)
            } else {
                renderFailure(
                    message = "Could not restore queued share state.",
                    canRetry = false,
                )
            }
        } else {
            handleShareIntent(intent)
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleShareIntent(intent)
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        val currentId = pendingEntry?.id ?: return
        outState.putString(STATE_PENDING_ENTRY_ID, currentId)
    }

    private fun handleShareIntent(intent: Intent?) {
        if (intent == null || intent.action != Intent.ACTION_SEND) {
            renderFailure(
                message = "Unsupported intent. Use Android Share from another app.",
                canRetry = false,
            )
            return
        }

        val sharedText = intent.getStringExtra(Intent.EXTRA_TEXT)
        val extractedUrl = UrlExtractor.extractFirstHttpUrl(sharedText)
        val fallbackUrl = normalizeHttpUrl(intent.dataString)
        val resolvedUrl = extractedUrl ?: fallbackUrl

        if (resolvedUrl == null) {
            renderFailure(
                message = getString(R.string.share_missing_url),
                canRetry = false,
            )
            return
        }

        val queued = queueStore.enqueue(
            url = resolvedUrl,
            sharedText = sharedText,
            sourceApp = resolveSourceApp(intent),
        )
        pendingEntry = queued
        ShareSyncScheduler.scheduleNow(this)
        Toast.makeText(this, getString(R.string.share_queued), Toast.LENGTH_SHORT).show()
        finish()
    }

    private fun syncNow() {
        ShareSyncScheduler.scheduleNow(this)
        pendingEntry?.let { renderQueued(it) }
    }

    private fun renderQueued(entry: ShareQueueEntry) {
        retryButton.visibility = View.VISIBLE
        openHistoryButton.visibility = View.VISIBLE
        statusText.text = getString(R.string.share_queued)
        detailText.text = buildString {
            append("URL: ")
            append(entry.url)
            append("\nQueue id: ")
            append(entry.id)
            append("\n")
            append(getString(R.string.share_queued_detail))
        }
    }

    private fun renderFailure(message: String, canRetry: Boolean) {
        retryButton.visibility = if (canRetry) View.VISIBLE else View.GONE
        openHistoryButton.visibility = View.VISIBLE
        statusText.text = "Could not save article"
        detailText.text = message
    }

    private fun resolveSourceApp(intent: Intent): String? {
        val byCallingPackage = callingPackage?.trim().orEmpty()
        if (byCallingPackage.isNotEmpty()) {
            return byCallingPackage
        }

        val byReferrerHost = referrer?.host?.trim().orEmpty()
        if (byReferrerHost.isNotEmpty()) {
            return byReferrerHost
        }

        val byReferrerName = intent.getStringExtra(Intent.EXTRA_REFERRER_NAME)?.trim().orEmpty()
        if (byReferrerName.isNotEmpty()) {
            return byReferrerName
        }

        return null
    }

    private fun normalizeHttpUrl(candidate: String?): String? {
        if (candidate.isNullOrBlank()) {
            return null
        }
        return try {
            val uri = Uri.parse(candidate)
            if (uri.scheme == "http" || uri.scheme == "https") {
                uri.toString()
            } else {
                null
            }
        } catch (_: Exception) {
            null
        }
    }

    companion object {
        private const val STATE_PENDING_ENTRY_ID = "pending_entry_id"
    }
}
