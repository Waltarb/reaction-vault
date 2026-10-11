package app.vault.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import app.vault.api.DiscoverItem
import app.vault.api.DiscoverSource
import app.vault.api.Item
import app.vault.api.ItemFilter
import app.vault.api.SendFormat
import app.vault.api.StageResult
import app.vault.api.VaultApi
import app.vault.sync.Library
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private const val QUICK_LIMIT = 8

enum class Screen { Vault, Discover }

enum class Quick(val label: String, val filter: ItemFilter) {
    All("All", ItemFilter()),
    Animated("Animated", ItemFilter(kind = "animated")),
    Static("Static", ItemFilter(kind = "static")),
    Favorites("Favorites", ItemFilter(favorite = true)),
    Unsorted("Unsorted", ItemFilter(unsorted = true)),
    Small("Under 2 MB", ItemFilter(maxBytes = 2_097_152)),
    Transparent("Transparent", ItemFilter(transparent = true)),
}

/** A file that has been uploaded and is waiting for the person to confirm tags and title. */
class PendingSave(val file: PickedFile?, val stage: StageResult) {
    var title by mutableStateOf(stage.meta?.suggestedTitle ?: "")
    val tags = mutableStateListOf<String>().apply { addAll(stage.autoTags.map { it.name }) }
    val collectionIds = mutableStateListOf<Long>()
}

/** All UI state and the actions on it. Plain Compose snapshot state, no platform dependencies. */
class Controller(
    val api: VaultApi,
    val library: Library,
    private val scope: CoroutineScope,
    val platform: Platform,
) {
    var screen by mutableStateOf(Screen.Vault)
    var quick by mutableStateOf(Quick.All)
    var collectionId by mutableStateOf<Long?>(null)
    var query by mutableStateOf("")
    var results by mutableStateOf<List<Item>>(emptyList())
    var offline by mutableStateOf(false)
    var message by mutableStateOf<String?>(null)
    var selected by mutableStateOf<Item?>(null)
    var similar by mutableStateOf<List<Item>>(emptyList())
    var pending by mutableStateOf<PendingSave?>(null)

    var discoverQuery by mutableStateOf("")
    var discoverSources by mutableStateOf<List<DiscoverSource>>(emptyList())
    val activeSources = mutableStateListOf<String>()
    var animatedOnly by mutableStateOf(false)
    var discoverResults by mutableStateOf<List<DiscoverItem>>(emptyList())
    var discoverHasMore by mutableStateOf(false)
    var discoverPage by mutableStateOf(1)
    var discoverReranked by mutableStateOf(false)
    var discovering by mutableStateOf(false)
    val picks = mutableStateListOf<Long>()
    val saving = mutableStateListOf<String>()

    private var searchJob: Job? = null
    private var quickJob: Job? = null

    /** The desktop quick-search popup keeps its own query so the main window's list is not disturbed. */
    var quickResults by mutableStateOf<List<Item>>(emptyList())

    fun quickSearch(query: String) {
        quickJob?.cancel()
        val local = if (query.isBlank()) library.filtered(ItemFilter()) else library.searchLocal(query, ItemFilter())
        quickResults = local.take(QUICK_LIMIT)
        if (query.isBlank()) return
        quickJob = scope.launch {
            delay(200)
            runCatching { api.search(query, ItemFilter(), limit = QUICK_LIMIT).items }
                .onSuccess { quickResults = it.take(QUICK_LIMIT) }
        }
    }

    /** Sends an item in its most compatible format: the original, or MP4 for clips that are not already one. */
    fun quickSend(item: Item, onDone: (String) -> Unit) {
        val formats = item.sendFormats()
        val format = formats.first()
        scope.launch {
            runCatching {
                val bytes = api.download(format.path)
                platform.sendMedia(bytes, item.mime, (item.title.ifBlank { "reaction" }) + "." + item.formatLabel.lowercase())
            }.onSuccess(onDone).onFailure { onDone(it.message ?: "Could not prepare the file") }
        }
    }

    val filter: ItemFilter get() = quick.filter.copy(collection = collectionId)

    fun start() {
        scope.launch {
            runCatching { discoverSources = api.discoverSources() }
            activeSources.clear()
            activeSources.addAll(discoverSources.map { it.key })
        }
        refresh(sync = true)
    }

    fun toast(text: String) {
        message = text
        scope.launch {
            delay(2500)
            if (message == text) message = null
        }
    }

    /** Re-reads the list. Shows the offline mirror immediately, then replaces it with server results. */
    fun refresh(sync: Boolean = false) {
        searchJob?.cancel()
        results = if (query.isBlank()) library.filtered(filter) else library.searchLocal(query, filter)
        searchJob = scope.launch {
            if (sync) offline = !library.sync()
            if (query.isBlank()) {
                results = library.filtered(filter)
                return@launch
            }
            delay(200)
            runCatching { api.search(query, filter).items }
                .onSuccess { results = it; offline = false }
                .onFailure { offline = true }
        }
    }

    fun select(item: Item?) {
        selected = item
        similar = emptyList()
        if (item != null) scope.launch { runCatching { similar = api.similar(item.id).items } }
    }

    fun setFavorite(item: Item, value: Boolean) = edit(item) { api.updateItem(item.id, favorite = value) }

    fun setTags(item: Item, tags: List<String>) = edit(item) { api.updateItem(item.id, tags = tags) }

    fun setCollections(item: Item, ids: List<Long>) = edit(item) { api.updateItem(item.id, collectionIds = ids) }

    private fun edit(item: Item, call: suspend () -> Item) {
        scope.launch {
            runCatching { call() }
                .onSuccess { updated ->
                    library.upsert(updated)
                    if (selected?.id == updated.id) selected = updated
                    refresh()
                }
                .onFailure { toast(it.message ?: "Could not save the change") }
        }
    }

    fun delete(item: Item) {
        scope.launch {
            runCatching { api.deleteItem(item.id) }
                .onSuccess {
                    library.remove(item.id)
                    if (selected?.id == item.id) selected = null
                    refresh()
                    toast("Deleted")
                }
                .onFailure { toast(it.message ?: "Could not delete") }
        }
    }

    fun send(item: Item, format: SendFormat) {
        scope.launch {
            toast("Preparing ${format.label}…")
            runCatching {
                val bytes = api.download(format.path)
                val mime = when (format.key) {
                    "mp4" -> "video/mp4"
                    "gif" -> "image/gif"
                    else -> item.mime
                }
                val ext = when (format.key) {
                    "original" -> item.formatLabel.lowercase()
                    else -> format.key
                }
                platform.sendMedia(bytes, mime, (item.title.ifBlank { "reaction" }) + "." + ext)
            }.onSuccess { toast(it) }.onFailure { toast(it.message ?: "Could not prepare the file") }
        }
    }

    fun refreshCollections() {
        scope.launch {
            val ok = library.sync()
            if (!ok) toast("Could not reach the server")
            refresh()
        }
    }

    fun createCollection(name: String) {
        scope.launch {
            runCatching { api.createCollection(name) }
                .onSuccess { refreshCollections() }
                .onFailure { toast(it.message ?: "Could not create collection") }
        }
    }

    /* ---- adding ---- */

    fun pickAndStage() {
        scope.launch { platform.pickFiles().forEach { stage(it) } }
    }

    fun stage(file: PickedFile) {
        scope.launch {
            runCatching { api.stage(file.bytes, file.name, file.mime) }
                .onSuccess { handleStage(it, file) }
                .onFailure { toast("${file.name}: ${it.message}") }
        }
    }

    fun stageUrl(url: String) {
        scope.launch {
            runCatching { api.stageUrl(url) }
                .onSuccess { handleStage(it, null) }
                .onFailure { toast(it.message ?: "Could not fetch that URL") }
        }
    }

    private fun handleStage(stage: StageResult, file: PickedFile?) {
        if (stage.duplicate == "exact" && stage.item != null) {
            toast("Already in your vault")
            select(stage.item)
        } else if (stage.stagedId != null) {
            pending = PendingSave(file, stage)
        }
    }

    fun commitPending() {
        val p = pending ?: return
        val id = p.stage.stagedId ?: return
        scope.launch {
            runCatching { api.commit(id, p.title, p.tags.toList(), p.collectionIds.toList()) }
                .onSuccess {
                    pending = null
                    library.upsert(it.item)
                    toast(if (it.duplicate != null) "Already in your vault" else "Saved to Vault")
                    refresh()
                }
                .onFailure { toast(it.message ?: "Could not save") }
        }
    }

    fun cancelPending() {
        val id = pending?.stage?.stagedId
        pending = null
        if (id != null) scope.launch { runCatching { api.discard(id) } }
    }

    /* ---- discover ---- */

    fun discover(reset: Boolean = true) {
        if (discoverQuery.isBlank()) return
        if (reset) {
            discoverPage = 1
            discoverResults = emptyList()
        }
        discovering = true
        scope.launch {
            runCatching {
                api.discover(discoverQuery, activeSources.toList(), animatedOnly, picks.toList(), discoverPage)
            }.onSuccess {
                discoverResults = if (reset) it.items else discoverResults + it.items
                discoverHasMore = it.hasMore
                discoverReranked = it.reranked
            }.onFailure { toast(it.message ?: "Search failed") }
            discovering = false
        }
    }

    fun discoverMore() {
        discoverPage += 1
        discover(reset = false)
    }

    fun saveDiscovered(item: DiscoverItem) {
        val key = item.source + ":" + item.sourceId
        if (key in saving || item.savedItemId != null) return
        saving.add(key)
        scope.launch {
            runCatching { api.discoverSave(item.source, item.sourceId) }
                .onSuccess { r ->
                    library.upsert(r.item)
                    discoverResults = discoverResults.map {
                        if (it.source == item.source && it.sourceId == item.sourceId) it.copy(savedItemId = r.item.id) else it
                    }
                    toast(if (r.duplicate != null) "Already in your vault" else "Saved to Vault")
                    refresh()
                }
                .onFailure { toast(it.message ?: "Could not save") }
            saving.remove(key)
        }
    }

    fun togglePick(id: Long) {
        if (id in picks) picks.remove(id) else picks.add(id)
    }
}
