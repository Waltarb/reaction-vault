package app.vault.ui

import android.os.Build
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import coil3.ImageLoader
import coil3.compose.AsyncImage
import coil3.gif.AnimatedImageDecoder
import coil3.gif.GifDecoder
import io.ktor.client.HttpClient

actual fun ImageLoader.Builder.withAnimatedImages(): ImageLoader.Builder = components {
    if (Build.VERSION.SDK_INT >= 28) add(AnimatedImageDecoder.Factory()) else add(GifDecoder.Factory())
}

@Composable
actual fun AnimatedImage(url: String, loader: ImageLoader, http: HttpClient, modifier: Modifier) {
    AsyncImage(url, contentDescription = null, imageLoader = loader, contentScale = ContentScale.Fit, modifier = modifier)
}
