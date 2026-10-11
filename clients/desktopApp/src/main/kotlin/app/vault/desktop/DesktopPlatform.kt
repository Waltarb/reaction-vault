package app.vault.desktop

import app.vault.sync.Storage
import app.vault.ui.Connection
import app.vault.ui.PickedFile
import app.vault.ui.Platform
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.awt.Desktop
import java.awt.FileDialog
import java.awt.Frame
import java.awt.Toolkit
import java.awt.datatransfer.DataFlavor
import java.awt.datatransfer.Transferable
import java.awt.datatransfer.UnsupportedFlavorException
import java.io.File
import java.net.URI

@Serializable
private data class StoredConnection(val serverUrl: String, val token: String)

/** Windows and Linux. State lives in the per-user config directory. */
class DesktopPlatform : Platform {
    override val name: String = if (System.getProperty("os.name").lowercase().contains("win")) "Windows" else "Linux"

    private val dir: File = run {
        val base = System.getenv("APPDATA")?.takeIf { it.isNotBlank() }?.let { File(it, "ReactionVault") }
            ?: File(System.getenv("XDG_CONFIG_HOME")?.takeIf { it.isNotBlank() } ?: (System.getProperty("user.home") + "/.config"),
                "reaction-vault")
        base.also { it.mkdirs() }
    }

    override val libraryStorage: Storage = object : Storage {
        private val file = File(dir, "library.json")
        override fun read(): String? = file.takeIf { it.exists() }?.readText()
        override fun write(text: String) {
            val tmp = File(dir, "library.json.tmp")
            tmp.writeText(text)
            tmp.renameTo(file).also { if (!it) { file.delete(); tmp.renameTo(file) } }
        }
    }

    private val connectionFile = File(dir, "connection.json")

    override fun loadConnection(): Connection? = runCatching {
        Json.decodeFromString(StoredConnection.serializer(), connectionFile.readText())
            .let { Connection(it.serverUrl, it.token) }
    }.getOrNull()

    override fun saveConnection(connection: Connection?) {
        if (connection == null) {
            connectionFile.delete()
            File(dir, "library.json").delete()
        } else {
            connectionFile.writeText(
                Json.encodeToString(StoredConnection.serializer(), StoredConnection(connection.serverUrl, connection.token)),
            )
        }
    }

    override suspend fun pickFiles(): List<PickedFile> = withContext(Dispatchers.Main) {
        val dialog = FileDialog(null as Frame?, "Add to Vault", FileDialog.LOAD).apply {
            isMultipleMode = true
            setFilenameFilter { _, n -> mimeFor(n) != null }
            isVisible = true
        }
        dialog.files.orEmpty().mapNotNull { f ->
            val mime = mimeFor(f.name) ?: return@mapNotNull null
            PickedFile(f.name, mime, f.readBytes())
        }
    }

    override suspend fun sendMedia(bytes: ByteArray, mime: String, fileName: String): String =
        withContext(Dispatchers.IO) {
            val safe = fileName.replace(Regex("[\\\\/:*?\"<>|]"), "_")
            val out = File(System.getProperty("java.io.tmpdir"), "reaction-vault").apply { mkdirs() }.let { File(it, safe) }
            out.writeBytes(bytes)
            out.deleteOnExit()
            val flavor = DataFlavor.javaFileListFlavor
            Toolkit.getDefaultToolkit().systemClipboard.setContents(object : Transferable {
                override fun getTransferDataFlavors() = arrayOf(flavor)
                override fun isDataFlavorSupported(f: DataFlavor) = f == flavor
                override fun getTransferData(f: DataFlavor): Any =
                    if (f == flavor) listOf(out) else throw UnsupportedFlavorException(f)
            }, null)
            "Copied $safe. Paste it into a chat."
        }

    override fun openUrl(url: String) {
        runCatching { if (Desktop.isDesktopSupported()) Desktop.getDesktop().browse(URI(url)) }
    }

    private fun mimeFor(name: String): String? = when (name.substringAfterLast('.', "").lowercase()) {
        "png" -> "image/png"
        "jpg", "jpeg" -> "image/jpeg"
        "gif" -> "image/gif"
        "webp" -> "image/webp"
        "avif" -> "image/avif"
        "mp4" -> "video/mp4"
        "webm" -> "video/webm"
        else -> null
    }
}
