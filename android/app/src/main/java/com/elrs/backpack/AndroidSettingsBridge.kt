package com.elrs.backpack

import android.webkit.JavascriptInterface

class AndroidSettingsBridge(private val activity: MainActivity) {

    @JavascriptInterface
    fun getPermissions(): String = activity.permissionsJson()

    @JavascriptInterface
    fun requestNotifications() = activity.requestNotificationsPermission()

    @JavascriptInterface
    fun requestBatteryOptimization() = activity.requestBatteryExemption()

    @JavascriptInterface
    fun openAppSettings() = activity.openAppSettings()

    @JavascriptInterface
    fun chooseTracksFolder() = activity.chooseTracksFolder()

    @JavascriptInterface
    fun resetTracksFolder() = activity.resetTracksFolder()

    @JavascriptInterface
    fun closeApp() = activity.closeApp()
}
