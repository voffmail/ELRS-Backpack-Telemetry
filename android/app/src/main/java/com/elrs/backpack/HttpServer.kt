package com.elrs.backpack

import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.URLDecoder
import java.util.concurrent.Executors

interface SettingsHost {
    fun settingsJson(): String
    fun changeUdpPort(port: Int): Pair<Boolean, String>
    fun changeIdleReleaseMinutes(minutes: Int): Pair<Boolean, String>
    fun changeAutoRecordOn3d(enabled: Boolean): Pair<Boolean, String>
    fun changeAutoStopRecordingSeconds(seconds: Int): Pair<Boolean, String>
}

class HttpServer(
    private val state: TelemetryState,
    private val page: String,
    private val port: Int,
    private val host: SettingsHost,
) {

    private data class Request(val method: String, val target: String, val body: String)

    private data class Response(
        val status: Int,
        val contentType: String,
        val body: ByteArray,
    )

    private val executor = Executors.newCachedThreadPool()
    @Volatile
    private var running = true
    private var serverSocket: ServerSocket? = null

    fun start(): Boolean {
        if (serverSocket != null && running) return true
        return try {
            val socket = ServerSocket()
            socket.reuseAddress = true
            socket.bind(InetSocketAddress("127.0.0.1", port))
            serverSocket = socket
            val thread = Thread({ acceptLoop(socket) }, "elrs-http")
            thread.isDaemon = true
            thread.start()
            true
        } catch (_: Exception) {
            // Port unavailable or socket closed; the service keeps the UDP side alive.
            false
        }
    }

    private fun acceptLoop(socket: ServerSocket) {
        while (running) {
            val client = try {
                socket.accept()
            } catch (_: Exception) {
                break
            }
            executor.execute { handle(client) }
        }
    }

    fun stop() {
        running = false
        try {
            serverSocket?.close()
        } catch (_: Exception) {
        }
        executor.shutdownNow()
    }

    private fun handle(client: Socket) {
        try {
            client.use { socket ->
                socket.soTimeout = 10000
                val request = readRequest(socket.getInputStream()) ?: return
                val response = route(request)
                writeResponse(socket.getOutputStream(), response)
            }
        } catch (_: Exception) {
        }
    }

    private fun readRequest(input: InputStream): Request? {
        val headers = ByteArrayOutputStream()
        var matched = 0
        val one = ByteArray(1)
        while (headers.size() < 16384) {
            val read = input.read(one)
            if (read < 0) return null
            headers.write(one[0].toInt())
            matched = when {
                one[0].toInt() == '\r'.code && (matched == 0 || matched == 2) -> matched + 1
                one[0].toInt() == '\n'.code && (matched == 1 || matched == 3) -> matched + 1
                else -> if (one[0].toInt() == '\r'.code) 1 else 0
            }
            if (matched == 4) break
        }
        val headerText = headers.toString("ISO-8859-1")
        val lines = headerText.split("\r\n")
        if (lines.isEmpty()) return null
        val requestLine = lines[0].split(" ")
        if (requestLine.size < 2) return null

        var contentLength = 0
        for (line in lines.drop(1)) {
            val colon = line.indexOf(':')
            if (colon > 0 && line.substring(0, colon).equals("Content-Length", ignoreCase = true)) {
                contentLength = line.substring(colon + 1).trim().toIntOrNull() ?: 0
            }
        }
        var remaining = contentLength.coerceIn(0, 1 shl 20)
        val body = ByteArrayOutputStream()
        val scratch = ByteArray(1024)
        while (remaining > 0) {
            val read = input.read(scratch, 0, minOf(scratch.size, remaining))
            if (read < 0) break
            body.write(scratch, 0, read)
            remaining -= read
        }
        return Request(requestLine[0].uppercase(), requestLine[1], body.toString("UTF-8"))
    }

    private fun route(request: Request): Response {
        val question = request.target.indexOf('?')
        val path = if (question >= 0) request.target.substring(0, question) else request.target
        val query = if (question >= 0) request.target.substring(question + 1) else ""

        return when (request.method) {
            "GET" -> get(path, query)
            "POST" -> post(path, request.body)
            "DELETE" -> delete(path)
            else -> Response(405, "application/json; charset=utf-8", "{\"error\":\"method not allowed\"}".toByteArray())
        }
    }

    private fun get(path: String, query: String): Response = when {
        path == "/" || path == "/index.html" ->
            Response(200, "text/html; charset=utf-8", page.toByteArray(Charsets.UTF_8))

        path == "/api/state" -> json(state.snapshotJson())

        path == "/api/record" -> {
            val since = queryParam(query, "since")?.toIntOrNull() ?: 0
            json(state.recordSnapshotJson(since))
        }

        path == "/api/tracks" -> json(state.listTracksJson())

        path == "/api/settings" -> json(host.settingsJson())

        path.startsWith("/api/tracks/") -> {
            val track = state.loadTrackJson(decode(path.removePrefix("/api/tracks/")))
            if (track == null) notFound() else json(track)
        }

        else -> notFound()
    }

    private fun post(path: String, body: String): Response {
        return when (path) {
            "/api/record/start" -> {
                val (ok, error) = state.startRecording()
                if (ok) {
                    val payload = JSONObject()
                        .put("ok", true)
                        .put("record", JSONObject(state.recordSnapshotJson(0)))
                    json(payload.toString())
                } else {
                    json(JSONObject().put("ok", false).put("error", error).toString(), 409)
                }
            }

            "/api/record/stop" -> {
                val (meta, error) = state.stopRecording()
                if (meta == null) {
                    json(JSONObject().put("ok", false).put("error", error).toString(), 400)
                } else {
                    json(JSONObject().put("ok", true).put("track", meta).toString())
                }
            }

            "/api/settings" -> {
                val data = try {
                    JSONObject(body)
                } catch (_: Exception) {
                    null
                }
                if (data == null) {
                    json(JSONObject().put("ok", false).put("error", "invalid json").toString(), 400)
                } else if (!data.has("udp_port") && !data.has("idle_release_min") &&
                    !data.has("auto_record_3d") && !data.has("auto_stop_recording_sec")) {
                    json(JSONObject().put("ok", false).put("error", "no settings").toString(), 400)
                } else {
                    var error: String? = null
                    if (data.has("udp_port")) {
                        val newPort = data.optInt("udp_port", -1)
                        if (newPort !in 1..65535) {
                            error = "port must be 1..65535"
                        } else {
                            val (ok, portError) = host.changeUdpPort(newPort)
                            if (!ok) error = portError
                        }
                    }
                    if (error == null && data.has("idle_release_min")) {
                        val minutes = data.optInt("idle_release_min", -1)
                        if (minutes !in 0..1440) {
                            error = "idle timeout must be 0..1440"
                        } else {
                            val (ok, idleError) = host.changeIdleReleaseMinutes(minutes)
                            if (!ok) error = idleError
                        }
                    }
                    if (error == null && data.has("auto_record_3d")) {
                        val enabled = data.optBoolean("auto_record_3d", false)
                        val (ok, autoError) = host.changeAutoRecordOn3d(enabled)
                        if (!ok) error = autoError
                    }
                    if (error == null && data.has("auto_stop_recording_sec")) {
                        val seconds = data.optInt("auto_stop_recording_sec", -1)
                        if (seconds !in 0..3600) {
                            error = "auto stop recording timeout must be 0..3600"
                        } else {
                            val (ok, autoStopError) = host.changeAutoStopRecordingSeconds(seconds)
                            if (!ok) error = autoStopError
                        }
                    }
                    if (error == null) {
                        json(
                            JSONObject()
                                .put("ok", true)
                                .put("settings", JSONObject(host.settingsJson()))
                                .toString(),
                        )
                    } else {
                        json(JSONObject().put("ok", false).put("error", error).toString(), 409)
                    }
                }
            }

            else -> notFound()
        }
    }

    private fun delete(path: String): Response = when {
        path.startsWith("/api/tracks/") -> {
            if (state.deleteTrack(decode(path.removePrefix("/api/tracks/")))) {
                json(JSONObject().put("ok", true).toString())
            } else {
                notFound()
            }
        }

        else -> notFound()
    }

    private fun json(body: String, status: Int = 200): Response =
        Response(status, "application/json; charset=utf-8", body.toByteArray(Charsets.UTF_8))

    private fun notFound(): Response =
        json(JSONObject().put("error", "not found").toString(), 404)

    private fun queryParam(query: String, name: String): String? {
        if (query.isEmpty()) return null
        for (part in query.split("&")) {
            val equals = part.indexOf('=')
            val key = if (equals >= 0) part.substring(0, equals) else part
            if (key == name) {
                return if (equals >= 0) decode(part.substring(equals + 1)) else ""
            }
        }
        return null
    }

    private fun decode(value: String): String = try {
        URLDecoder.decode(value, "UTF-8")
    } catch (_: Exception) {
        value
    }

    private fun writeResponse(output: OutputStream, response: Response) {
        val reason = when (response.status) {
            200 -> "OK"
            400 -> "Bad Request"
            404 -> "Not Found"
            405 -> "Method Not Allowed"
            409 -> "Conflict"
            else -> "Error"
        }
        val header = buildString {
            append("HTTP/1.1 ").append(response.status).append(' ').append(reason).append("\r\n")
            append("Content-Type: ").append(response.contentType).append("\r\n")
            append("Cache-Control: no-store\r\n")
            append("Content-Length: ").append(response.body.size).append("\r\n")
            append("Connection: close\r\n\r\n")
        }
        output.write(header.toByteArray(Charsets.US_ASCII))
        output.write(response.body)
        output.flush()
    }
}
