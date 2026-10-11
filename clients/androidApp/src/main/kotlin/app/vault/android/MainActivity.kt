package app.vault.android

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import app.vault.ui.PickedFile
import app.vault.ui.VaultApp
import io.ktor.client.engine.okhttp.OkHttp
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.receiveAsFlow

class MainActivity : ComponentActivity() {
    // Channels hold shares that arrive before the UI is collecting, such as a cold start from the share sheet.
    private val incoming = Channel<PickedFile>(Channel.BUFFERED)
    private val incomingUrls = Channel<String>(Channel.BUFFERED)
    private var pending: CompletableDeferred<List<Uri>>? = null

    private val picker = registerForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        pending?.complete(uris)
        pending = null
    }

    private lateinit var platform: AndroidPlatform

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        platform = AndroidPlatform(
            activity = this,
            incoming = incoming.receiveAsFlow(),
            incomingUrls = incomingUrls.receiveAsFlow(),
            launchPicker = { deferred ->
                pending = deferred
                picker.launch(arrayOf("image/*", "video/mp4", "video/webm"))
            },
        )
        setContent { VaultApp(platform, engine = { OkHttp.create() }) }
        handle(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handle(intent)
    }

    /** Files shared to the app from another app's share sheet. */
    private fun handle(intent: Intent?) {
        if (intent == null) return
        // A link shared from a browser or chat arrives as text.
        if (intent.action == Intent.ACTION_SEND && intent.type?.startsWith("text/") == true) {
            val text = intent.getStringExtra(Intent.EXTRA_TEXT).orEmpty()
            URL_PATTERN.find(text)?.value?.let { incomingUrls.trySend(it) }
            return
        }
        val uris = when (intent.action) {
            Intent.ACTION_SEND -> listOfNotNull(intent.streamUri())
            Intent.ACTION_SEND_MULTIPLE -> intent.streamUris()
            else -> emptyList()
        }
        for (uri in uris) platform.read(uri)?.let { incoming.trySend(it) }
    }

    @Suppress("DEPRECATION")
    private fun Intent.streamUri(): Uri? = getParcelableExtra(Intent.EXTRA_STREAM)

    @Suppress("DEPRECATION")
    private fun Intent.streamUris(): List<Uri> =
        getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM).orEmpty()

    private companion object {
        val URL_PATTERN = Regex("https?://\\S+")
    }
}
