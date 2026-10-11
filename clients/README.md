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

## Known gaps

- Animated previews: thumbnails and previews render as still frames (Coil on Compose Multiplatform has no animated GIF/WebP decoder yet). The MP4/GIF/original send formats are unaffected.
- No global hotkey quick-search popup yet; search is in the main window.
- The Android module has not been built in CI or on a device yet.
