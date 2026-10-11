plugins {
    alias(libs.plugins.kotlinMultiplatform)
    alias(libs.plugins.kotlinSerialization)
    alias(libs.plugins.composeCompiler)
    alias(libs.plugins.composeMultiplatform)
}

val withAndroid = gradle.extra["androidSdkPresent"] as Boolean
if (withAndroid) apply(plugin = "com.android.library")

kotlin {
    jvm()
    if (withAndroid) androidTarget()

    sourceSets {
        commonMain.dependencies {
            implementation(compose.runtime)
            implementation(compose.foundation)
            implementation(compose.material3)
            implementation(libs.ktor.client.core)
            implementation(libs.ktor.client.content.negotiation)
            implementation(libs.ktor.serialization.json)
            implementation(libs.serialization.json)
            implementation(libs.coroutines.core)
            implementation(libs.coil.compose)
            implementation(libs.coil.network.ktor)
        }
        commonTest.dependencies {
            implementation(kotlin("test"))
            implementation(libs.ktor.client.mock)
            implementation(libs.coroutines.test)
        }
        jvmTest.dependencies {
            implementation(compose.desktop.currentOs) // Skia natives for the frame decoder test
        }
        jvmMain.dependencies {
            implementation(libs.ktor.client.okhttp)
        }
        if (withAndroid) {
            getByName("androidMain").dependencies {
                implementation(libs.ktor.client.okhttp)
                implementation(libs.coil.gif)
            }
        }
    }
}

if (withAndroid) {
    extensions.configure<com.android.build.api.dsl.LibraryExtension> {
        namespace = "app.vault.shared"
        compileSdk = 35
        defaultConfig { minSdk = 26 }
        compileOptions {
            sourceCompatibility = JavaVersion.VERSION_17
            targetCompatibility = JavaVersion.VERSION_17
        }
    }
}
