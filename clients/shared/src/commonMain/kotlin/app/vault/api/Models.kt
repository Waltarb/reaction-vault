package app.vault.api

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class Tag(val name: String, val origin: String = "manual", val score: Double? = null)

@Serializable
data class Rendition(val bytes: Long? = null, val width: Int? = null, val height: Int? = null)

@Serializable
data class Urls(
    val original: String,
    val thumb: String? = null,
    val preview: String? = null,
    val mp4: String? = null,
    val gif: String? = null,
)

@Serializable
data class Item(
    val id: Long,
    val sha256: String = "",
    val title: String = "",
    /** image | animated | video */
    val kind: String = "image",
    val mime: String = "",
    val width: Int = 0,
    val height: Int = 0,
    @SerialName("duration_ms") val durationMs: Long? = null,
    @SerialName("frame_count") val frameCount: Int? = null,
    @SerialName("has_alpha") val hasAlpha: Boolean = false,
    @SerialName("has_audio") val hasAudio: Boolean = false,
    val bytes: Long = 0,
    val favorite: Boolean = false,
    val source: String = "upload",
    @SerialName("source_url") val sourceUrl: String? = null,
    @SerialName("created_at") val createdAt: String = "",
    @SerialName("updated_at") val updatedAt: String = "",
    val rev: Long = 0,
    val tags: List<Tag> = emptyList(),
    @SerialName("collection_ids") val collectionIds: List<Long> = emptyList(),
    val renditions: Map<String, Rendition> = emptyMap(),
    val urls: Urls,
    /** Present on search results only. */
    val score: Double? = null,
) {
    val isAnimated: Boolean get() = kind != "image"
    val formatLabel: String
        get() = when (mime) {
            "image/webp" -> "WEBP"
            "image/gif" -> "GIF"
            "image/png" -> "PNG"
            "image/jpeg" -> "JPG"
            "image/avif" -> "AVIF"
            "video/mp4" -> "MP4"
            "video/webm" -> "WEBM"
            else -> mime.substringAfter('/').uppercase()
        }

    /** The formats an item can be sent as, with sizes when known. The original is always first. */
    fun sendFormats(): List<SendFormat> {
        val out = mutableListOf(SendFormat("original", formatLabel, bytes, urls.original))
        if (isAnimated) {
            if (mime != "video/mp4") out += SendFormat("mp4", "MP4", renditions["mp4"]?.bytes, "/media/$id/send/mp4")
            if (mime != "image/gif") out += SendFormat("gif", "GIF", renditions["gif"]?.bytes, "/media/$id/send/gif")
        }
        return out
    }
}

data class SendFormat(val key: String, val label: String, val bytes: Long?, val path: String)

@Serializable
data class VaultCollection(
    val id: Long,
    val name: String,
    val color: String? = null,
    val count: Int = 0,
    val rev: Long = 0,
)

@Serializable
data class ItemsPage(
    val items: List<Item>,
    @SerialName("next_cursor") val nextCursor: Long? = null,
)

@Serializable
data class SearchPage(
    val items: List<Item>,
    val semantic: Boolean = false,
    val offset: Int = 0,
)

@Serializable
data class EmbeddingStatus(val state: String = "idle", val model: String? = null, val error: String? = null)

@Serializable
data class ServerInfo(
    val version: String = "",
    val rev: Long = 0,
    val items: Int = 0,
    val bytes: Long = 0,
    val unsorted: Int = 0,
    val favorites: Int = 0,
    val jobs: Map<String, Int> = emptyMap(),
    @SerialName("disk_free") val diskFree: Long = 0,
    val embeddings: EmbeddingStatus = EmbeddingStatus(),
)

@Serializable
data class StagedMeta(
    val kind: String = "image",
    val mime: String = "",
    val width: Int = 0,
    val height: Int = 0,
    @SerialName("duration_ms") val durationMs: Long? = null,
    val bytes: Long = 0,
    @SerialName("suggested_title") val suggestedTitle: String = "",
)

@Serializable
data class NearMatch(val item: Item, val similarity: Double)

@Serializable
data class AutoTag(val name: String, val score: Double? = null)

/** Result of the first ingest step. `duplicate == "exact"` means [item] is already in the vault. */
@Serializable
data class StageResult(
    @SerialName("staged_id") val stagedId: String? = null,
    val duplicate: String? = null,
    val meta: StagedMeta? = null,
    val item: Item? = null,
    val near: List<NearMatch> = emptyList(),
    @SerialName("auto_tags") val autoTags: List<AutoTag> = emptyList(),
    @SerialName("file_url") val fileUrl: String? = null,
)

@Serializable
data class CommitResult(val item: Item, val duplicate: String? = null)

@Serializable
data class DiscoverItem(
    val source: String,
    @SerialName("source_id") val sourceId: String,
    val title: String = "",
    @SerialName("preview_url") val previewUrl: String,
    val mime: String = "",
    val width: Int? = null,
    val height: Int? = null,
    val animated: Boolean = false,
    @SerialName("page_url") val pageUrl: String? = null,
    val author: String? = null,
    @SerialName("saved_item_id") val savedItemId: Long? = null,
    val similarity: Double? = null,
)

@Serializable
data class DiscoverPage(
    val items: List<DiscoverItem>,
    val page: Int = 1,
    @SerialName("has_more") val hasMore: Boolean = false,
    val reranked: Boolean = false,
    val errors: Map<String, String> = emptyMap(),
)

@Serializable
data class DiscoverSource(val key: String, val label: String)

@Serializable
data class SyncResponse(
    val rev: Long,
    @SerialName("has_more") val hasMore: Boolean = false,
    val items: List<kotlinx.serialization.json.JsonElement> = emptyList(),
    val collections: List<kotlinx.serialization.json.JsonElement> = emptyList(),
)

/** Library filters. `kind` is one of "animated", "static", "image", "video". */
data class ItemFilter(
    val kind: String? = null,
    val favorite: Boolean = false,
    val unsorted: Boolean = false,
    val collection: Long? = null,
    val tag: String? = null,
    val maxBytes: Long? = null,
    val transparent: Boolean = false,
)
