package app.vault.desktop

import com.github.kwhat.jnativehook.GlobalScreen
import com.github.kwhat.jnativehook.keyboard.NativeKeyEvent
import com.github.kwhat.jnativehook.keyboard.NativeKeyListener
import java.util.logging.Level
import java.util.logging.Logger

/**
 * Ctrl+Alt+V from anywhere. Works on Windows and X11; Wayland does not let apps listen globally,
 * so there [start] returns false and the tray icon and the in-app Ctrl+K are the way in.
 */
class GlobalHotkey(private val onPressed: () -> Unit) : NativeKeyListener {
    @Volatile private var started = false

    fun start(): Boolean = runCatching {
        Logger.getLogger(GlobalScreen::class.java.`package`.name).apply { level = Level.OFF; useParentHandlers = false }
        GlobalScreen.registerNativeHook()
        GlobalScreen.addNativeKeyListener(this)
        started = true
    }.isSuccess

    fun stop() {
        if (!started) return
        runCatching {
            GlobalScreen.removeNativeKeyListener(this)
            GlobalScreen.unregisterNativeHook()
        }
        started = false
    }

    override fun nativeKeyPressed(e: NativeKeyEvent) {
        val mods = NativeKeyEvent.CTRL_MASK or NativeKeyEvent.ALT_MASK
        if (e.keyCode == NativeKeyEvent.VC_V && (e.modifiers and mods) == mods) onPressed()
    }
}
