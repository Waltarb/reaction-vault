# Clients

One Kotlin codebase, Compose Multiplatform:

- `shared/`: server API client (Ktor), offline library mirror and sync, and the whole UI.
- `desktopApp/`: Windows and Linux window. "Copy" puts the chosen format on the clipboard as a file, so it pastes into chat apps.
- `androidApp/`: phone host. Registers as a "Save to Vault" share target, "Share" hands the file to the system share sheet.

## Build

JDK 17 and the included Gradle wrapper:

```bash
./gradlew :desktopApp:run                  # run the desktop client
./gradlew :shared:jvmTest                  # API and sync tests
./gradlew :desktopApp:packageDistributionForCurrentOS   # MSI / DEB / AppImage
```

The Android modules are only included when an Android SDK is found (`ANDROID_HOME`, `ANDROID_SDK_ROOT` or `sdk.dir` in `local.properties`):

```bash
./gradlew :androidApp:assembleDebug
```

## Connecting

Create a device token on the server (`vault token create phone`), then enter the server address and token on first launch. The Android build refuses plain HTTP; put the server behind HTTPS (see `deploy/Caddyfile.snippet`).

## Quick search (desktop)

`Ctrl+Alt+V` from anywhere (Windows and X11), the tray icon, or `Ctrl+K` inside the app opens a small
always-on-top search box. Type, arrow left/right, `Enter` copies the file to the clipboard and closes it,
`Esc` closes. Closing the main window hides it to the tray when the desktop has one; use the tray's Quit.
On Wayland apps cannot listen for global keys, so use the tray icon or `Ctrl+K`.

## Animated previews

Hovering a tile and the detail panel play the item's preview. The desktop decodes animated WebP and GIF
frames with Skia (`AnimatedImage` in `shared/src/jvmMain`); Android uses Coil's decoders.

## Known gaps

- The quick-search popup and animated previews were compiled and unit-tested (frame decoding) but not
  driven by hand on every platform; the Android app has only been built in CI, not run on a device.
- The global hotkey cannot work on Wayland (see above).
- Android refuses plain HTTP, and shared links must be `http(s)://` text.
