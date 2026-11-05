package com.elrs.backpack

import android.content.ContentValues
import android.content.Context
import android.os.Build
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import android.webkit.JavascriptInterface
import android.widget.Toast
import java.io.File

class AndroidExport(private val context: Context) {

    private val handler = Handler(Looper.getMainLooper())

    @JavascriptInterface
    fun saveFile(fileName: String, mime: String, content: String) {
        val safeName = fileName
            .replace(Regex("[^A-Za-z0-9._-]"), "_")
            .ifBlank { "track.txt" }
        val location = try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                saveToDownloads(safeName, mime, content)
            } else {
                saveToAppDownloads(safeName, content)
            }
        } catch (_: Exception) {
            null
        }
        handler.post {
            val message = if (location != null) {
                context.getString(R.string.saved_to, location)
            } else {
                context.getString(R.string.save_failed, safeName)
            }
            Toast.makeText(context, message, Toast.LENGTH_LONG).show()
        }
    }

    private fun saveToDownloads(name: String, mime: String, content: String): String? {
        val relative = Environment.DIRECTORY_DOWNLOADS + "/ELRS Backpack"
        val values = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, name)
            put(MediaStore.Downloads.MIME_TYPE, mime)
            put(MediaStore.Downloads.RELATIVE_PATH, relative)
            put(MediaStore.Downloads.IS_PENDING, 1)
        }
        val resolver = context.contentResolver
        val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values) ?: return null
        try {
            val output = resolver.openOutputStream(uri) ?: return null
            output.use { it.write(content.toByteArray(Charsets.UTF_8)) }
            values.clear()
            values.put(MediaStore.Downloads.IS_PENDING, 0)
            resolver.update(uri, values, null, null)
        } catch (_: Exception) {
            resolver.delete(uri, null, null)
            return null
        }
        return "$relative/$name"
    }

    private fun saveToAppDownloads(name: String, content: String): String? {
        val dir = context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) ?: context.filesDir
        dir.mkdirs()
        val file = File(dir, name)
        file.writeText(content)
        return file.absolutePath
    }
}
