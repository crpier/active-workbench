package com.activeworkbench.mobile.share

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity

class MainActivity : AppCompatActivity() {
    private val queueStore: ShareQueueStore by lazy { ShareQueueStore(this) }
    private val endpointConfigStore: EndpointConfigStore by lazy { EndpointConfigStore(this) }
    private lateinit var historyText: TextView
    private lateinit var backendUrlInput: EditText
    private lateinit var opencodeUrlInput: EditText

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        backendUrlInput = findViewById(R.id.backendUrlInput)
        opencodeUrlInput = findViewById(R.id.opencodeUrlInput)
        backendUrlInput.setText(endpointConfigStore.getBackendBaseUrl())
        opencodeUrlInput.setText(endpointConfigStore.getOpencodeWebUrl())

        historyText = findViewById(R.id.historyText)
        findViewById<Button>(R.id.saveEndpointsButton).setOnClickListener {
            saveEndpoints()
        }
        findViewById<Button>(R.id.openChatButton).setOnClickListener {
            startActivity(Intent(this, ChatActivity::class.java))
        }
        findViewById<Button>(R.id.syncNowButton).setOnClickListener {
            ShareSyncScheduler.scheduleNow(this)
            renderHistory()
        }

        handleShortcutIntent(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleShortcutIntent(intent)
    }

    override fun onResume() {
        super.onResume()
        ShareSyncScheduler.scheduleNow(this)
        renderHistory()
    }

    private fun renderHistory() {
        val entries = queueStore.listRecent(limit = 30)
        if (entries.isEmpty()) {
            historyText.text = getString(R.string.history_empty)
            return
        }

        historyText.text = buildString {
            entries.forEach { entry ->
                append(formatStatus(entry.status))
                append("  ")
                append(entry.url)
                if (!entry.message.isNullOrBlank()) {
                    append("\n")
                    append("   ")
                    append(entry.message)
                }
                if (!entry.canonicalUrl.isNullOrBlank()) {
                    append("\n")
                    append("   canonical: ")
                    append(entry.canonicalUrl)
                }
                append("\n\n")
            }
        }.trim()
    }

    private fun formatStatus(status: String): String {
        return when (status) {
            ShareQueueStore.STATUS_QUEUED -> "QUEUED"
            ShareQueueStore.STATUS_SYNCING -> "SYNCING"
            ShareQueueStore.STATUS_RETRY_WAIT -> "RETRY_WAIT"
            ShareQueueStore.STATUS_SAVED -> "SAVED"
            ShareQueueStore.STATUS_ALREADY_EXISTS -> "ALREADY_EXISTS"
            ShareQueueStore.STATUS_NEEDS_CLARIFICATION -> "NEEDS_CLARIFICATION"
            ShareQueueStore.STATUS_FAILED -> "FAILED"
            else -> status.uppercase()
        }
    }

    private fun handleShortcutIntent(intent: Intent?) {
        if (intent?.action != ACTION_SYNC_NOW) {
            return
        }

        ShareSyncScheduler.scheduleNow(this)
        renderHistory()
        Toast.makeText(this, getString(R.string.shortcut_sync_triggered), Toast.LENGTH_SHORT).show()
    }

    private fun saveEndpoints() {
        val backendUrl = backendUrlInput.text?.toString().orEmpty()
        val opencodeUrl = opencodeUrlInput.text?.toString().orEmpty()
        when (endpointConfigStore.saveUrls(backendUrl, opencodeUrl)) {
            SaveResult.Saved -> {
                Toast.makeText(this, getString(R.string.endpoints_saved), Toast.LENGTH_SHORT).show()
            }
            SaveResult.InvalidBackendUrl -> {
                Toast.makeText(this, getString(R.string.invalid_backend_url), Toast.LENGTH_SHORT).show()
            }
            SaveResult.InvalidOpenCodeUrl -> {
                Toast.makeText(this, getString(R.string.invalid_opencode_url), Toast.LENGTH_SHORT).show()
            }
        }
    }

    companion object {
        const val ACTION_SYNC_NOW = "com.activeworkbench.mobile.share.action.SYNC_NOW"
    }
}
