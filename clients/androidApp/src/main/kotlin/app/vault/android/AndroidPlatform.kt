package app.vault.android

import android.content.ClipData
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.OpenableColumns
import androidx.core.content.FileProvider
import app.vault.sync.Storage
import app.vault.ui.Connection
import app.vault.ui.PickedFile
import app.vault.ui.Platform
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.withContext
import java.io.File

class AndroidPlatform(
    private val activity: Context,
    override val incoming: Flow<PickedFile>,
    private val launchPicker: (CompletableDeferred<List<Uri>>) -> Unit,
) : Platform {
    override val name: String = "Android"

    private val prefs = activity.getSharedPreferences("vault", Context.MODE_PRIVATE)

    override val libraryStorage: Storage = object : Storage {
        private val file = File(activity.filesDir, "library.json")
        override fun read(): String? = file.takeIf { it.exists() }?.readText()
        override fun write(text: String) {
            val tmp = File(activity.filesDir, "library.json.tmp")
            tmp.writeText(text)
            if (!tmp.renameTo(file)) {
                file.delete()
                tmp.renameTo(file)
            }
        }
    }

    override fun loadConnection(): Connection? {
        val url = prefs.getString("serverUrl", null) ?: return null
        return Connection(url, prefs.getString("token", "") ?: "")
    }

    override fun saveConnection(connection: Connection?) {
        prefs.edit().apply {
            if (connection == null) clear() else {
                putString("serverUrl", connection.serverUrl)
                putString("token", connection.token)
            }
        }.apply()
        if (connection == null) File(activity.filesDir, "library.json").delete()
    }

    override suspend fun pickFiles(): List<PickedFile> {
        val deferred = CompletableDeferred<List<Uri>>()
        launchPicker(deferred)
        val uris = deferred.await()
        return withContext(Dispatchers.IO) { uris.mapNotNull { read(it) } }
    }

    /** Reads a content URI fully into memory. Reaction images are small, and the server limits size. */
    fun read(uri: Uri): PickedFile? = runCatching {
        val resolver = activity.contentResolver
        val mime = resolver.getType(uri) ?: "application/octet-stream"
        val name = resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
            if (c.moveToFirst()) c.getString(0) else null
        } ?: uri.lastPathSegment ?: "shared"
        val bytes = resolver.openInputStream(uri)?.use { it.readBytes() } ?: return null
        PickedFile(name, mime, bytes)
    }.getOrNull()

    override suspend fun sendMedia(bytes: ByteArray, mime: String, fileName: String): String =
        withContext(Dispatchers.IO) {
            val dir = File(activity.cacheDir, "shared").apply { mkdirs() }
            val file = File(dir, fileName.replace(Regex("[\\\\/:*?\"<>|]"), "_"))
            file.writeBytes(bytes)
            val uri = FileProvider.getUriForFile(activity, "${activity.packageName}.files", file)
            val send = Intent(Intent.ACTION_SEND).apply {
                type = mime
                putExtra(Intent.EXTRA_STREAM, uri)
                clipData = ClipData.newRawUri(fileName, uri)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            val chooser = Intent.createChooser(send, "Send ${file.name}").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            activity.startActivity(chooser)
            "Choose where to send it"
        }

    override fun openUrl(url: String) {
        activity.startActivity(
            Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        )
    }
}
