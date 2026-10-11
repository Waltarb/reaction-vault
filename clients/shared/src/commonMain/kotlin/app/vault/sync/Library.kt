package app.vault.sync

import app.vault.api.VaultCollection
import app.vault.api.Item
import app.vault.api.ItemFilter
import app.vault.api.VaultApi
import app.vault.api.VaultJson
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** Where the offline copy of the library is kept. One implementation per platform. */
interface Storage {
    fun read(): String?
    fun write(text: String)
}

class MemoryStorage(var text: String? = null) : Storage {
    override fun read(): String? = text
    override fun write(text: String) { this.text = text }
}

@Serializable
private data class Snapshot(
    val rev: Long = 0,
    val items: List<Item> = emptyList(),
    val collections: List<VaultCollection> = emptyList(),
)

data class LibraryState(
    val rev: Long = 0,
    val items: Map<Long, Item> = emptyMap(),
    val collections: Map<Long, VaultCollection> = emptyMap(),
    val syncing: Boolean = false,
    val lastSyncError: String? = null,
) {
    /** Newest first, matching the server's default order. */
    val ordered: List<Item> get() = items.values.sortedByDescending { it.id }
}

/**
 * The offline mirror of the server library, kept current with the `/api/sync` change feed.
 * The UI reads [state] and works from it when the server is unreachable.
 */
class Library(private val api: VaultApi, private val storage: Storage) {
    private val _state = MutableStateFlow(LibraryState())
    val state: StateFlow<LibraryState> = _state.asStateFlow()

    init {
        load()
    }

    private fun load() {
        val text = storage.read() ?: return
        val snap = runCatching { VaultJson.decodeFromString(Snapshot.serializer(), text) }.getOrNull() ?: return
        _state.value = LibraryState(
            rev = snap.rev,
            items = snap.items.associateBy { it.id },
            collections = snap.collections.associateBy { it.id },
        )
    }

    private fun persist() {
        val s = _state.value
        val snap = Snapshot(s.rev, s.items.values.toList(), s.collections.values.toList())
        runCatching { storage.write(VaultJson.encodeToString(Snapshot.serializer(), snap)) }
    }

    /** Pulls every change since the last sync. Returns true when the server was reached. */
    suspend fun sync(): Boolean {
        _state.update { it.copy(syncing = true, lastSyncError = null) }
        return try {
            var since = _state.value.rev
            do {
                val page = api.sync(since)
                apply(page.items.map { it.jsonObject }, page.collections.map { it.jsonObject }, page.rev)
                since = page.rev
            } while (page.hasMore)
            persist()
            _state.update { it.copy(syncing = false) }
            true
        } catch (e: Exception) {
            _state.update { it.copy(syncing = false, lastSyncError = e.message ?: e::class.simpleName) }
            false
        }
    }

    private fun apply(items: List<JsonObject>, collections: List<JsonObject>, rev: Long) {
        _state.update { s ->
            val newItems = s.items.toMutableMap()
            for (o in items) {
                val id = o["id"]!!.jsonPrimitive.content.toLong()
                if (o["deleted"]?.jsonPrimitive?.booleanOrNull == true) newItems.remove(id)
                else newItems[id] = VaultJson.decodeFromJsonElement(Item.serializer(), o)
            }
            val newCollections = s.collections.toMutableMap()
            for (o in collections) {
                val id = o["id"]!!.jsonPrimitive.content.toLong()
                if (o["deleted"]?.jsonPrimitive?.booleanOrNull == true) newCollections.remove(id)
                else newCollections[id] = VaultJson.decodeFromJsonElement(VaultCollection.serializer(), o)
            }
            s.copy(rev = rev, items = newItems, collections = newCollections)
        }
    }

    /** Insert or replace one item after a local edit, so the UI updates before the next sync. */
    fun upsert(item: Item) {
        _state.update { it.copy(items = it.items + (item.id to item)) }
        persist()
    }

    fun remove(id: Long) {
        _state.update { it.copy(items = it.items - id) }
        persist()
    }

    /** Offline search over title, tags and source. Online search is ranked by the server instead. */
    fun searchLocal(query: String, filter: ItemFilter = ItemFilter()): List<Item> {
        val words = query.lowercase().split(Regex("\\W+")).filter { it.isNotBlank() }
        return state.value.ordered.filter { it.matches(filter) && words.all { w -> it.haystack().contains(w) } }
    }

    fun filtered(filter: ItemFilter): List<Item> = state.value.ordered.filter { it.matches(filter) }

    private fun Item.haystack(): String =
        (listOf(title, source) + tags.map { it.name }).joinToString(" ").lowercase()

    private fun Item.matches(f: ItemFilter): Boolean {
        when (f.kind) {
            "animated" -> if (!isAnimated) return false
            "static", "image" -> if (kind != "image") return false
            "video" -> if (kind != "video") return false
        }
        if (f.favorite && !favorite) return false
        if (f.unsorted && collectionIds.isNotEmpty()) return false
        if (f.collection != null && f.collection !in collectionIds) return false
        if (f.tag != null && tags.none { it.name == f.tag.lowercase() }) return false
        if (f.maxBytes != null && bytes > f.maxBytes) return false
        if (f.transparent && !hasAlpha) return false
        return true
    }
}
