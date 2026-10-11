import org.jetbrains.compose.desktop.application.dsl.TargetFormat

plugins {
    alias(libs.plugins.kotlinJvm)
    alias(libs.plugins.kotlinSerialization)
    alias(libs.plugins.composeCompiler)
    alias(libs.plugins.composeMultiplatform)
}

dependencies {
    implementation(project(":shared"))
    implementation(compose.desktop.currentOs)
    implementation(libs.ktor.client.okhttp)
    implementation(libs.serialization.json)
    implementation(libs.coroutines.swing)
    implementation(libs.jnativehook)
}

compose.desktop {
    application {
        mainClass = "app.vault.desktop.MainKt"
        nativeDistributions {
            targetFormats(TargetFormat.Msi, TargetFormat.Deb, TargetFormat.AppImage)
            packageName = "ReactionVault"
            packageVersion = "1.0.0"
            description = "Reaction Vault desktop client"
            vendor = "Reaction Vault"
            includeAllModules = true // ktor/okhttp and the tray need JDK modules the default runtime trims
            windows {
                menuGroup = "Reaction Vault"
                shortcut = true
                dirChooser = false // one click: no wizard questions
                perUserInstall = true // no admin prompt
                upgradeUuid = "6f4d3c2a-8a39-4a0e-9d2b-3f1d4f5a7c11"
            }
            linux {
                shortcut = true
                menuGroup = "Graphics"
            }
        }
    }
}
