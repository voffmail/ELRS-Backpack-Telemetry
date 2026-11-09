package com.elrs.backpack

import android.content.Context
import android.hardware.usb.UsbDeviceConnection
import android.hardware.usb.UsbManager
import android.os.SystemClock
import com.hoho.android.usbserial.driver.UsbSerialPort
import com.hoho.android.usbserial.driver.UsbSerialProber
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.atomic.AtomicReference

class UsbTelemetryReader(
    private val context: Context,
    private val preferredDevice: String?,
    private val onFrame: (ByteArray) -> Unit,
    private val onData: () -> Unit,
) {
    companion object {
        const val ESPRESSIF_VID = 0x303A
        private const val BAUD = 115200
        private const val RETRY_MS = 1500L
        private const val CONFIG_RETRY_MS = 2000L
    }

    private val command = AtomicReference<ByteArray?>(null)
    private val configParser = DongleConfig.Parser()
    private val framer = CrsfFramer()
    private val lock = Any()

    @Volatile
    private var running = false

    @Volatile
    private var generation = 0

    private var thread: Thread? = null

    @Volatile
    private var connection: UsbDeviceConnection? = null

    @Volatile
    private var port: UsbSerialPort? = null

    @Volatile
    var state: String = "idle"
        private set

    @Volatile
    var deviceName: String? = null
        private set

    @Volatile
    var vendorId: Int = 0
        private set

    @Volatile
    var productId: Int = 0
        private set

    @Volatile
    var frames: Long = 0L
        private set

    @Volatile
    var crcErrors: Long = 0L
        private set

    @Volatile
    var bytesRead: Long = 0L
        private set

    @Volatile
    var lastError: String? = null
        private set

    @Volatile
    var configStatus: String = ""
        private set

    @Volatile
    var config: DongleConfig.ConfigInfo? = null
        private set

    fun start() {
        if (running) return
        running = true
        generation += 1
        val activeGeneration = generation
        state = "starting"
        val worker = Thread({ loop(activeGeneration) }, "elrs-usb")
        worker.isDaemon = true
        thread = worker
        worker.start()
    }

    fun stop() {
        running = false
        generation += 1
        closePort()
        thread?.interrupt()
        thread = null
        state = "idle"
    }

    fun queue(bytes: ByteArray) {
        command.set(bytes)
    }

    fun statusJson(): JSONObject = JSONObject()
        .put("state", state)
        .put("device", deviceName ?: JSONObject.NULL)
        .put("vid", vendorId)
        .put("pid", productId)
        .put("frames", frames)
        .put("crc_errors", crcErrors)
        .put("bytes", bytesRead)
        .put("error", lastError ?: JSONObject.NULL)
        .put("config_status", configStatus)

    private fun loop(activeGeneration: Int) {
        while (running && generation == activeGeneration) {
            val usb = context.getSystemService(UsbManager::class.java)
            val drivers = try {
                UsbSerialProber.getDefaultProber().findAllDrivers(usb)
                    .filter { it.device.vendorId == ESPRESSIF_VID }
            } catch (_: Exception) {
                emptyList()
            }
            val driver = drivers.firstOrNull { it.device.deviceName == preferredDevice }
                ?: drivers.firstOrNull()
            if (driver == null) {
                deviceName = null
                vendorId = 0
                productId = 0
                config = null
                state = "no_device"
                lastError = null
                sleep(RETRY_MS)
                continue
            }

            val device = driver.device
            deviceName = device.deviceName
            vendorId = device.vendorId
            productId = device.productId

            if (!usb.hasPermission(device)) {
                config = null
                state = "permission"
                lastError = null
                sleep(RETRY_MS)
                continue
            }

            val conn = try {
                usb.openDevice(device)
            } catch (_: Exception) {
                null
            }
            if (conn == null) {
                config = null
                state = "error"
                lastError = "USB open failed"
                sleep(RETRY_MS)
                continue
            }

            val serialPort = driver.ports[0]
            synchronized(lock) {
                connection = conn
                port = serialPort
            }
            try {
                serialPort.open(conn)
                serialPort.setParameters(
                    BAUD,
                    8,
                    UsbSerialPort.STOPBITS_1,
                    UsbSerialPort.PARITY_NONE,
                )
                try {
                    serialPort.setDTR(false)
                    serialPort.setRTS(false)
                } catch (_: IOException) {
                }

                configParser.reset()
                config = null
                configStatus = ""
                state = "connected"
                lastError = null

                val buffer = ByteArray(512)
                var lastConfigRequest = 0L
                while (running && generation == activeGeneration) {
                    val now = SystemClock.elapsedRealtime()
                    if (config == null && now - lastConfigRequest >= CONFIG_RETRY_MS) {
                        if (command.compareAndSet(null, DongleConfig.buildGetConfig())) {
                            lastConfigRequest = now
                        }
                    }
                    command.getAndSet(null)?.let { bytes ->
                        try {
                            serialPort.write(bytes, 1000)
                        } catch (e: IOException) {
                            configStatus = "write failed: ${e.message}"
                        }
                    }
                    val read = try {
                        serialPort.read(buffer, 200)
                    } catch (_: IOException) {
                        -1
                    }
                    if (read < 0) break
                    if (read > 0) {
                        bytesRead += read
                        framer.feed(buffer, read)
                        for (frame in configParser.feed(buffer, read)) {
                            handleConfigFrame(frame)
                        }
                    }
                }
            } catch (t: Throwable) {
                state = "error"
                lastError = t.message
            } finally {
                closePort()
            }

            if (running && generation == activeGeneration) {
                config = null
                state = "disconnected"
                sleep(RETRY_MS)
            }
        }
    }

    private fun handleConfigFrame(frame: DongleConfig.Frame) {
        when (frame.type) {
            DongleConfig.GET_CONFIG or DongleConfig.RESPONSE -> {
                val info = DongleConfig.parseConfig(frame.payload)
                if (info != null) config = info
                configStatus = DongleConfig.decodeConfig(frame.payload)
            }

            DongleConfig.SET_CONFIG or DongleConfig.RESPONSE -> {
                if (frame.payload.isNotEmpty() &&
                    (frame.payload[0].toInt() and 0xFF) == DongleConfig.OK
                ) {
                    command.compareAndSet(null, DongleConfig.buildGetConfig())
                }
                configStatus = "set: " + DongleConfig.decodeAck(frame.payload)
            }

            DongleConfig.SET_UID or DongleConfig.RESPONSE -> {
                if (frame.payload.isNotEmpty() &&
                    (frame.payload[0].toInt() and 0xFF) == DongleConfig.OK
                ) {
                    command.compareAndSet(null, DongleConfig.buildGetConfig())
                }
                configStatus = "set UID: " + DongleConfig.decodeAck(frame.payload)
            }

            DongleConfig.RESET or DongleConfig.RESPONSE -> {
                if (frame.payload.isNotEmpty() &&
                    (frame.payload[0].toInt() and 0xFF) == DongleConfig.OK
                ) {
                    command.compareAndSet(null, DongleConfig.buildGetConfig())
                }
                configStatus = "reset: " + DongleConfig.decodeAck(frame.payload)
            }

            DongleConfig.GET_STATS or DongleConfig.RESPONSE ->
                configStatus = "stats: " + DongleConfig.decodeStats(frame.payload)

            DongleConfig.PING or DongleConfig.RESPONSE ->
                configStatus = "ping: " + DongleConfig.decodeAck(frame.payload)

            else -> configStatus =
                "response 0x" + frame.type.toString(16).uppercase()
        }
    }

    private fun closePort() {
        synchronized(lock) {
            try {
                port?.close()
            } catch (_: Exception) {
            }
            try {
                connection?.close()
            } catch (_: Exception) {
            }
            port = null
            connection = null
        }
    }

    private fun sleep(millis: Long) {
        try {
            Thread.sleep(millis)
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
        }
    }

    private inner class CrsfFramer {
        private val buffer = ByteArray(8192)
        private var length = 0

        @Synchronized
        fun feed(data: ByteArray, count: Int) {
            if (count <= 0) return
            if (length + count > buffer.size) {
                val keep = minOf(length, 256)
                System.arraycopy(buffer, length - keep, buffer, 0, keep)
                length = keep
            }
            System.arraycopy(data, 0, buffer, length, count)
            length += count

            var i = 0
            while (i + 1 < length) {
                val address = buffer[i].toInt() and 0xFF
                if (address == 0xC8 || address == 0xEA || address == 0xEE) {
                    val frameLength = buffer[i + 1].toInt() and 0xFF
                    if (frameLength in 2..62) {
                        val total = frameLength + 2
                        if (i + total > length) break
                        val crcIndex = i + total - 1
                        if (crc8(buffer, i + 2, crcIndex) == (buffer[crcIndex].toInt() and 0xFF)) {
                            val frame = buffer.copyOfRange(i, i + total)
                            frames += 1
                            onFrame(frame)
                            onData()
                            i += total
                            continue
                        }
                        crcErrors += 1
                    }
                }
                i++
            }

            if (i > 0) {
                System.arraycopy(buffer, i, buffer, 0, length - i)
                length -= i
            }
        }

        private fun crc8(data: ByteArray, from: Int, until: Int): Int {
            var crc = 0
            for (i in from until until) {
                crc = crc xor (data[i].toInt() and 0xFF)
                repeat(8) {
                    crc = if ((crc and 0x80) != 0) {
                        ((crc shl 1) xor 0xD5) and 0xFF
                    } else {
                        (crc shl 1) and 0xFF
                    }
                }
            }
            return crc
        }
    }
}
