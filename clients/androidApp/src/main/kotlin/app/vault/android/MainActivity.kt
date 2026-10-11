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
import kotlinx.coroutines.flow.MutableSharedFlow

class MainActivity : ComponentActivity() {
    private val incoming = MutableSharedFlow<PickedFile>(extraBufferCapacity = 16)
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
            incoming = incoming,
            launchPicker = { deferred ->
                pending = deferred
                picker.launch(arrayOf("image/*", "video/mp4", "video/webm"))
            },
        )
        setContent { VaultApp(platform) { OkHttp.create() } }
        handle(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handle(intent)
    }

    /** Files shared to the app from another app's share sheet. */
    private fun handle(intent: Intent?) {
        if (intent == null) return
        val uris = when (intent.action) {
            Intent.ACTION_SEND -> listOfNotNull(intent.streamUri())
            Intent.ACTION_SEND_MULTIPLE -> intent.streamUris()
            else -> emptyList()
        }
        for (uri in uris) platform.read(uri)?.let { incoming.tryEmit(it) }
    }

    @Suppress("DEPRECATION")
    private fun Intent.streamUri(): Uri? = getParcelableExtra(Intent.EXTRA_STREAM)

    @Suppress("DEPRECATION")
    private fun Intent.streamUris(): List<Uri> =
        getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM).orEmpty()
}
