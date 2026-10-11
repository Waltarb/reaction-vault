package app.vault.api

import io.ktor.client.HttpClient
import io.ktor.client.call.body
import io.ktor.client.engine.HttpClientEngine
import io.ktor.client.plugins.HttpTimeout
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.client.plugins.defaultRequest
import io.ktor.client.request.delete
import io.ktor.client.request.forms.formData
import io.ktor.client.request.forms.submitFormWithBinaryData
import io.ktor.client.request.get
import io.ktor.client.request.header
import io.ktor.client.request.parameter
import io.ktor.client.request.patch
import io.ktor.client.request.post
import io.ktor.client.request.setBody
import io.ktor.client.statement.HttpResponse
import io.ktor.client.statement.bodyAsText
import io.ktor.http.ContentType
import io.ktor.http.Headers
import io.ktor.http.HttpHeaders
import io.ktor.http.contentType
import io.ktor.http.isSuccess
import io.ktor.serialization.kotlinx.json.json
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

val VaultJson = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
    encodeDefaults = false
}

class ApiException(val status: Int, message: String) : Exception(message)

@Serializable
private data class ErrorBody(val detail: String? = null)

@Serializable
private data class PatchBody(
    val title: String? = null,
    val favorite: Boolean? = null,
    val tags: List<String>? = null,
    @kotlinx.serialization.SerialName("collection_ids") val collectionIds: List<Long>? = null,
)

@Serializable
private data class CommitBody(
    val title: String? = null,
    val tags: List<String>? = null,
    @kotlinx.serialization.SerialName("collection_ids") val collectionIds: List<Long> = emptyList(),
)

@Serializable
private data class SaveBody(
    val source: String,
    @kotlinx.serialization.SerialName("source_id") val sourceId: String,
    val tags: List<String>? = null,
    @kotlinx.serialization.SerialName("collection_ids") val collectionIds: List<Long> = emptyList(),
)

@Serializable
private data class NameBody(val name: String, val color: String? = null)

/** Typed client for the Reaction Vault server. All calls are suspending and throw [ApiException]. */
class VaultApi(
    baseUrl: String,
    private val token: String,
    engine: HttpClientEngine,
) {
    val baseUrl: String = baseUrl.trim().trimEnd('/')

    val http: HttpClient = HttpClient(engine) {
        install(ContentNegotiation) { json(VaultJson) }
        install(HttpTimeout) {
            requestTimeoutMillis = 120_000
            connectTimeoutMillis = 10_000
        }
        defaultRequest {
            if (token.isNotBlank()) header(HttpHeaders.Authorization, "Bearer $token")
        }
    }

    fun absolute(path: String): String =
        if (path.startsWith("http://") || path.startsWith("https://")) path else baseUrl + path

    private suspend fun HttpResponse.check(): HttpResponse {
        if (status.isSuccess()) return this
        val detail = runCatching { VaultJson.decodeFromString(ErrorBody.serializer(), bodyAsText()).detail }.getOrNull()
        throw ApiException(status.value, detail ?: "${status.value} ${status.description}")
    }

    suspend fun serverInfo(): ServerInfo = http.get(absolute("/api/server")).check().body()

    suspend fun items(filter: ItemFilter = ItemFilter(), cursor: Long? = null, limit: Int = 60): ItemsPage =
        http.get(absolute("/api/items")) {
            filterParams(filter)
            cursor?.let { parameter("cursor", it) }
            parameter("limit", limit)
        }.check().body()

    suspend fun search(q: String, filter: ItemFilter = ItemFilter(), offset: Int = 0, limit: Int = 60): SearchPage =
        http.get(absolute("/api/search")) {
            parameter("q", q)
            filterParams(filter)
            parameter("offset", offset)
            parameter("limit", limit)
        }.check().body()

    suspend fun similar(id: Long, limit: Int = 12): SearchPage =
        http.get(absolute("/api/items/$id/similar")) { parameter("limit", limit) }.check().body()

    suspend fun item(id: Long): Item = http.get(absolute("/api/items/$id")).check().body()

    suspend fun updateItem(
        id: Long,
        title: String? = null,
        favorite: Boolean? = null,
        tags: List<String>? = null,
        collectionIds: List<Long>? = null,
    ): Item = http.patch(absolute("/api/items/$id")) {
        contentType(ContentType.Application.Json)
        setBody(PatchBody(title, favorite, tags, collectionIds))
    }.check().body()

    suspend fun deleteItem(id: Long) {
        http.delete(absolute("/api/items/$id")).check()
    }

    suspend fun collections(): List<VaultCollection> = http.get(absolute("/api/collections")).check().body()

    suspend fun createCollection(name: String, color: String? = null): VaultCollection =
        http.post(absolute("/api/collections")) {
            contentType(ContentType.Application.Json)
            setBody(NameBody(name, color))
        }.check().body()

    suspend fun deleteCollection(id: Long) {
        http.delete(absolute("/api/collections/$id")).check()
    }

    suspend fun sync(since: Long, limit: Int = 500): SyncResponse =
        http.get(absolute("/api/sync")) {
            parameter("since", since)
            parameter("limit", limit)
        }.check().body()

    /** Step one of saving: upload bytes, get metadata, suggested tags and near-duplicates back. */
    suspend fun stage(bytes: ByteArray, fileName: String, mime: String): StageResult =
        http.submitFormWithBinaryData(
            url = absolute("/api/ingest"),
            formData = formData {
                append("file", bytes, Headers.build {
                    append(HttpHeaders.ContentType, mime)
                    append(HttpHeaders.ContentDisposition, "filename=\"${fileName.replace("\"", "")}\"")
                })
            },
        ).check().body()

    suspend fun stageUrl(url: String): StageResult =
        http.submitFormWithBinaryData(
            url = absolute("/api/ingest"),
            formData = formData { append("url", url) },
        ).check().body()

    suspend fun commit(
        stagedId: String,
        title: String? = null,
        tags: List<String>? = null,
        collectionIds: List<Long> = emptyList(),
    ): CommitResult = http.post(absolute("/api/ingest/$stagedId/commit")) {
        contentType(ContentType.Application.Json)
        setBody(CommitBody(title, tags, collectionIds))
    }.check().body()

    suspend fun discard(stagedId: String) {
        http.delete(absolute("/api/ingest/$stagedId")).check()
    }

    suspend fun discoverSources(): List<DiscoverSource> = http.get(absolute("/api/discover/sources")).check().body()

    suspend fun discover(
        q: String,
        sources: List<String> = emptyList(),
        animatedOnly: Boolean = false,
        similarTo: List<Long> = emptyList(),
        page: Int = 1,
    ): DiscoverPage = http.get(absolute("/api/discover/search")) {
        parameter("q", q)
        if (sources.isNotEmpty()) parameter("sources", sources.joinToString(","))
        if (animatedOnly) parameter("animated", true)
        if (similarTo.isNotEmpty()) parameter("similar_to", similarTo.joinToString(","))
        parameter("page", page)
    }.check().body()

    suspend fun discoverSave(source: String, sourceId: String): CommitResult =
        http.post(absolute("/api/discover/save")) {
            contentType(ContentType.Application.Json)
            setBody(SaveBody(source, sourceId))
        }.check().body()

    /** Raw bytes of a media path such as `/media/12/send/mp4`, for copying or sharing. */
    suspend fun download(path: String): ByteArray = http.get(absolute(path)).check().body()

    private fun io.ktor.client.request.HttpRequestBuilder.filterParams(f: ItemFilter) {
        f.kind?.let { parameter("kind", it) }
        if (f.favorite) parameter("favorite", true)
        if (f.unsorted) parameter("unsorted", true)
        f.collection?.let { parameter("collection", it) }
        f.tag?.let { parameter("tag", it) }
        f.maxBytes?.let { parameter("max_bytes", it) }
        if (f.transparent) parameter("transparent", true)
    }
}
