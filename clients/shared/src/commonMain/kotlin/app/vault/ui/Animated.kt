package app.vault.ui

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import coil3.ImageLoader
import io.ktor.client.HttpClient

/** Teaches Coil to decode animated GIF and WebP where the platform decoder can do it. */
expect fun ImageLoader.Builder.withAnimatedImages(): ImageLoader.Builder

/**
 * Shows [url] and plays it when it is an animated GIF or WebP. Android animates through Coil's
 * decoder; the desktop has no such decoder, so it decodes the frames with Skia itself.
 */
@Composable
expect fun AnimatedImage(url: String, loader: ImageLoader, http: HttpClient, modifier: Modifier)
