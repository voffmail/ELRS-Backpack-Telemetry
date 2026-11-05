package com.elrs.backpack

import android.content.Context
import android.net.Uri
import android.provider.DocumentsContract
import androidx.documentfile.provider.DocumentFile
import java.io.File

interface TrackStore {
    fun listIds(): List<String>
    fun read(id: String): String?
    fun write(id: String, json: String): Boolean
    fun delete(id: String): Boolean
    fun location(): String
    fun isUsable(): Boolean = true
}

class FileTrackStore(private val dir: File) : TrackStore {

    override fun listIds(): List<String> {
        dir.mkdirs()
        return dir.listFiles { file -> file.isFile && file.name.endsWith(".json") }
            ?.map { it.name.removeSuffix(".json") }
            ?: emptyList()
    }

    override fun read(id: String): String? = try {
        File(dir, "$id.json").readText()
    } catch (_: Exception) {
        null
    }

    override fun write(id: String, json: String): Boolean = try {
        dir.mkdirs()
        File(dir, "$id.json").writeText(json)
        true
    } catch (_: Exception) {
        false
    }

    override fun delete(id: String): Boolean = try {
        File(dir, "$id.json").delete()
    } catch (_: Exception) {
        false
    }

    override fun location(): String = dir.absolutePath
}

class SafTrackStore(
    private val context: Context,
    private val uri: Uri,
) : TrackStore {

    private val tree: DocumentFile? = try {
        DocumentFile.fromTreeUri(context, uri)
    } catch (_: Exception) {
        null
    }

    private fun find(id: String): DocumentFile? =
        tree?.listFiles()?.firstOrNull { it.isFile && it.name == "$id.json" }

    override fun listIds(): List<String> =
        tree?.listFiles()
            ?.filter { it.isFile && it.name?.endsWith(".json") == true }
            ?.mapNotNull { it.name?.removeSuffix(".json") }
            ?: emptyList()

    override fun read(id: String): String? {
        val file = find(id) ?: return null
        return try {
            context.contentResolver.openInputStream(file.uri)?.bufferedReader()?.use { it.readText() }
        } catch (_: Exception) {
            null
        }
    }

    override fun write(id: String, json: String): Boolean {
        val parent = tree ?: return false
        val existing = find(id)
        val file = existing ?: try {
            parent.createFile("application/json", "$id.json")
        } catch (_: Exception) {
            null
        } ?: return false
        return try {
            val output = context.contentResolver.openOutputStream(file.uri, "wt") ?: return false
            output.use { it.write(json.toByteArray(Charsets.UTF_8)) }
            true
        } catch (_: Exception) {
            false
        }
    }

    override fun delete(id: String): Boolean = try {
        find(id)?.delete() ?: false
    } catch (_: Exception) {
        false
    }

    override fun location(): String {
        val name = tree?.name
        val documentId = try {
            DocumentsContract.getTreeDocumentId(uri)
        } catch (_: Exception) {
            null
        }
        return when {
            !name.isNullOrBlank() && !documentId.isNullOrBlank() -> "$name ($documentId)"
            !name.isNullOrBlank() -> name
            else -> uri.toString()
        }
    }

    override fun isUsable(): Boolean = try {
        tree?.canWrite() == true
    } catch (_: Exception) {
        false
    }
}
