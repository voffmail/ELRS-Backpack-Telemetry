package com.elrs.backpack

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.drawable.Icon
import android.net.Uri
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import android.widget.Toast
import org.json.JSONObject
import java.io.File
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetSocketAddress
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.TimeUnit

class TelemetryService : Service(), SettingsHost {

    companion object {
        const val HTTP_PORT = 8080
        const val ACTION_STOP = "com.elrs.backpack.STOP"
        const val ACTION_SET_TRACKS = "com.elrs.backpack.SET_TRACKS"
        const val ACTION_SETTINGS_CHANGED = "com.elrs.backpack.SETTINGS_CHANGED"
        const val EXTRA_TRACKS_URI = "tracks_uri"
        private const val CHANNEL_ID = "elrs_telemetry_v2"
        private const val ALERT_CHANNEL_ID = "elrs_alerts"
        private const val NOTIFICATION_ID = 14550
        private const val ALERT_NOTIFICATION_ID = 14551

        @Volatile
        var httpReady = false
            private set
    }

    private lateinit var state: TelemetryState
    private lateinit var settings: AppSettings
    private var udpSocket: DatagramSocket? = null
    private var udpThread: Thread? = null
    private var http: HttpServer? = null
    private val mainHandler = Handler(Looper.getMainLooper())

    @Volatile
    private var running = false

    @Volatile
    private var udpGeneration = 0

    @Volatile
    private var currentUdpPort = AppSettings.DEFAULT_UDP_PORT

    @Volatile
    private var powerSave = false

    private var watchdog: ScheduledExecutorService? = null
    private var serviceStartMono = 0L

    private var wifiLock: WifiManager.WifiLock? = null
    private var multicastLock: WifiManager.MulticastLock? = null
    private var wakeLock: PowerManager.WakeLock? = null

    override fun onCreate() {
        super.onCreate()
        running = true
        httpReady = false
        serviceStartMono = SystemClock.elapsedRealtime()
        settings = AppSettings(this)
        currentUdpPort = settings.udpPort
        state = TelemetryState(initialTrackStore())
        createChannel()
        startForegroundCompat(buildNotification())
        acquireLocks()
        if (!startUdp(currentUdpPort)) {
            if (currentUdpPort != AppSettings.DEFAULT_UDP_PORT && startUdp(AppSettings.DEFAULT_UDP_PORT)) {
                currentUdpPort = AppSettings.DEFAULT_UDP_PORT
                settings.udpPort = currentUdpPort
                updateNotification()
            }
        }
        startHttp()
        startWatchdog()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent == null) return START_STICKY
        when (intent.action) {
            ACTION_STOP -> {
                stopSelf()
                return START_NOT_STICKY
            }

            ACTION_SET_TRACKS -> {
                applyTracksUriAsync(intent.getStringExtra(EXTRA_TRACKS_URI))
                mainHandler.post { exitPowerSaveNow() }
            }

            else -> mainHandler.post { exitPowerSaveNow() }
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        running = false
        stopWatchdog()
        stopUdp()
        http?.stop()
        http = null
        httpReady = false
        releaseLocks()
        super.onDestroy()
    }

    override fun settingsJson(): String = JSONObject()
        .put("udp_port", currentUdpPort)
        .put("tracks_location", state.tracksLocation())
        .put("tracks_uri", settings.tracksUri ?: JSONObject.NULL)
        .put("recording", state.isRecording())
        .put("idle_release_min", settings.idleReleaseMinutes)
        .toString()

    override fun changeUdpPort(port: Int): Pair<Boolean, String> {
        if (port !in 1..65535) return Pair(false, "port must be 1..65535")
        if (port == currentUdpPort && udpSocket != null) return Pair(true, "")

        val oldPort = currentUdpPort
        stopUdp()
        if (startUdp(port)) {
            currentUdpPort = port
            settings.udpPort = port
            updateNotification()
            notifySettingsChanged()
            return Pair(true, "")
        }

        if (startUdp(oldPort)) {
            currentUdpPort = oldPort
        }
        return Pair(false, "failed to bind UDP $port")
    }

    override fun changeIdleReleaseMinutes(minutes: Int): Pair<Boolean, String> {
        if (minutes !in 0..1440) return Pair(false, "idle timeout must be 0..1440")
        settings.idleReleaseMinutes = minutes
        if (minutes == 0) mainHandler.post { exitPowerSaveNow() }
        mainHandler.post { updateNotification() }
        notifySettingsChanged()
        return Pair(true, "")
    }

    private fun initialTrackStore(): TrackStore {
        val uri = settings.tracksUri
        if (!uri.isNullOrBlank()) {
            val store = buildSafStore(uri)
            if (store != null) return store
            settings.tracksUri = null
        }
        return FileTrackStore(File(filesDir, "tracks"))
    }

    private fun buildSafStore(uriString: String): SafTrackStore? = try {
        val store = SafTrackStore(this, Uri.parse(uriString))
        if (store.isUsable()) store else null
    } catch (_: Exception) {
        null
    }

    private fun applyTracksUriAsync(uriString: String?) {
        Thread({
            if (state.isRecording()) {
                toast(getString(R.string.stop_recording_first))
                return@Thread
            }
            val newStore = if (uriString.isNullOrBlank()) {
                FileTrackStore(File(filesDir, "tracks"))
            } else {
                buildSafStore(uriString)
            }
            if (newStore == null || !newStore.isUsable()) {
                toast(getString(R.string.tracks_folder_error))
                return@Thread
            }

            val oldStore = state.currentStore()
            if (oldStore.location() != newStore.location()) {
                copyTracks(oldStore, newStore)
                state.setTrackStore(newStore)
            }
            settings.tracksUri = if (newStore is SafTrackStore) uriString else null
            toast(getString(R.string.tracks_location_changed, newStore.location()))
            notifySettingsChanged()
        }, "elrs-settings").start()
    }

    private fun copyTracks(from: TrackStore, to: TrackStore) {
        for (id in from.listIds()) {
            if (to.read(id) != null) continue
            val data = from.read(id) ?: continue
            to.write(id, data)
        }
    }

    private fun startUdp(port: Int): Boolean {
        stopUdp()
        return try {
            val socket = DatagramSocket(null)
            socket.reuseAddress = true
            try {
                socket.receiveBufferSize = 1 shl 20
            } catch (_: Exception) {
            }
            socket.bind(InetSocketAddress("0.0.0.0", port))
            udpSocket = socket
            val generation = udpGeneration
            val thread = Thread({
                val buffer = ByteArray(4096)
                while (running && generation == udpGeneration) {
                    val packet = DatagramPacket(buffer, buffer.size)
                    try {
                        socket.receive(packet)
                    } catch (_: Exception) {
                        break
                    }
                    state.onDatagram(buffer, packet.length)
                    if (powerSave) mainHandler.post { exitPowerSaveNow() }
                }
            }, "elrs-udp")
            thread.isDaemon = true
            udpThread = thread
            thread.start()
            true
        } catch (_: Exception) {
            udpSocket = null
            false
        }
    }

    private fun stopUdp() {
        udpGeneration += 1
        try {
            udpSocket?.close()
        } catch (_: Exception) {
        }
        udpSocket = null
        udpThread = null
    }

    private fun startHttp() {
        val page = try {
            assets.open("index.html").bufferedReader().use { it.readText() }
        } catch (_: Exception) {
            "<!doctype html><meta charset=\"utf-8\"><body style=\"background:#0b0f14;color:#e6edf3;font-family:sans-serif;padding:24px\">index.html not found</body>"
        }
        val rendered = page.replace("\"__MAPTILER_KEY__\"", JSONObject.quote(BuildConfig.MAPTILER_KEY))
        val server = HttpServer(state, rendered, HTTP_PORT, this)
        http = server
        httpReady = server.start()
        if (!httpReady) {
            val retry = Thread({
                while (running && !httpReady) {
                    try {
                        Thread.sleep(1000)
                    } catch (_: InterruptedException) {
                        return@Thread
                    }
                    if (running && server.start()) httpReady = true
                }
            }, "elrs-http-retry")
            retry.isDaemon = true
            retry.start()
        }
    }

    private fun notifySettingsChanged() {
        sendBroadcast(Intent(ACTION_SETTINGS_CHANGED).setPackage(packageName))
    }

    private fun toast(message: String) {
        mainHandler.post {
            Toast.makeText(applicationContext, message, Toast.LENGTH_LONG).show()
        }
    }

    private fun updateNotification() {
        startForegroundCompat(buildNotification())
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = getSystemService(NotificationManager::class.java)
        val channel = NotificationChannel(
            CHANNEL_ID,
            getString(R.string.notif_channel_name),
            NotificationManager.IMPORTANCE_DEFAULT,
        )
        channel.setSound(null, null)
        channel.enableVibration(false)
        channel.setShowBadge(false)
        channel.lockscreenVisibility = Notification.VISIBILITY_PUBLIC
        manager.createNotificationChannel(channel)

        val alert = NotificationChannel(
            ALERT_CHANNEL_ID,
            getString(R.string.alert_channel_name),
            NotificationManager.IMPORTANCE_HIGH,
        )
        alert.setShowBadge(false)
        manager.createNotificationChannel(alert)
    }

    private fun notificationText(): String {
        val age = state.lastPacketAgeSeconds()
        val total = state.totalPackets()
        val pps = state.recentPps(5.0)
        return when {
            powerSave -> getString(R.string.notif_powersave_text, settings.idleReleaseMinutes)
            age == null || age > 5.0 -> getString(R.string.notif_waiting, currentUdpPort)
            else -> getString(R.string.notif_running, currentUdpPort, pps, total)
        }
    }

    private fun buildNotification(): Notification {
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) PendingIntent.FLAG_IMMUTABLE else 0
        val openIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            flags,
        )
        val stopIntent = PendingIntent.getService(
            this,
            1,
            Intent(this, TelemetryService::class.java).setAction(ACTION_STOP),
            flags,
        )
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, CHANNEL_ID)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this).setPriority(Notification.PRIORITY_LOW)
        }
        builder
            .setContentTitle(getString(if (powerSave) R.string.notif_title_powersave else R.string.notif_title))
            .setContentText(notificationText())
            .setSmallIcon(R.drawable.ic_stat_elrs)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(openIntent)
            .addAction(
                Notification.Action.Builder(
                    Icon.createWithResource(this, R.drawable.ic_stat_elrs),
                    getString(R.string.stop_service),
                    stopIntent,
                ).build(),
            )
        return builder.build()
    }

    private fun startWatchdog() {
        if (watchdog != null) return
        val executor = Executors.newSingleThreadScheduledExecutor { runnable ->
            Thread(runnable, "elrs-watchdog").apply { isDaemon = true }
        }
        watchdog = executor
        executor.scheduleAtFixedRate({
            if (running) {
                try {
                    mainHandler.post { if (running) updateNotification() }
                    checkIdleTimeout()
                } catch (_: Exception) {
                }
            }
        }, 5, 5, TimeUnit.SECONDS)
    }

    private fun stopWatchdog() {
        try {
            watchdog?.shutdownNow()
        } catch (_: Exception) {
        }
        watchdog = null
    }

    private fun checkIdleTimeout() {
        if (powerSave) return
        val minutes = settings.idleReleaseMinutes
        if (minutes <= 0) return
        val age = state.lastPacketAgeSeconds()
        val idleSeconds = age ?: ((SystemClock.elapsedRealtime() - serviceStartMono) / 1000.0)
        if (idleSeconds >= minutes * 60.0) {
            mainHandler.post { enterPowerSave() }
        }
    }

    private fun enterPowerSave() {
        if (!running || powerSave) return
        powerSave = true
        updateNotification()
        showPowerSaveAlert()
        releaseLocks()
    }

    private fun exitPowerSaveNow() {
        if (!running || !powerSave) return
        powerSave = false
        acquireLocks()
        updateNotification()
        try {
            getSystemService(NotificationManager::class.java).cancel(ALERT_NOTIFICATION_ID)
        } catch (_: Exception) {
        }
    }

    private fun showPowerSaveAlert() {
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) PendingIntent.FLAG_IMMUTABLE else 0
        val openIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            flags,
        )
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, ALERT_CHANNEL_ID)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this).setPriority(Notification.PRIORITY_HIGH)
        }
        builder
            .setContentTitle(getString(R.string.alert_title))
            .setContentText(getString(R.string.alert_text, settings.idleReleaseMinutes))
            .setSmallIcon(R.drawable.ic_stat_elrs)
            .setAutoCancel(true)
            .setContentIntent(openIntent)
        try {
            getSystemService(NotificationManager::class.java).notify(ALERT_NOTIFICATION_ID, builder.build())
        } catch (_: Exception) {
        }
    }

    private fun startForegroundCompat(notification: Notification) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE,
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    @Suppress("DEPRECATION")
    private fun acquireLocks() {
        if (wakeLock != null || wifiLock != null || multicastLock != null) return
        try {
            val power = getSystemService(PowerManager::class.java)
            wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "ELRSBackpack::telemetry").apply {
                setReferenceCounted(false)
                acquire()
            }
        } catch (_: Exception) {
        }
        try {
            val wifi = applicationContext.getSystemService(WifiManager::class.java)
            wifiLock = wifi.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "ELRSBackpack::wifi").apply {
                setReferenceCounted(false)
                acquire()
            }
            multicastLock = wifi.createMulticastLock("ELRSBackpack::udp").apply {
                setReferenceCounted(false)
                acquire()
            }
        } catch (_: Exception) {
        }
    }

    private fun releaseLocks() {
        try {
            wakeLock?.takeIf { it.isHeld }?.release()
        } catch (_: Exception) {
        }
        try {
            wifiLock?.takeIf { it.isHeld }?.release()
        } catch (_: Exception) {
        }
        try {
            multicastLock?.takeIf { it.isHeld }?.release()
        } catch (_: Exception) {
        }
        wakeLock = null
        wifiLock = null
        multicastLock = null
    }
}
