package com.elrs.backpack

import android.content.Context

class AppSettings(context: Context) {

    private val prefs = context.getSharedPreferences("elrs_settings", Context.MODE_PRIVATE)

    var udpPort: Int
        get() = prefs.getInt(KEY_UDP_PORT, DEFAULT_UDP_PORT)
        set(value) = prefs.edit().putInt(KEY_UDP_PORT, value).apply()

    var tracksUri: String?
        get() = prefs.getString(KEY_TRACKS_URI, null)
        set(value) = prefs.edit().putString(KEY_TRACKS_URI, value).apply()

    var idleReleaseMinutes: Int
        get() = prefs.getInt(KEY_IDLE_RELEASE_MIN, DEFAULT_IDLE_RELEASE_MIN)
        set(value) = prefs.edit().putInt(KEY_IDLE_RELEASE_MIN, value).apply()

    companion object {
        const val DEFAULT_UDP_PORT = 14550
        const val DEFAULT_IDLE_RELEASE_MIN = 5
        private const val KEY_UDP_PORT = "udp_port"
        private const val KEY_TRACKS_URI = "tracks_uri"
        private const val KEY_IDLE_RELEASE_MIN = "idle_release_min"
    }
}
