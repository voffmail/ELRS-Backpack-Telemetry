import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val keystoreProperties = Properties()
val keystorePropertiesFile = rootProject.file("keystore.properties")
if (keystorePropertiesFile.isFile) {
    keystorePropertiesFile.inputStream().use { keystoreProperties.load(it) }
}
val releaseStorePath = System.getenv("ANDROID_KEYSTORE_PATH")
    ?: keystoreProperties.getProperty("storeFile")?.let { rootProject.file(it).absolutePath }
val releaseStorePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
    ?: keystoreProperties.getProperty("storePassword")
val releaseKeyAlias = System.getenv("ANDROID_KEY_ALIAS")
    ?: keystoreProperties.getProperty("keyAlias")
val releaseKeyPassword = System.getenv("ANDROID_KEY_PASSWORD")
    ?: keystoreProperties.getProperty("keyPassword")

android {
    namespace = "com.elrs.backpack"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.elrs.backpack"
        minSdk = 24
        targetSdk = 35
        versionCode = 12
        versionName = "3.1.0"
    }

    sourceSets {
        getByName("main") {
            assets.srcDir("../../web")
        }
    }

    buildFeatures {
        buildConfig = true
    }

    signingConfigs {
        if (releaseStorePath != null) {
            create("release") {
                storeFile = file(releaseStorePath)
                storePassword = releaseStorePassword
                keyAlias = releaseKeyAlias
                keyPassword = releaseKeyPassword
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("release")
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
    implementation("com.github.mik3y:usb-serial-for-android:3.11.0")
}
