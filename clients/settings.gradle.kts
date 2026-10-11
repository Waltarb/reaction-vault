pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "reaction-vault"

include(":shared", ":desktopApp")

// The Android modules need an Android SDK. Without one the desktop client still builds.
val androidSdkPresent: Boolean = run {
    val local = file("local.properties")
    val fromFile = local.exists() && local.readLines().any { it.startsWith("sdk.dir=") }
    fromFile || !System.getenv("ANDROID_HOME").isNullOrBlank() || !System.getenv("ANDROID_SDK_ROOT").isNullOrBlank()
}
gradle.extra["androidSdkPresent"] = androidSdkPresent
if (androidSdkPresent) include(":androidApp")
