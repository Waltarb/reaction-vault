package app.vault.desktop

import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.painter.BitmapPainter
import androidx.compose.ui.graphics.Canvas
import androidx.compose.ui.graphics.Paint
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.isCtrlPressed
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.DialogWindow
import androidx.compose.ui.window.Tray
import androidx.compose.ui.window.Window
import androidx.compose.ui.window.WindowPosition
import androidx.compose.ui.window.application
import androidx.compose.ui.window.isTraySupported
import androidx.compose.ui.window.rememberDialogState
import androidx.compose.ui.window.rememberWindowState
import app.vault.ui.QuickSearchHandle
import app.vault.ui.VaultApp
import app.vault.ui.VaultTheme
import io.ktor.client.engine.okhttp.OkHttp

private fun trayIcon(): BitmapPainter {
    val bitmap = ImageBitmap(32, 32)
    val canvas = Canvas(bitmap)
    canvas.drawRoundRect(0f, 0f, 32f, 32f, 9f, 9f, Paint().apply { color = Color(0xFFC8F24B) })
    return BitmapPainter(bitmap)
}

fun main() = application {
    val platform = remember { DesktopPlatform() }
    val quick = remember { QuickSearchHandle() }
    var mainVisible by remember { mutableStateOf(true) }
    val trayOk = isTraySupported

    DisposableEffect(Unit) {
        val hotkey = GlobalHotkey { quick.toggle() }
        val ok = hotkey.start()
        if (!ok) System.err.println("Global hotkey unavailable (Wayland or no permission); use the tray icon or Ctrl+K.")
        onDispose { hotkey.stop() }
    }

    if (trayOk) {
        Tray(
            icon = remember { trayIcon() }, tooltip = "Reaction Vault",
            onAction = { quick.toggle() },
        ) {
            Item("Quick search", onClick = { quick.toggle() })
            Item("Open Vault", onClick = { mainVisible = true })
            Item("Quit", onClick = ::exitApplication)
        }
    }

    Window(
        onCloseRequest = { if (trayOk) mainVisible = false else exitApplication() },
        visible = mainVisible,
        title = "Reaction Vault",
        state = rememberWindowState(width = 1280.dp, height = 800.dp),
        onPreviewKeyEvent = { e ->
            if (e.type == KeyEventType.KeyDown && e.isCtrlPressed && e.key == Key.K) { quick.toggle(); true } else false
        },
    ) {
        VaultApp(platform, { OkHttp.create() }, quickSearch = quick) { content ->
            DialogWindow(
                onCloseRequest = { quick.hide() },
                state = rememberDialogState(position = WindowPosition.Aligned(androidx.compose.ui.Alignment.Center), size = DpSize(640.dp, 240.dp)),
                title = "Quick search", undecorated = true, resizable = false, alwaysOnTop = true,
            ) {
                VaultTheme { content() }
            }
        }
    }
}
