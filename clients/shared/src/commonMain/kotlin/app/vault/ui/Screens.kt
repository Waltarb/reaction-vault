@file:OptIn(ExperimentalLayoutApi::class, ExperimentalMaterial3Api::class)

package app.vault.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import app.vault.api.DiscoverItem
import app.vault.api.Item
import app.vault.api.VaultApi
import app.vault.sync.Library
import androidx.compose.foundation.hoverable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsHoveredAsState
import coil3.ImageLoader
import io.ktor.client.HttpClient
import coil3.compose.AsyncImage
import coil3.compose.LocalPlatformContext
import coil3.network.ktor3.KtorNetworkFetcherFactory
import io.ktor.client.engine.HttpClientEngine
import kotlinx.coroutines.launch

@androidx.compose.runtime.Composable
fun VaultApp(
    platform: Platform,
    engine: () -> HttpClientEngine,
    quickSearch: QuickSearchHandle? = null,
    quickWindow: QuickWindow? = null,
) {
    VaultTheme {
        Surface(Modifier.fillMaxSize(), color = Palette.Bg) {
            var connection by remember { mutableStateOf(platform.loadConnection()) }
            val c = connection
            if (c == null) {
                LoginScreen(engine) { conn ->
                    platform.saveConnection(conn)
                    connection = conn
                }
            } else {
                androidx.compose.runtime.key(c) {
                    MainScreen(platform, c, engine, quickSearch, quickWindow) {
                        platform.saveConnection(null)
                        connection = null
                    }
                }
            }
        }
    }
}

@Composable
private fun LoginScreen(engine: () -> HttpClientEngine, onConnected: (Connection) -> Unit) {
    var url by remember { mutableStateOf("") }
    var token by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    Box(Modifier.fillMaxSize().padding(24.dp), contentAlignment = Alignment.Center) {
        Column(Modifier.width(380.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Text("Vault", fontSize = 32.sp, fontWeight = FontWeight.Bold)
            Text("Connect to your Reaction Vault server.", color = Palette.Muted)
            OutlinedTextField(
                url, { url = it }, label = { Text("Server address") }, singleLine = true,
                placeholder = { Text("https://vault.example.com") }, modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                token, { token = it }, label = { Text("Device token") }, singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            error?.let { Text(it, color = Palette.Danger) }
            Button(
                enabled = !busy && url.isNotBlank(),
                modifier = Modifier.fillMaxWidth().height(48.dp),
                onClick = {
                    busy = true
                    error = null
                    val address = url.trim().let { if ("://" in it) it else "https://$it" }
                    scope.launch {
                        val api = VaultApi(address, token.trim(), engine())
                        runCatching { api.serverInfo() }
                            .onSuccess { onConnected(Connection(address, token.trim())) }
                            .onFailure { error = it.message ?: "Could not connect" }
                        busy = false
                    }
                },
            ) { Text(if (busy) "Connecting…" else "Connect") }
        }
    }
}

@Composable
private fun MainScreen(
    platform: Platform, connection: Connection, engine: () -> HttpClientEngine,
    quickSearch: QuickSearchHandle?, quickWindow: QuickWindow?, onSignOut: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val api = remember(connection) { VaultApi(connection.serverUrl, connection.token, engine()) }
    val library = remember(api) { Library(api, platform.libraryStorage) }
    val controller = remember(api) { Controller(api, library, scope, platform) }
    val context = LocalPlatformContext.current
    val loader = remember(api) {
        ImageLoader.Builder(context).components { add(KtorNetworkFetcherFactory(api.http)) }.withAnimatedImages().build()
    }
    LaunchedEffect(controller) { controller.start() }
    LaunchedEffect(controller) { platform.incoming.collect { controller.stage(it) } }
    LaunchedEffect(controller) { platform.incomingUrls.collect { controller.stageUrl(it) } }

    BoxWithConstraints(Modifier.fillMaxSize()) {
        val wide = maxWidth >= 900.dp
        Column(Modifier.fillMaxSize()) {
            Row(Modifier.weight(1f).fillMaxWidth()) {
                if (wide) Sidebar(controller, library, onSignOut)
                Box(Modifier.weight(1f).fillMaxHeight()) {
                    when (controller.screen) {
                        Screen.Vault -> VaultContent(controller, loader, compactNav = !wide)
                        Screen.Discover -> DiscoverContent(controller, loader, compactNav = !wide)
                    }
                    controller.message?.let {
                        Surface(
                            Modifier.align(Alignment.BottomCenter).padding(20.dp),
                            shape = RoundedCornerShape(14.dp), color = Palette.Raised,
                            border = BorderStroke(1.dp, Palette.Border),
                        ) { Text(it, Modifier.padding(horizontal = 18.dp, vertical = 12.dp)) }
                    }
                }
                val item = controller.selected
                if (wide && item != null) {
                    Box(Modifier.width(360.dp).fillMaxHeight().background(Palette.Side)) {
                        DetailPanel(controller, item, loader)
                    }
                }
            }
        }
        val item = controller.selected
        if (!wide && item != null) {
            Dialog(onDismissRequest = { controller.select(null) }) {
                Surface(shape = RoundedCornerShape(22.dp), color = Palette.Surface) {
                    DetailPanel(controller, item, loader)
                }
            }
        }
        controller.pending?.let { SaveDialog(controller, it, loader) }
        if (quickSearch != null && quickWindow != null && quickSearch.visible) {
            quickWindow { QuickSearchPanel(controller, loader) { quickSearch.hide() } }
        }
    }
}

/* ------------------------------------------------------------------ sidebar */

@Composable
private fun Sidebar(c: Controller, library: Library, onSignOut: () -> Unit) {
    val state = library.state.value
    var newName by remember { mutableStateOf<String?>(null) }
    Column(
        Modifier.width(232.dp).fillMaxHeight().background(Palette.Side).padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        Text("Vault", fontSize = 26.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(10.dp, 6.dp, 10.dp, 16.dp))
        val all = state.ordered
        NavRow("All items", all.size, c.screen == Screen.Vault && c.quick == Quick.All && c.collectionId == null) {
            c.screen = Screen.Vault; c.quick = Quick.All; c.collectionId = null; c.refresh()
        }
        NavRow("Favorites", all.count { it.favorite }, c.screen == Screen.Vault && c.quick == Quick.Favorites) {
            c.screen = Screen.Vault; c.quick = Quick.Favorites; c.collectionId = null; c.refresh()
        }
        NavRow("Unsorted", all.count { it.collectionIds.isEmpty() }, c.screen == Screen.Vault && c.quick == Quick.Unsorted) {
            c.screen = Screen.Vault; c.quick = Quick.Unsorted; c.collectionId = null; c.refresh()
        }
        NavRow("Discover", null, c.screen == Screen.Discover) { c.screen = Screen.Discover }

        Text(
            "COLLECTIONS", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Palette.Muted,
            modifier = Modifier.padding(10.dp, 18.dp, 10.dp, 6.dp),
        )
        LazyColumn(Modifier.weight(1f)) {
            items(state.collections.values.sortedBy { it.name }) { col ->
                val count = all.count { col.id in it.collectionIds }
                NavRow(col.name, count, c.screen == Screen.Vault && c.collectionId == col.id) {
                    c.screen = Screen.Vault; c.quick = Quick.All; c.collectionId = col.id; c.refresh()
                }
            }
            item {
                val editing = newName
                if (editing == null) {
                    TextButton(onClick = { newName = "" }) { Text("+ New collection", color = Palette.Muted) }
                } else {
                    OutlinedTextField(
                        editing, { newName = it }, singleLine = true, placeholder = { Text("Name") },
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                        keyboardActions = KeyboardActions(onDone = {
                            if (editing.isNotBlank()) c.createCollection(editing.trim())
                            newName = null
                        }),
                    )
                }
            }
        }
        Card(colors = CardDefaults.cardColors(containerColor = Palette.Surface)) {
            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                val ok = state.lastSyncError == null && !c.offline
                Text(if (ok) "● Server online" else "● Offline", fontWeight = FontWeight.SemiBold,
                    color = if (ok) Palette.Accent else Palette.Danger, fontSize = 14.sp)
                Text("${all.size} items", color = Palette.Muted, fontSize = 12.sp)
                Text(if (state.syncing) "Syncing…" else "Synced", color = Palette.Muted, fontSize = 12.sp)
                TextButton(onClick = onSignOut, contentPadding = PaddingValues(0.dp)) {
                    Text("Sign out", color = Palette.Muted, fontSize = 12.sp)
                }
            }
        }
    }
}

@Composable
private fun NavRow(label: String, count: Int?, selected: Boolean, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().height(40.dp).clip(RoundedCornerShape(10.dp))
            .background(if (selected) Palette.Raised else Color.Transparent)
            .clickable(onClick = onClick).padding(horizontal = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, Modifier.weight(1f), fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
            maxLines = 1, overflow = TextOverflow.Ellipsis)
        if (count != null) Text(count.toString(), color = Palette.Muted, fontSize = 12.sp)
    }
}

/* ------------------------------------------------------------------- vault */

@Composable
private fun VaultContent(c: Controller, loader: ImageLoader, compactNav: Boolean) {
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.padding(16.dp, 16.dp, 16.dp, 8.dp), horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                c.query, { c.query = it; c.refresh() }, singleLine = true, modifier = Modifier.weight(1f),
                placeholder = { Text("Search by vibe: smug frog, coping…") },
                shape = RoundedCornerShape(14.dp),
            )
            Button(onClick = { c.pickAndStage() }, modifier = Modifier.height(54.dp), shape = RoundedCornerShape(14.dp)) {
                Text("+ Add", fontWeight = FontWeight.SemiBold)
            }
        }
        if (compactNav) CompactNav(c)
        LazyRow(contentPadding = PaddingValues(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            items(Quick.entries.toList()) { q ->
                FilterChip(selected = c.quick == q, onClick = { c.quick = q; c.refresh() }, label = { Text(q.label) })
            }
        }
        Row(Modifier.fillMaxWidth().padding(16.dp, 12.dp, 16.dp, 8.dp), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(if (c.query.isBlank()) "Recently saved" else "Results", fontWeight = FontWeight.SemiBold, fontSize = 17.sp)
            if (c.offline) Text("Offline copy", color = Palette.Danger, fontSize = 13.sp)
        }
        if (c.results.isEmpty()) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text(if (c.query.isBlank()) "Nothing here yet. Add an image or try Discover." else "Nothing matched.",
                    color = Palette.Muted)
            }
        } else {
            LazyVerticalGrid(
                GridCells.Adaptive(132.dp), contentPadding = PaddingValues(16.dp, 0.dp, 16.dp, 24.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                items(c.results, key = { it.id }) { item ->
                    Tile(c.api.absolute(item.urls.thumb ?: item.urls.original), item.formatLabel, loader,
                        selected = c.selected?.id == item.id, http = c.api.http,
                        animatedUrl = item.urls.preview?.let { c.api.absolute(it) }) { c.select(item) }
                }
            }
        }
    }
}

@Composable
private fun CompactNav(c: Controller) {
    Row(Modifier.padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        FilterChip(selected = c.screen == Screen.Vault, onClick = { c.screen = Screen.Vault }, label = { Text("Vault") })
        FilterChip(selected = c.screen == Screen.Discover, onClick = { c.screen = Screen.Discover }, label = { Text("Discover") })
    }
}

@Composable
private fun Tile(url: String, badge: String, loader: ImageLoader, selected: Boolean, overlay: @Composable (() -> Unit)? = null,
                 http: HttpClient, animatedUrl: String? = null, onClick: () -> Unit) {
    val hover = remember { MutableInteractionSource() }
    val hovered by hover.collectIsHoveredAsState()
    Box(
        Modifier.fillMaxWidth().aspectRatio(1f).clip(RoundedCornerShape(14.dp)).background(Palette.Surface)
            .then(if (selected) Modifier.background(Palette.Raised) else Modifier)
            .hoverable(hover)
            .clickable(onClick = onClick),
    ) {
        if (hovered && animatedUrl != null) {
            AnimatedImage(animatedUrl, loader, http, Modifier.fillMaxSize())
        } else {
            AsyncImage(url, contentDescription = null, imageLoader = loader, contentScale = ContentScale.Fit,
                modifier = Modifier.fillMaxSize())
        }
        Text(
            badge, fontSize = 10.sp, fontWeight = FontWeight.SemiBold,
            modifier = Modifier.align(Alignment.TopEnd).padding(6.dp).clip(RoundedCornerShape(6.dp))
                .background(Color(0xD914151A)).padding(horizontal = 6.dp, vertical = 2.dp),
        )
        overlay?.invoke()
    }
}

/* ------------------------------------------------------------------ detail */

@Composable
private fun DetailPanel(c: Controller, item: Item, loader: ImageLoader) {
    var format by remember(item.id) { mutableStateOf("original") }
    var newTag by remember(item.id) { mutableStateOf("") }
    val formats = item.sendFormats()
    val chosen = formats.firstOrNull { it.key == format } ?: formats.first()
    LazyColumn(Modifier.fillMaxSize().padding(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        item {
            Box(Modifier.fillMaxWidth().height(240.dp).clip(RoundedCornerShape(18.dp)).background(Palette.Bg)) {
                AnimatedImage(c.api.absolute(item.urls.preview ?: item.urls.thumb ?: item.urls.original), loader,
                    c.api.http, Modifier.fillMaxSize())
            }
        }
        item {
            Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                Text(item.title.ifBlank { "Untitled" }, fontSize = 22.sp, fontWeight = FontWeight.Bold)
                Text("${item.width}×${item.height} · ${formatBytes(item.bytes)} · ${item.formatLabel}" +
                    if (item.source != "upload") " · from ${item.source}" else "", color = Palette.Muted, fontSize = 13.sp)
            }
        }
        item {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                item.tags.forEach { t ->
                    FilterChip(selected = t.origin == "auto", onClick = {
                        c.setTags(item, item.tags.map { it.name } - t.name)
                    }, label = { Text("${t.name}  ×") })
                }
            }
            OutlinedTextField(
                newTag, { newTag = it }, singleLine = true, placeholder = { Text("+ tag") },
                modifier = Modifier.fillMaxWidth().padding(top = 6.dp),
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = {
                    if (newTag.isNotBlank()) c.setTags(item, item.tags.map { it.name } + newTag.trim())
                    newTag = ""
                }),
            )
        }
        item {
            Text("SEND AS", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Palette.Muted)
            Row(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                formats.forEach { f ->
                    val on = f.key == chosen.key
                    Surface(
                        Modifier.weight(1f).height(56.dp).clickable { format = f.key },
                        shape = RoundedCornerShape(14.dp),
                        color = if (on) Palette.Accent else Palette.Surface,
                        border = if (on) null else BorderStroke(1.dp, Palette.Border),
                    ) {
                        Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.Center,
                            horizontalAlignment = Alignment.CenterHorizontally) {
                            Text(if (f.key == "original") "Original" else f.label, fontWeight = FontWeight.SemiBold,
                                color = if (on) Palette.OnAccent else Palette.Text)
                            Text(f.bytes?.let { formatBytes(it) } ?: "on first use", fontSize = 11.sp,
                                color = if (on) Palette.OnAccent else Palette.Muted)
                        }
                    }
                }
            }
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { c.send(item, chosen) }, modifier = Modifier.weight(1f).height(48.dp),
                    shape = RoundedCornerShape(14.dp)) {
                    Text(if (c.platform.name == "Android") "Share" else "Copy", fontWeight = FontWeight.SemiBold)
                }
                OutlinedButton(onClick = { c.setFavorite(item, !item.favorite) }, modifier = Modifier.height(48.dp),
                    shape = RoundedCornerShape(14.dp)) { Text(if (item.favorite) "★" else "☆") }
            }
        }
        if (c.library.state.value.collections.isNotEmpty()) {
            item {
                Text("COLLECTIONS", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Palette.Muted)
                FlowRow(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    c.library.state.value.collections.values.sortedBy { it.name }.forEach { col ->
                        val on = col.id in item.collectionIds
                        FilterChip(selected = on, onClick = {
                            c.setCollections(item, if (on) item.collectionIds - col.id else item.collectionIds + col.id)
                        }, label = { Text(col.name) })
                    }
                }
            }
        }
        if (c.similar.isNotEmpty()) {
            item {
                Text("MORE LIKE THIS", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Palette.Muted)
                LazyRow(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(c.similar) { s ->
                        Box(Modifier.size(76.dp).clip(RoundedCornerShape(14.dp)).background(Palette.Bg)
                            .clickable { c.select(s) }) {
                            AsyncImage(c.api.absolute(s.urls.thumb ?: s.urls.original), null, imageLoader = loader,
                                contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
                        }
                    }
                }
            }
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TextButton(onClick = { c.togglePick(item.id) }) {
                    Text(if (item.id in c.picks) "Remove Discover pick" else "Use as Discover pick")
                }
                TextButton(onClick = { c.delete(item) }) { Text("Delete", color = Palette.Danger) }
                TextButton(onClick = { c.select(null) }) { Text("Close", color = Palette.Muted) }
            }
        }
    }
}

/* -------------------------------------------------------------- save sheet */

@Composable
private fun SaveDialog(c: Controller, p: PendingSave, loader: ImageLoader) {
    var tag by remember(p) { mutableStateOf("") }
    val near = p.stage.near.firstOrNull()
    AlertDialog(
        onDismissRequest = { c.cancelPending() },
        title = { Text("Save to Vault", fontWeight = FontWeight.Bold) },
        text = {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                item {
                    val m = p.stage.meta
                    Text(
                        if (m != null) "${m.mime.substringAfter('/').uppercase()} · ${m.width}×${m.height} · ${formatBytes(m.bytes)}" else "",
                        color = Palette.Muted,
                    )
                }
                item {
                    OutlinedTextField(p.title, { p.title = it }, singleLine = true, label = { Text("Title") },
                        modifier = Modifier.fillMaxWidth())
                }
                item {
                    Text(if (p.stage.autoTags.isNotEmpty()) "TAGS FROM YOUR SERVER" else "TAGS", fontSize = 12.sp,
                        fontWeight = FontWeight.SemiBold, color = Palette.Muted)
                    FlowRow(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        p.tags.toList().forEach { t ->
                            FilterChip(selected = true, onClick = { p.tags.remove(t) }, label = { Text("$t  ×") })
                        }
                    }
                    OutlinedTextField(
                        tag, { tag = it }, singleLine = true, placeholder = { Text("+ tag") },
                        modifier = Modifier.fillMaxWidth().padding(top = 6.dp),
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                        keyboardActions = KeyboardActions(onDone = {
                            val t = tag.trim().lowercase()
                            if (t.isNotEmpty() && t !in p.tags) p.tags.add(t)
                            tag = ""
                        }),
                    )
                }
                val collections = c.library.state.value.collections.values.sortedBy { it.name }
                if (collections.isNotEmpty()) {
                    item {
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            collections.forEach { col ->
                                val on = col.id in p.collectionIds
                                FilterChip(selected = on, onClick = {
                                    if (on) p.collectionIds.remove(col.id) else p.collectionIds.add(col.id)
                                }, label = { Text(col.name) })
                            }
                        }
                    }
                }
                if (near != null) {
                    item {
                        Surface(shape = RoundedCornerShape(16.dp), color = Palette.Raised) {
                            Row(Modifier.padding(10.dp), verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                AsyncImage(c.api.absolute(near.item.urls.thumb ?: near.item.urls.original), null,
                                    imageLoader = loader, modifier = Modifier.size(44.dp).clip(RoundedCornerShape(10.dp)))
                                Column(Modifier.weight(1f)) {
                                    Text("Looks a lot like one you have", fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                                    Text("${near.item.title.ifBlank { "Untitled" }} · ${(near.similarity * 100).toInt()}% match",
                                        color = Palette.Muted, fontSize = 12.sp)
                                }
                            }
                        }
                    }
                }
            }
        },
        confirmButton = { Button(onClick = { c.commitPending() }) { Text("Save to Vault") } },
        dismissButton = { TextButton(onClick = { c.cancelPending() }) { Text("Cancel") } },
    )
}

/* ---------------------------------------------------------------- discover */

@Composable
private fun DiscoverContent(c: Controller, loader: ImageLoader, compactNav: Boolean) {
    Column(Modifier.fillMaxSize()) {
        Column(Modifier.padding(16.dp, 16.dp, 16.dp, 8.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text("Discover", fontSize = 28.sp, fontWeight = FontWeight.Bold)
            Text("Search the web, save what sticks", color = Palette.Muted, fontSize = 13.sp)
        }
        if (compactNav) CompactNav(c)
        OutlinedTextField(
            c.discoverQuery, { c.discoverQuery = it }, singleLine = true,
            modifier = Modifier.fillMaxWidth().padding(16.dp, 8.dp), shape = RoundedCornerShape(14.dp),
            placeholder = { Text("Search 7TV and more…") },
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
            keyboardActions = KeyboardActions(onSearch = { c.discover() }),
        )
        LazyRow(contentPadding = PaddingValues(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            items(c.discoverSources) { s ->
                FilterChip(selected = s.key in c.activeSources, onClick = {
                    if (s.key in c.activeSources) c.activeSources.remove(s.key) else c.activeSources.add(s.key)
                }, label = { Text(s.label) })
            }
            item {
                FilterChip(selected = c.animatedOnly, onClick = { c.animatedOnly = !c.animatedOnly },
                    label = { Text("Animated") })
            }
        }
        if (c.picks.isNotEmpty()) {
            Surface(Modifier.padding(16.dp, 10.dp, 16.dp, 0.dp).fillMaxWidth(), shape = RoundedCornerShape(16.dp),
                color = Palette.Surface, border = BorderStroke(1.dp, Palette.Border)) {
                Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("Similar to ${c.picks.size} pick${if (c.picks.size > 1) "s" else ""}", fontWeight = FontWeight.SemiBold)
                        Text("Ranks by look, not just tags", color = Palette.Muted, fontSize = 12.sp)
                    }
                    TextButton(onClick = { c.picks.clear() }) { Text("Clear") }
                }
            }
        }
        Spacer(Modifier.height(8.dp))
        LazyVerticalGrid(
            GridCells.Adaptive(150.dp), contentPadding = PaddingValues(16.dp, 4.dp, 16.dp, 24.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items(c.discoverResults, key = { it.source + ":" + it.sourceId }) { d -> DiscoverTile(c, d, loader) }
            if (c.discoverHasMore) {
                item(span = { GridItemSpan(maxLineSpan) }) {
                    Box(Modifier.fillMaxWidth().padding(8.dp), contentAlignment = Alignment.Center) {
                        OutlinedButton(onClick = { c.discoverMore() }) { Text("Load more") }
                    }
                }
            }
            if (c.discoverResults.isEmpty() && !c.discovering) {
                item(span = { GridItemSpan(maxLineSpan) }) {
                    Text("Type a search and press Enter.", color = Palette.Muted, modifier = Modifier.padding(24.dp))
                }
            }
        }
    }
}

@Composable
private fun DiscoverTile(c: Controller, d: DiscoverItem, loader: ImageLoader) {
    val saved = d.savedItemId != null
    val busy = (d.source + ":" + d.sourceId) in c.saving
    Tile(d.previewUrl, d.mime.substringAfter('/').uppercase(), loader, selected = false, http = c.api.http,
        animatedUrl = d.previewUrl.takeIf { d.animated }, overlay = {
        Box(Modifier.fillMaxSize()) {
            Text("${d.source.uppercase()} · ${d.title}", fontSize = 11.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.align(Alignment.BottomStart).padding(8.dp).widthIn(max = 100.dp)
                    .clip(RoundedCornerShape(8.dp)).background(Color(0xD914151A)).padding(horizontal = 8.dp, vertical = 3.dp))
            Box(
                Modifier.align(Alignment.BottomEnd).padding(8.dp).size(44.dp).clip(CircleShape)
                    .background(if (saved) Color(0xD914151A) else Palette.Accent)
                    .clickable(enabled = !saved && !busy) { c.saveDiscovered(d) },
                contentAlignment = Alignment.Center,
            ) {
                Text(if (saved) "✓" else if (busy) "…" else "+", fontSize = 22.sp, fontWeight = FontWeight.Bold,
                    color = if (saved) Palette.Accent else Palette.OnAccent)
            }
        }
    }, onClick = { d.savedItemId?.let { id -> c.library.state.value.items[id]?.let { c.select(it) } } })
}

private fun formatBytes(n: Long): String = when {
    n < 1024 -> "$n B"
    n < 1_048_576 -> "${n / 1024} KB"
    else -> "${(n * 10 / 1_048_576) / 10.0} MB"
}
