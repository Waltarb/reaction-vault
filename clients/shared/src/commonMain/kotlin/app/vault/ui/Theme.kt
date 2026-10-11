package app.vault.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/** Colours taken from the design canvas. */
object Palette {
    val Bg = Color(0xFF14151A)
    val Side = Color(0xFF101116)
    val Surface = Color(0xFF1E2027)
    val Raised = Color(0xFF272A33)
    val Border = Color(0xFF2F333D)
    val Text = Color(0xFFF2F1EC)
    val Muted = Color(0xFFA4A7B3)
    val Accent = Color(0xFFC8F24B)
    val OnAccent = Color(0xFF14151A)
    val Danger = Color(0xFFFF7A7A)
}

@Composable
fun VaultTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = Palette.Accent,
            onPrimary = Palette.OnAccent,
            background = Palette.Bg,
            onBackground = Palette.Text,
            surface = Palette.Surface,
            onSurface = Palette.Text,
            surfaceVariant = Palette.Raised,
            onSurfaceVariant = Palette.Muted,
            outline = Palette.Border,
            error = Palette.Danger,
        ),
        content = content,
    )
}
