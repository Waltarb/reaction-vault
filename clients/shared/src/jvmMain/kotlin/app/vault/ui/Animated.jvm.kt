package app.vault.ui

import androidx.compose.foundation.Image
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.toComposeImageBitmap
import androidx.compose.ui.layout.ContentScale
import coil3.ImageLoader
import coil3.compose.AsyncImage
import io.ktor.client.HttpClient
import io.ktor.client.request.get
import io.ktor.client.statement.readRawBytes
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import org.jetbrains.skia.Bitmap
import org.jetbrains.skia.Codec
import org.jetbrains.skia.Data
import org.jetbrains.skia.Image as SkiaImage

// Previews are small (a few hundred pixels), so holding every frame decoded is cheap; the cap
// keeps a pathological file from exhausting memory.
private const val MAX_FRAMES = 150
private const val MIN_FRAME_MS = 20

actual fun ImageLoader.Builder.withAnimatedImages(): ImageLoader.Builder = this

internal class Frames(val images: List<ImageBitmap>, val durations: List<Int>)

internal fun decodeFrames(bytes: ByteArray): Frames? {
    val codec = Codec.makeFromData(Data.makeFromBytes(bytes))
    try {
        if (codec.frameCount <= 1) return null
        val count = minOf(codec.frameCount, MAX_FRAMES)
        val images = ArrayList<ImageBitmap>(count)
        val durations = ArrayList<Int>(count)
        val info = codec.framesInfo
        for (i in 0 until count) {
            val bitmap = Bitmap()
            bitmap.allocPixels(codec.imageInfo)
            codec.readPixels(bitmap, i)
            images += SkiaImage.makeFromBitmap(bitmap).toComposeImageBitmap()
            durations += maxOf(info[i].duration, MIN_FRAME_MS)
        }
        return if (images.size > 1) Frames(images, durations) else null
    } finally {
        codec.close()
    }
}

@Composable
actual fun AnimatedImage(url: String, loader: ImageLoader, http: HttpClient, modifier: Modifier) {
    var frames by remember(url) { mutableStateOf<Frames?>(null) }
    LaunchedEffect(url) {
        frames = withContext(Dispatchers.Default) {
            runCatching { decodeFrames(http.get(url).readRawBytes()) }.getOrNull()
        }
    }
    val f = frames
    if (f == null) {
        AsyncImage(url, contentDescription = null, imageLoader = loader, contentScale = ContentScale.Fit, modifier = modifier)
        return
    }
    var index by remember(f) { mutableStateOf(0) }
    LaunchedEffect(f) {
        while (true) {
            delay(f.durations[index].toLong())
            index = (index + 1) % f.images.size
        }
    }
    Image(f.images[index], contentDescription = null, contentScale = ContentScale.Fit, modifier = modifier)
}
