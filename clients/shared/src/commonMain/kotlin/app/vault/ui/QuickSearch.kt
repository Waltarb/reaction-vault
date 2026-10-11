package app.vault.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil3.ImageLoader
import coil3.compose.AsyncImage

/** Whether the quick-search popup is showing. The host app flips it from a hotkey or tray icon. */
class QuickSearchHandle {
    var visible by mutableStateOf(false)
    fun toggle() { visible = !visible }
    fun hide() { visible = false }
}

/**
 * Hosts supply a way to show [content] in their own floating window.
 * Android has none, so it passes null and the popup never appears.
 */
typealias QuickWindow = @Composable (content: @Composable () -> Unit) -> Unit

/** Type, arrow to a result, Enter copies it as a file and closes. Esc closes. */
@Composable
fun QuickSearchPanel(c: Controller, loader: ImageLoader, onClose: () -> Unit) {
    var query by remember { mutableStateOf("") }
    var index by remember { mutableStateOf(0) }
    var note by remember { mutableStateOf<String?>(null) }
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) { c.quickSearch(""); focus.requestFocus() }
    LaunchedEffect(c.quickResults) { index = index.coerceIn(0, (c.quickResults.size - 1).coerceAtLeast(0)) }

    fun send(i: Int) {
        val item = c.quickResults.getOrNull(i) ?: return
        note = "Preparing…"
        c.quickSend(item) { msg -> note = msg; onClose() }
    }

    Column(
        Modifier.fillMaxSize().background(Palette.Surface).border(BorderStroke(1.dp, Palette.Border), RoundedCornerShape(18.dp))
            .padding(16.dp)
            .onPreviewKeyEvent { e ->
                if (e.type != KeyEventType.KeyDown) return@onPreviewKeyEvent false
                when (e.key) {
                    Key.Escape -> { onClose(); true }
                    Key.Enter, Key.NumPadEnter -> { send(index); true }
                    Key.DirectionRight -> { index = (index + 1).coerceAtMost(c.quickResults.size - 1).coerceAtLeast(0); true }
                    Key.DirectionLeft -> { index = (index - 1).coerceAtLeast(0); true }
                    else -> false
                }
            },
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        OutlinedTextField(
            query, { query = it; index = 0; c.quickSearch(it) }, singleLine = true,
            modifier = Modifier.fillMaxWidth().focusRequester(focus),
            placeholder = { Text("Find a reaction…  Enter copies it") },
            shape = RoundedCornerShape(14.dp),
        )
        if (c.quickResults.isEmpty()) {
            Box(Modifier.fillMaxWidth().padding(vertical = 24.dp), contentAlignment = Alignment.Center) {
                Text(if (query.isBlank()) "Your vault is empty." else "Nothing matched.", color = Palette.Muted)
            }
        } else {
            LazyRow(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                itemsIndexed(c.quickResults, key = { _, it -> it.id }) { i, item ->
                    Column(
                        Modifier.size(width = 112.dp, height = 128.dp).clip(RoundedCornerShape(14.dp))
                            .background(if (i == index) Palette.Raised else Palette.Bg)
                            .border(BorderStroke(if (i == index) 2.dp else 1.dp, if (i == index) Palette.Accent else Palette.Border),
                                RoundedCornerShape(14.dp))
                            .clickable { index = i; send(i) }.padding(6.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        AsyncImage(c.api.absolute(item.urls.thumb ?: item.urls.original), null, imageLoader = loader,
                            contentScale = ContentScale.Fit, modifier = Modifier.fillMaxWidth().size(88.dp))
                        Text(item.title.ifBlank { "Untitled" }, fontSize = 11.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
                            fontWeight = FontWeight.Medium)
                    }
                }
            }
        }
        note?.let { Text(it, color = Palette.Muted, fontSize = 12.sp) }
    }
}
