package app.vault.ui

import java.util.Base64
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull

class AnimatedTest {
    // Three 16x16 lossless frames (red, blue, green), 80 ms each.
    private val webp = "UklGRrQAAABXRUJQVlA4WAoAAAACAAAADwAADwAAQU5JTQYAAAAAAAAAAABBTk1GKAAAAAAAAAAAAA8AAA8AAFAAAAJWUDhMDwAAAC8PwAMABxD9j/4HIqL/AQBBTk1GKAAAAAAAAAAAAA8AAA8AAFAAAABWUDhMDwAAAC8PwAMABxDR//4HIqL/AQBBTk1GKAAAAAAAAAAAAA8AAA8AAFAAAABWUDhMDwAAAC8PwAMAB1DAiP4HIqL/AQA="

    @Test
    fun decodesEveryFrameOfAnAnimatedWebp() {
        val frames = assertNotNull(decodeFrames(Base64.getDecoder().decode(webp)))
        assertEquals(3, frames.images.size)
        assertEquals(listOf(80, 80, 80), frames.durations)
    }

    @Test
    fun staticImagesDecodeToNull() {
        val png = Base64.getDecoder().decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
        )
        assertEquals(null, decodeFrames(png))
    }
}
