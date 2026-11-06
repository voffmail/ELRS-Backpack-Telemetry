package com.elrs.backpack

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.ActivityNotFoundException
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.webkit.JsResult
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import org.json.JSONObject
import java.util.Locale

class MainActivity : Activity() {

    companion object {
        private const val REQ_NOTIFICATIONS = 1
        private const val REQ_TRACKS_FOLDER = 2
        private const val UI_PREFS = "elrs_ui"
    }

    private lateinit var webView: WebView
    private val handler = Handler(Looper.getMainLooper())
    private var destroyed = false

    private val settingsReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            notifyWebSettingsChanged()
        }
    }

    private val openPage = object : Runnable {
        override fun run() {
            if (destroyed) return
            if (TelemetryService.httpReady) {
                webView.loadUrl("http://127.0.0.1:${TelemetryService.HTTP_PORT}/")
            } else {
                handler.postDelayed(this, 200)
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        startTelemetryService()

        webView = WebView(this)
        webView.setBackgroundColor(0xFF0B0F14.toInt())
        webView.settings.javaScriptEnabled = true
        webView.settings.domStorageEnabled = true
        webView.settings.cacheMode = android.webkit.WebSettings.LOAD_DEFAULT
        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(
                view: WebView?,
                request: WebResourceRequest?,
            ): Boolean {
                val uri = request?.url ?: return false
                if (request.isForMainFrame != true) return false
                return when (uri.scheme?.lowercase(Locale.US)) {
                    "geo", "maps", "google.navigation", "yandexmaps", "yandexnavi" ->
                        openExternalGeo(uri)

                    "http", "https" -> openExternalUrl(uri)
                    else -> false
                }
            }
        }
        webView.webChromeClient = object : WebChromeClient() {
            override fun onJsAlert(
                view: WebView?,
                url: String?,
                message: String?,
                result: JsResult?,
            ): Boolean {
                showJsDialog(message, result, confirmOnly = true)
                return true
            }

            override fun onJsConfirm(
                view: WebView?,
                url: String?,
                message: String?,
                result: JsResult?,
            ): Boolean {
                showJsDialog(message, result, confirmOnly = false)
                return true
            }
        }
        webView.addJavascriptInterface(AndroidSettingsBridge(this), "AndroidSettings")
        setContentView(webView)

        val filter = IntentFilter(TelemetryService.ACTION_SETTINGS_CHANGED)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(settingsReceiver, filter, RECEIVER_NOT_EXPORTED)
        } else {
            @Suppress("DEPRECATION")
            registerReceiver(settingsReceiver, filter)
        }

        handler.post(openPage)
        handler.postDelayed({ maybePromptStartupPermissions() }, 1500)
    }

    override fun onStart() {
        super.onStart()
        startTelemetryService()
    }

    override fun onResume() {
        super.onResume()
        if (this::webView.isInitialized) {
            handler.postDelayed({ notifyWebSettingsChanged() }, 300)
        }
    }

    private fun startTelemetryService() {
        val serviceIntent = Intent(this, TelemetryService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(serviceIntent)
        } else {
            startService(serviceIntent)
        }
    }

    override fun onDestroy() {
        destroyed = true
        handler.removeCallbacksAndMessages(null)
        try {
            unregisterReceiver(settingsReceiver)
        } catch (_: Exception) {
        }
        webView.destroy()
        super.onDestroy()
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQ_NOTIFICATIONS) {
            maybePromptBatteryExemption(uiPrefs())
            notifyWebSettingsChanged()
        }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != REQ_TRACKS_FOLDER || resultCode != RESULT_OK) return
        val uri = data?.data ?: return
        try {
            contentResolver.takePersistableUriPermission(
                uri,
                Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION,
            )
        } catch (_: Exception) {
        }
        val intent = Intent(this, TelemetryService::class.java)
            .setAction(TelemetryService.ACTION_SET_TRACKS)
            .putExtra(TelemetryService.EXTRA_TRACKS_URI, uri.toString())
        startService(intent)
        handler.postDelayed({ notifyWebSettingsChanged() }, 1200)
    }

    fun permissionsJson(): String = try {
        val power = getSystemService(PowerManager::class.java)
        val notifications = Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
        val battery = power.isIgnoringBatteryOptimizations(packageName)
        val wifi = checkSelfPermission(Manifest.permission.CHANGE_WIFI_STATE) == PackageManager.PERMISSION_GRANTED &&
            checkSelfPermission(Manifest.permission.CHANGE_WIFI_MULTICAST_STATE) == PackageManager.PERMISSION_GRANTED &&
            checkSelfPermission(Manifest.permission.ACCESS_WIFI_STATE) == PackageManager.PERMISSION_GRANTED
        val foreground = checkSelfPermission(Manifest.permission.FOREGROUND_SERVICE) == PackageManager.PERMISSION_GRANTED &&
            checkSelfPermission(Manifest.permission.WAKE_LOCK) == PackageManager.PERMISSION_GRANTED &&
            checkSelfPermission(Manifest.permission.INTERNET) == PackageManager.PERMISSION_GRANTED &&
            (Build.VERSION.SDK_INT < Build.VERSION_CODES.UPSIDE_DOWN_CAKE ||
                checkSelfPermission(Manifest.permission.FOREGROUND_SERVICE_CONNECTED_DEVICE) == PackageManager.PERMISSION_GRANTED)
        JSONObject()
            .put("notifications", notifications)
            .put("battery", battery)
            .put("wifi", wifi)
            .put("foreground", foreground)
            .toString()
    } catch (_: Exception) {
        "{}"
    }

    fun requestNotificationsPermission() {
        runOnUiThread {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
                notifyWebSettingsChanged()
                return@runOnUiThread
            }
            if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) {
                notifyWebSettingsChanged()
            } else {
                requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), REQ_NOTIFICATIONS)
            }
        }
    }

    fun requestBatteryExemption() {
        runOnUiThread {
            val power = getSystemService(PowerManager::class.java)
            if (power.isIgnoringBatteryOptimizations(packageName)) {
                notifyWebSettingsChanged()
                return@runOnUiThread
            }
            val intent = Intent(
                Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                Uri.parse("package:$packageName"),
            )
            try {
                startActivity(intent)
            } catch (_: ActivityNotFoundException) {
                openBatterySettings()
            } catch (_: SecurityException) {
                openBatterySettings()
            }
        }
    }

    fun openAppSettings() {
        runOnUiThread {
            try {
                startActivity(
                    Intent(
                        Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                        Uri.parse("package:$packageName"),
                    ),
                )
            } catch (_: Exception) {
                toast(getString(R.string.settings_open_error))
            }
        }
    }

    fun chooseTracksFolder() {
        runOnUiThread {
            val intent = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).apply {
                addFlags(
                    Intent.FLAG_GRANT_READ_URI_PERMISSION or
                        Intent.FLAG_GRANT_WRITE_URI_PERMISSION or
                        Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION,
                )
            }
            try {
                startActivityForResult(intent, REQ_TRACKS_FOLDER)
            } catch (_: ActivityNotFoundException) {
                toast(getString(R.string.tracks_folder_error))
            }
        }
    }

    fun resetTracksFolder() {
        runOnUiThread {
            val intent = Intent(this, TelemetryService::class.java)
                .setAction(TelemetryService.ACTION_SET_TRACKS)
            startService(intent)
            handler.postDelayed({ notifyWebSettingsChanged() }, 1200)
        }
    }

    fun closeApp() {
        runOnUiThread {
            stopService(Intent(this, TelemetryService::class.java))
            finishAndRemoveTask()
        }
    }

    private fun openBatterySettings() {
        try {
            startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
        } catch (_: Exception) {
            openAppSettings()
        }
    }

    private fun maybePromptStartupPermissions() {
        val prefs = uiPrefs()
        if (prefs.getBoolean("startup_permissions_done", false)) return
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), REQ_NOTIFICATIONS)
            return
        }
        maybePromptBatteryExemption(prefs)
    }

    private fun maybePromptBatteryExemption(prefs: SharedPreferences) {
        if (prefs.getBoolean("startup_permissions_done", false)) return
        val power = getSystemService(PowerManager::class.java)
        if (power.isIgnoringBatteryOptimizations(packageName)) {
            prefs.edit().putBoolean("startup_permissions_done", true).apply()
            return
        }
        AlertDialog.Builder(this)
            .setTitle(R.string.permissions_title)
            .setMessage(R.string.battery_prompt_message)
            .setPositiveButton(R.string.allow) { _, _ ->
                prefs.edit().putBoolean("startup_permissions_done", true).apply()
                requestBatteryExemption()
            }
            .setNegativeButton(R.string.later) { _, _ ->
                prefs.edit().putBoolean("startup_permissions_done", true).apply()
            }
            .setOnCancelListener {
                prefs.edit().putBoolean("startup_permissions_done", true).apply()
            }
            .show()
    }

    private fun uiPrefs(): SharedPreferences = getSharedPreferences(UI_PREFS, MODE_PRIVATE)

    private fun notifyWebSettingsChanged() {
        if (destroyed || !this::webView.isInitialized) return
        webView.post {
            webView.evaluateJavascript(
                "if (window.onNativeSettingsChanged) window.onNativeSettingsChanged();",
                null,
            )
        }
    }

    private fun openExternalGeo(uri: Uri): Boolean {
        return try {
            startActivity(Intent(Intent.ACTION_VIEW, uri))
            true
        } catch (_: ActivityNotFoundException) {
            toast(getString(R.string.no_navigation_app))
            true
        }
    }

    private fun openExternalUrl(uri: Uri): Boolean {
        return try {
            startActivity(Intent(Intent.ACTION_VIEW, uri))
            true
        } catch (_: ActivityNotFoundException) {
            toast(getString(R.string.no_browser_app))
            true
        }
    }

    private fun showJsDialog(message: String?, result: JsResult?, confirmOnly: Boolean) {
        if (destroyed || isFinishing) {
            result?.cancel()
            return
        }
        val builder = AlertDialog.Builder(this).setMessage(message)
        builder.setPositiveButton(android.R.string.ok) { _, _ -> result?.confirm() }
        if (!confirmOnly) {
            builder.setNegativeButton(android.R.string.cancel) { _, _ -> result?.cancel() }
        }
        builder.setOnCancelListener { result?.cancel() }
        builder.show()
    }

    private fun toast(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (this::webView.isInitialized && webView.canGoBack()) {
            webView.goBack()
        } else {
            super.onBackPressed()
        }
    }
}
