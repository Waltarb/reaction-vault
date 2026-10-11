package app.vault.ui

import app.vault.sync.Storage
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow

class PickedFile(val name: String, val mime: String, val bytes: ByteArray)

/** What the shared UI needs from the host app. Implemented once per platform. */
interface Platform {
    /** "Windows", "Linux", "Android": shown in the UI where wording differs. */
    val name: String

    /** Where the offline copy of the library lives. */
    val libraryStorage: Storage

    /** Saved connection, or null on first run. */
    fun loadConnection(): Connection?
    fun saveConnection(connection: Connection?)

    /** Lets the person choose images or videos. Empty when cancelled. */
    suspend fun pickFiles(): List<PickedFile>

    /**
     * Gets the bytes in front of the person in whatever way the platform allows: copied to the
     * clipboard as a file on desktop, handed to the share sheet on Android.
     * Returns a short message to show, such as "Copied".
     */
    suspend fun sendMedia(bytes: ByteArray, mime: String, fileName: String): String

    fun openUrl(url: String)

    /** Files handed to the app from outside, such as the Android share sheet. */
    val incoming: Flow<PickedFile> get() = emptyFlow()
}

data class Connection(val serverUrl: String, val token: String)
