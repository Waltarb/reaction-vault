package app.vault.desktop

import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Window
import androidx.compose.ui.window.application
import androidx.compose.ui.window.rememberWindowState
import app.vault.ui.VaultApp
import io.ktor.client.engine.okhttp.OkHttp

fun main() = application {
    val platform = remember { DesktopPlatform() }
    Window(
        onCloseRequest = ::exitApplication,
        title = "Reaction Vault",
        state = rememberWindowState(width = 1280.dp, height = 800.dp),
    ) {
        VaultApp(platform) { OkHttp.create() }
    }
}

private fun <T> remember(block: () -> T): T = block()
