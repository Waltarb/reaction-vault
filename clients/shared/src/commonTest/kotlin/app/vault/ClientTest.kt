package app.vault

import app.vault.api.ApiException
import app.vault.api.ItemFilter
import app.vault.api.VaultApi
import app.vault.sync.Library
import app.vault.sync.MemoryStorage
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

private val json = headersOf(HttpHeaders.ContentType, "application/json")

private fun itemJson(id: Int, title: String, extra: String = "", kind: String = "image", mime: String = "image/png") =
    """{"id":$id,"sha256":"x$id","title":"$title","kind":"$kind","mime":"$mime","width":10,"height":10,
    "bytes":1000,"favorite":false,"source":"upload","created_at":"","updated_at":"","rev":$id,
    "tags":[{"name":"frog","origin":"manual","score":null}],"collection_ids":[],"renditions":{},
    "urls":{"original":"/media/$id/original","thumb":"/media/$id/thumb"}$extra}"""

class ClientTest {
    @Test
    fun sendsBearerTokenAndDecodesItems() = runTest {
        var auth: String? = null
        val engine = MockEngine { req ->
            auth = req.headers[HttpHeaders.Authorization]
            respond("""{"items":[${itemJson(2, "smug frog")}],"next_cursor":1}""", HttpStatusCode.OK, json)
        }
        val api = VaultApi("https://vault.example/", "secret", engine)
        val page = api.items(ItemFilter(kind = "animated", favorite = true))
        assertEquals("Bearer secret", auth)
        assertEquals(1L, page.nextCursor)
        assertEquals("smug frog", page.items.single().title)
        assertEquals("frog", page.items.single().tags.single().name)
    }

    @Test
    fun filterBecomesQueryParameters() = runTest {
        var url = ""
        val engine = MockEngine { req ->
            url = req.url.toString()
            respond("""{"items":[]}""", HttpStatusCode.OK, json)
        }
        VaultApi("https://v", "t", engine)
            .items(ItemFilter(kind = "static", unsorted = true, collection = 3, maxBytes = 2_097_152), cursor = 9)
        for (part in listOf("kind=static", "unsorted=true", "collection=3", "max_bytes=2097152", "cursor=9")) {
            assertTrue(url.contains(part), "$part missing from $url")
        }
        assertFalse(url.contains("favorite"))
    }

    @Test
    fun serverErrorsBecomeApiExceptionWithDetail() = runTest {
        val engine = MockEngine { respond("""{"detail":"item not found"}""", HttpStatusCode.NotFound, json) }
        val e = assertFailsWith<ApiException> { VaultApi("https://v", "t", engine).item(5) }
        assertEquals(404, e.status)
        assertEquals("item not found", e.message)
    }

    @Test
    fun sendFormatsListOriginalFirstAndSkipPassthrough() = runTest {
        val engine = MockEngine {
            respond(itemJson(4, "gif", kind = "animated", mime = "image/gif"), HttpStatusCode.OK, json)
        }
        val item = VaultApi("https://v", "t", engine).item(4)
        assertEquals(listOf("original", "mp4"), item.sendFormats().map { it.key })
    }

    @Test
    fun syncAppliesChangesAndTombstonesAndPersists() = runTest {
        val pages = ArrayDeque(
            listOf(
                """{"rev":2,"has_more":true,"items":[${itemJson(1, "one")}],"collections":[]}""",
                """{"rev":3,"has_more":false,"items":[${itemJson(2, "two")}],"collections":[{"id":7,"name":"Frogs","rev":3}]}""",
                """{"rev":5,"has_more":false,"items":[{"id":1,"deleted":true,"rev":5}],"collections":[]}""",
            ),
        )
        val seenSince = mutableListOf<String?>()
        val engine = MockEngine { req ->
            seenSince += req.url.parameters["since"]
            respond(pages.removeFirst(), HttpStatusCode.OK, json)
        }
        val storage = MemoryStorage()
        val lib = Library(VaultApi("https://v", "t", engine), storage)

        assertTrue(lib.sync())
        assertEquals(listOf<String?>("0", "2"), seenSince)
        assertEquals(listOf(2L, 1L), lib.state.value.ordered.map { it.id })
        assertEquals("Frogs", lib.state.value.collections.getValue(7).name)
        assertEquals(3L, lib.state.value.rev)

        assertTrue(lib.sync())
        assertNull(lib.state.value.items[1L])
        assertEquals(5L, lib.state.value.rev)

        // A fresh instance restores the offline copy without touching the network.
        val offline = Library(VaultApi("https://v", "t", MockEngine { respond("", HttpStatusCode.ServiceUnavailable) }), storage)
        assertEquals(listOf(2L), offline.state.value.ordered.map { it.id })
        assertEquals(listOf(2L), offline.searchLocal("two frog").map { it.id })
        assertTrue(offline.searchLocal("cat").isEmpty())
    }

    @Test
    fun failedSyncKeepsLocalCopyAndReportsError() = runTest {
        val storage = MemoryStorage()
        val ok = MockEngine { respond("""{"rev":1,"items":[${itemJson(1, "one")}],"collections":[]}""", HttpStatusCode.OK, json) }
        Library(VaultApi("https://v", "t", ok), storage).sync()

        val down = MockEngine { respond("nope", HttpStatusCode.BadGateway) }
        val lib = Library(VaultApi("https://v", "t", down), storage)
        assertFalse(lib.sync())
        assertEquals(1, lib.state.value.items.size)
        assertTrue(lib.state.value.lastSyncError != null)
    }
}
