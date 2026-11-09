package com.elrs.backpack

import android.content.res.AssetManager
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.InputStream
import java.io.OutputStream
import java.io.RandomAccessFile
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.URLDecoder
import java.util.concurrent.Executors

interface SettingsHost {
    fun settingsJson(): String
    fun changeUdpPort(port: Int): Pair<Boolean, String>
    fun changeSource(source: String): Pair<Boolean, String>
    fun dongleJson(): String
    fun dongleCommand(action: String, phrase: String?, uid: String?): Pair<Boolean, String>
    fun changeIdleReleaseMinutes(minutes: Int): Pair<Boolean, String>
    fun changeAutoRecordOn3d(enabled: Boolean): Pair<Boolean, String>
    fun changeAutoStopRecordingSeconds(seconds: Int): Pair<Boolean, String>
    fun changeKeepTracks(count: Int?): Pair<Boolean, String>
}

class HttpServer(
    private val state: TelemetryState,
    private val page: String,
    private val port: Int,
    private val host: SettingsHost,
    private val assets: AssetManager,
    private val tilesDir: File,
) {

    private data class Request(
        val method: String,
        val target: String,
        val body: String,
        val headers: Map<String, String>,
    )

    private data class Response(
        val status: Int,
        val contentType: String,
        val body: ByteArray,
        val headers: Map<String, String> = emptyMap(),
        val cacheControl: String = "no-store",
        val file: File? = null,
        val fileOffset: Long = 0,
        val fileLength: Long = -1,
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
        val headerBytes = ByteArrayOutputStream()
        var matched = 0
        val one = ByteArray(1)
        while (headerBytes.size() < 16384) {
            val read = input.read(one)
            if (read < 0) return null
            headerBytes.write(one[0].toInt())
            matched = when {
                one[0].toInt() == '\r'.code && (matched == 0 || matched == 2) -> matched + 1
                one[0].toInt() == '\n'.code && (matched == 1 || matched == 3) -> matched + 1
                else -> if (one[0].toInt() == '\r'.code) 1 else 0
            }
            if (matched == 4) break
        }
        val headerText = headerBytes.toString("ISO-8859-1")
        val lines = headerText.split("\r\n")
        if (lines.isEmpty()) return null
        val requestLine = lines[0].split(" ")
        if (requestLine.size < 2) return null

        var contentLength = 0
        val headers = LinkedHashMap<String, String>()
        for (line in lines.drop(1)) {
            val colon = line.indexOf(':')
            if (colon <= 0) continue
            val name = line.substring(0, colon).trim()
            val value = line.substring(colon + 1).trim()
            headers[name.lowercase()] = value
            if (name.equals("Content-Length", ignoreCase = true)) {
                contentLength = value.toIntOrNull() ?: 0
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
        return Request(requestLine[0].uppercase(), requestLine[1], body.toString("UTF-8"), headers)
    }

    private fun route(request: Request): Response {
        val question = request.target.indexOf('?')
        val path = if (question >= 0) request.target.substring(0, question) else request.target
        val query = if (question >= 0) request.target.substring(question + 1) else ""

        return when (request.method) {
            "GET" -> get(path, query, request.headers)
            "POST" -> post(path, request.body)
            "DELETE" -> delete(path)
            else -> Response(405, "application/json; charset=utf-8", "{\"error\":\"method not allowed\"}".toByteArray())
        }
    }

    private fun get(path: String, query: String, headers: Map<String, String>): Response = when {
        path == "/" || path == "/index.html" ->
            Response(200, "text/html; charset=utf-8", page.toByteArray(Charsets.UTF_8))

        path.startsWith("/static/") -> serveAsset(path.removePrefix("/static/"))

        path.startsWith("/tiles/") -> serveTile(path.removePrefix("/tiles/"), headers)

        path == "/api/state" -> json(state.snapshotJson())

        path == "/api/record" -> {
            val since = queryParam(query, "since")?.toIntOrNull() ?: 0
            json(state.recordSnapshotJson(since))
        }

        path == "/api/tracks" -> json(state.listTracksJson())

        path == "/api/settings" -> json(host.settingsJson())

        path == "/api/dongle" -> json(host.dongleJson())

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

            "/api/dongle" -> {
                val data = try {
                    JSONObject(body)
                } catch (_: Exception) {
                    null
                }
                if (data == null) {
                    json(JSONObject().put("ok", false).put("error", "invalid json").toString(), 400)
                } else {
                    val action = data.optString("action", "")
                    val phrase = if (data.has("phrase") && !data.isNull("phrase")) data.optString("phrase") else null
                    val uid = if (data.has("uid") && !data.isNull("uid")) data.optString("uid") else null
                    val (ok, error) = host.dongleCommand(action, phrase, uid)
                    if (ok) {
                        json(
                            JSONObject()
                                .put("ok", true)
                                .put("dongle", JSONObject(host.dongleJson()))
                                .toString(),
                        )
                    } else {
                        json(JSONObject().put("ok", false).put("error", error).toString(), 409)
                    }
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
                } else if (!data.has("udp_port") && !data.has("source") && !data.has("idle_release_min") &&
                    !data.has("auto_record_3d") && !data.has("auto_stop_recording_sec") &&
                    !data.has("keep_tracks")) {
                    json(JSONObject().put("ok", false).put("error", "no settings").toString(), 400)
                } else {
                    var error: String? = null
                    if (data.has("source")) {
                        val source = data.optString("source", "")
                        val (ok, sourceError) = host.changeSource(source)
                        if (!ok) error = sourceError
                    }
                    if (error == null && data.has("udp_port")) {
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
                    if (error == null && data.has("keep_tracks")) {
                        val raw = if (data.isNull("keep_tracks")) null else data.optInt("keep_tracks", 0)
                        val count = raw?.takeIf { it > 0 }
                        if (raw != null && count == null) {
                            error = "keep tracks must be greater than 0"
                        } else {
                            val (ok, keepError) = host.changeKeepTracks(count)
                            if (!ok) error = keepError
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

    private fun serveAsset(relative: String): Response {
        val name = decode(relative)
        if (name.isEmpty() || name.contains("..")) return notFound()
        return try {
            val bytes = assets.open("static/$name").use { it.readBytes() }
            Response(200, mimeType(name), bytes, cacheControl = "no-store")
        } catch (_: Exception) {
            notFound()
        }
    }

    private fun serveTile(relative: String, headers: Map<String, String>): Response {
        val name = decode(relative)
        if (name.isEmpty() || name.contains("..")) return notFound()
        val root = try {
            tilesDir.canonicalFile
        } catch (_: Exception) {
            return notFound()
        }
        val file = try {
            File(root, name).canonicalFile
        } catch (_: Exception) {
            return notFound()
        }
        if (file.path != root.path && !file.path.startsWith(root.path + File.separator)) return notFound()
        if (!file.isFile) return notFound()
        val size = file.length()
        val cache = "public, max-age=3600"
        val range = headers["range"]
        if (range == null) {
            return Response(
                200,
                mimeType(name),
                ByteArray(0),
                mapOf("Accept-Ranges" to "bytes"),
                cache,
                file,
                0,
                size,
            )
        }
        val parsed = parseRange(range, size)
        if (parsed == null) {
            return Response(
                416,
                "text/plain; charset=utf-8",
                ByteArray(0),
                mapOf("Content-Range" to "bytes */$size", "Accept-Ranges" to "bytes"),
                cache,
            )
        }
        return Response(
            206,
            mimeType(name),
            ByteArray(0),
            mapOf(
                "Content-Range" to "bytes ${parsed.first}-${parsed.last}/$size",
                "Accept-Ranges" to "bytes",
            ),
            cache,
            file,
            parsed.first,
            parsed.last - parsed.first + 1,
        )
    }

    private fun parseRange(header: String, size: Long): LongRange? {
        val value = header.trim()
        if (!value.startsWith("bytes=", ignoreCase = true)) return null
        val spec = value.substringAfter("=").substringBefore(',').trim()
        val dash = spec.indexOf('-')
        if (dash < 0) return null
        val startText = spec.substring(0, dash).trim()
        val endText = spec.substring(dash + 1).trim()
        if (size <= 0) return null
        val start: Long
        var end: Long
        try {
            if (startText.isEmpty()) {
                val suffix = endText.toLong()
                if (suffix <= 0) return null
                start = maxOf(0L, size - suffix)
                end = size - 1
            } else {
                start = startText.toLong()
                end = if (endText.isEmpty()) size - 1 else endText.toLong()
            }
        } catch (_: Exception) {
            return null
        }
        if (start < 0 || start >= size || end < start) return null
        end = minOf(end, size - 1)
        return start..end
    }

    private fun mimeType(name: String): String = when {
        name.endsWith(".js") -> "application/javascript; charset=utf-8"
        name.endsWith(".css") -> "text/css; charset=utf-8"
        name.endsWith(".json") -> "application/json; charset=utf-8"
        name.endsWith(".pmtiles") -> "application/vnd.pmtiles"
        name.endsWith(".png") -> "image/png"
        name.endsWith(".jpg") || name.endsWith(".jpeg") -> "image/jpeg"
        name.endsWith(".svg") -> "image/svg+xml"
        name.endsWith(".woff2") -> "font/woff2"
        else -> "application/octet-stream"
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
            206 -> "Partial Content"
            400 -> "Bad Request"
            404 -> "Not Found"
            405 -> "Method Not Allowed"
            409 -> "Conflict"
            416 -> "Range Not Satisfiable"
            else -> "Error"
        }
        val fileLength = response.file?.let {
            if (response.fileLength >= 0) response.fileLength else it.length()
        } ?: -1L
        val contentLength = if (response.file != null) fileLength else response.body.size.toLong()
        val header = buildString {
            append("HTTP/1.1 ").append(response.status).append(' ').append(reason).append("\r\n")
            append("Content-Type: ").append(response.contentType).append("\r\n")
            append("Cache-Control: ").append(response.cacheControl).append("\r\n")
            append("Content-Length: ").append(contentLength).append("\r\n")
            for ((name, value) in response.headers) {
                append(name).append(": ").append(value).append("\r\n")
            }
            append("Connection: close\r\n\r\n")
        }
        output.write(header.toByteArray(Charsets.US_ASCII))
        val file = response.file
        if (file != null) {
            RandomAccessFile(file, "r").use { raf ->
                raf.seek(response.fileOffset)
                var remaining = fileLength
                val buffer = ByteArray(64 * 1024)
                while (remaining > 0) {
                    val read = raf.read(buffer, 0, minOf(buffer.size.toLong(), remaining).toInt())
                    if (read < 0) break
                    output.write(buffer, 0, read)
                    remaining -= read
                }
            }
        } else {
            output.write(response.body)
        }
        output.flush()
    }
}
