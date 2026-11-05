import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

fun readMapTilerKey(): String {
    System.getenv("MAPTILER_KEY")?.trim()?.takeIf { it.isNotEmpty() }?.let { return it }
    val keyFile = rootProject.file("../maptiler.key")
    if (keyFile.isFile) {
        keyFile.readText().trim().takeIf { it.isNotEmpty() }?.let { return it }
    }
    val localFile = rootProject.file("local.properties")
    if (localFile.isFile) {
        val properties = Properties()
        localFile.inputStream().use { properties.load(it) }
        properties.getProperty("MAPTILER_KEY", "").trim().takeIf { it.isNotEmpty() }?.let { return it }
    }
    return ""
}

fun jsString(value: String): String =
    "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\""

android {
    namespace = "com.elrs.backpack"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.elrs.backpack"
        minSdk = 24
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"
        buildConfigField("String", "MAPTILER_KEY", jsString(readMapTilerKey()))
    }

    buildFeatures {
        buildConfig = true
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.documentfile:documentfile:1.0.1")
}
