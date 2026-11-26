package com.cinevault.studio

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.net.Uri
import android.provider.OpenableColumns
import androidx.documentfile.provider.DocumentFile
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.util.zip.ZipInputStream

data class LocalVideoEntry(
    val uriString: String,
    val fileName: String,
    val parentDirs: List<String>,
    val sizeBytes: Long,
    val mtimeEpoch: Double,
    val fastHash: String
)

object CvpackImporter {

    private val VIDEO_EXTENSIONS = setOf(
        "mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v", "ts", "rmvb"
    )

    fun importFromUri(context: Context, uri: Uri, db: LibraryDatabase): JSONObject {
        val displayName = queryDisplayName(context, uri).lowercase()
        val tempFile = File(context.cacheDir, "import_temp_${System.currentTimeMillis()}")
        try {
            context.contentResolver.openInputStream(uri)?.use { input ->
                FileOutputStream(tempFile).use { output ->
                    input.copyTo(output)
                }
            } ?: throw IllegalStateException("无法读取所选文件")

            val isZip = displayName.endsWith(".cvpack") || displayName.endsWith(".zip") || isZipHeader(tempFile)
            return if (isZip) {
                importCvpackZip(context, tempFile, db)
            } else {
                importSqliteDb(tempFile, db)
            }
        } finally {
            tempFile.delete()
        }
    }

    private fun isZipHeader(file: File): Boolean {
        if (!file.isFile || file.length() < 4) return false
        file.inputStream().use { ins ->
            val hdr = ByteArray(2)
            if (ins.read(hdr) < 2) return false
            return hdr[0] == 'P'.code.toByte() && hdr[1] == 'K'.code.toByte()
        }
    }

    private fun importCvpackZip(context: Context, zipFile: File, db: LibraryDatabase): JSONObject {
        val coversDir = File(context.filesDir, "covers").apply { mkdirs() }
        var libraryJsonText = ""
        var extractedCovers = 0

        ZipInputStream(zipFile.inputStream().buffered()).use { zis ->
            var entry = zis.nextEntry
            while (entry != null) {
                val name = entry.name.replace("\\", "/")
                if (!entry.isDirectory) {
                    if (name == "library_items.json") {
                        libraryJsonText = zis.readBytes().toString(Charsets.UTF_8)
                    } else if (name.startsWith("covers/")) {
                        val fileName = File(name).name
                        if (fileName.isNotEmpty() && !fileName.contains("..")) {
                            val outCover = File(coversDir, fileName)
                            FileOutputStream(outCover).use { fos -> zis.copyTo(fos) }
                            extractedCovers++
                        }
                    }
                }
                zis.closeEntry()
                entry = zis.nextEntry
            }
        }

        if (libraryJsonText.isEmpty()) {
            throw IllegalArgumentException("无效的 .cvpack 文件：缺少 library_items.json")
        }

        val rawArray = JSONArray(libraryJsonText)
        return reconcileAndSaveItems(context, rawArray, db, extractedCovers, "cvpack")
    }

    private fun importSqliteDb(dbFile: File, db: LibraryDatabase): JSONObject {
        val rawArray = JSONArray()
        val extDb = SQLiteDatabase.openDatabase(dbFile.absolutePath, null, SQLiteDatabase.OPEN_READONLY)
        extDb.use { sdb ->
            sdb.rawQuery("SELECT * FROM media_items", null).use { c ->
                while (c.moveToNext()) {
                    val obj = JSONObject()
                    for (idx in 0 until c.columnCount) {
                        val col = c.columnNames[idx]
                        when (col) {
                            "parent_dirs_json" -> obj.put("parent_dirs", JSONArray(c.getString(idx) ?: "[]"))
                            "performers_json" -> obj.put("performers", JSONArray(c.getString(idx) ?: "[]"))
                            "tags_json" -> obj.put("tags", JSONArray(c.getString(idx) ?: "[]"))
                            "user_keywords_json" -> obj.put("user_keywords", JSONArray(c.getString(idx) ?: "[]"))
                            "is_unknown_studio", "is_incomplete" -> obj.put(col, c.getInt(idx) != 0)
                            "size_bytes", "rating_half_steps", "play_count" -> obj.put(col, c.getLong(idx))
                            "mtime_epoch", "duration_sec", "rating", "last_played_pos_sec" -> obj.put(col, c.getDouble(idx))
                            else -> obj.put(col, c.getString(idx) ?: "")
                        }
                    }
                    rawArray.put(obj)
                }
            }
        }
        return reconcileAndSaveItems(null, rawArray, db, 0, "sqlite_db")
    }

    private fun reconcileAndSaveItems(
        context: Context?,
        rawArray: JSONArray,
        db: LibraryDatabase,
        extractedCovers: Int,
        importType: String
    ): JSONObject {
        val existingArr = db.loadAllAsJsonArray()
        val existingByHash = HashMap<String, JSONObject>()
        val existingBySizeName = HashMap<String, JSONObject>()
        for (i in 0 until existingArr.length()) {
            val ex = existingArr.getJSONObject(i)
            val fh = ex.optString("fast_hash")
            val fp = ex.optString("file_path")
            if (fp.startsWith("content://") || (fp.startsWith("/") && File(fp).exists())) {
                if (fh.isNotEmpty()) existingByHash[fh] = ex
                val key = "${ex.optLong("size_bytes")}|${ex.optString("file_name").lowercase()}"
                existingBySizeName[key] = ex
            }
        }

        val coversDir = context?.let { File(it.filesDir, "covers") }
        val toSave = ArrayList<JSONObject>(rawArray.length())
        var matchedByHash = 0
        var matchedBySizeName = 0
        var remoteOnly = 0

        for (i in 0 until rawArray.length()) {
            val obj = rawArray.getJSONObject(i)
            val itemId = obj.optString("item_id")
            val arcCover = obj.optString("bundled_cover_arcname")
            if (arcCover.isNotEmpty() && coversDir != null) {
                val fname = File(arcCover).name
                val localCover = File(coversDir, fname)
                if (localCover.isFile()) {
                    obj.put("cover_path", "https://appassets.androidplatform.net/covers/$fname")
                }
            } else if (coversDir != null && itemId.isNotEmpty()) {
                val fallbackCover = File(coversDir, "$itemId.jpg")
                if (fallbackCover.isFile()) {
                    obj.put("cover_path", "https://appassets.androidplatform.net/covers/$itemId.jpg")
                }
            }

            val fh = obj.optString("fast_hash")
            val sizeNameKey = "${obj.optLong("size_bytes")}|${obj.optString("file_name").lowercase()}"
            val localMatch = existingByHash[fh] ?: existingBySizeName[sizeNameKey]
            if (localMatch != null) {
                obj.put("file_path", localMatch.optString("file_path"))
                obj.put("diff_status", "unchanged")
                if (existingByHash.containsKey(fh)) matchedByHash++ else matchedBySizeName++
            } else {
                remoteOnly++
            }
            toSave.add(obj)
        }

        db.upsertJsonItems(toSave)

        return JSONObject().apply {
            put("status", "ok")
            put("import_type", importType)
            put("total", toSave.size)
            put("extracted_covers", extractedCovers)
            put("matched_by_hash", matchedByHash)
            put("matched_by_size_and_name", matchedBySizeName)
            put("unmatched_remote_only", remoteOnly)
        }
    }

    fun scanSafTreeAndReconcile(context: Context, treeUri: Uri, db: LibraryDatabase): JSONObject {
        val rootDoc = DocumentFile.fromTreeUri(context, treeUri)
            ?: throw IllegalStateException("无法访问所选目录")
        val scanned = ArrayList<LocalVideoEntry>()
        val rootName = rootDoc.name ?: "Android"
        walkDocumentTree(context, rootDoc, listOf(rootName), scanned)

        val byHash = HashMap<String, LocalVideoEntry>()
        val bySizeName = HashMap<String, LocalVideoEntry>()
        for (ent in scanned) {
            if (ent.fastHash.isNotEmpty()) byHash[ent.fastHash] = ent
            bySizeName["${ent.sizeBytes}|${ent.fileName.lowercase()}"] = ent
        }

        val existingArr = db.loadAllAsJsonArray()
        val updatedList = ArrayList<JSONObject>()
        val matchedKeys = HashSet<String>()
        var matchedByHash = 0
        var matchedBySizeName = 0

        for (i in 0 until existingArr.length()) {
            val obj = existingArr.getJSONObject(i)
            val fh = obj.optString("fast_hash")
            val sizeNameKey = "${obj.optLong("size_bytes")}|${obj.optString("file_name").lowercase()}"
            val hitHash = if (fh.isNotEmpty()) byHash[fh] else null
            val hitFallback = if (hitHash == null) bySizeName[sizeNameKey] else null
            val hit = hitHash ?: hitFallback
            if (hit != null) {
                obj.put("file_path", hit.uriString)
                obj.put("file_name", hit.fileName)
                obj.put("parent_dirs", JSONArray(hit.parentDirs))
                obj.put("source_type", "local_disk")
                obj.put("diff_status", "unchanged")
                updatedList.add(obj)
                if (hit.fastHash.isNotEmpty()) matchedKeys.add(hit.fastHash)
                if (hitHash != null) matchedByHash++ else matchedBySizeName++
            }
        }

        // Also register newly scanned local videos not yet in DB
        var addedNew = 0
        for (ent in scanned) {
            if (ent.fastHash.isNotEmpty() && matchedKeys.contains(ent.fastHash)) continue
            if (ent.fastHash.isEmpty()) continue
            val itemId = makeItemId(ent.fastHash)
            val obj = JSONObject().apply {
                put("item_id", itemId)
                put("fast_hash", ent.fastHash)
                put("file_path", ent.uriString)
                put("file_name", ent.fileName)
                put("parent_dirs", JSONArray(ent.parentDirs))
                put("size_bytes", ent.sizeBytes)
                put("mtime_epoch", ent.mtimeEpoch)
                put("source_type", "local_disk")
                put("media_category", "western_adult")
                put("title", ent.fileName.substringBeforeLast('.'))
                put("performers", JSONArray())
                put("tags", JSONArray())
                put("user_keywords", JSONArray())
                put("diff_status", "added")
                put("is_incomplete", true)
                put("cover_source", "placeholder")
            }
            updatedList.add(obj)
            addedNew++
        }

        db.upsertJsonItems(updatedList)
        return JSONObject().apply {
            put("status", "ok")
            put("scanned_count", scanned.size)
            put("matched_by_hash", matchedByHash)
            put("matched_by_size_and_name", matchedBySizeName)
            put("added_new", addedNew)
        }
    }

    private fun walkDocumentTree(
        context: Context,
        dir: DocumentFile,
        parentDirs: List<String>,
        out: MutableList<LocalVideoEntry>
    ) {
        for (child in dir.listFiles()) {
            val name = child.name ?: continue
            if (name.startsWith(".")) continue
            if (child.isDirectory) {
                walkDocumentTree(context, child, parentDirs + name, out)
            } else if (child.isFile) {
                val ext = name.substringAfterLast('.', "").lowercase()
                if (ext !in VIDEO_EXTENSIONS) continue
                val size = child.length()
                val mtime = child.lastModified() / 1000.0
                var hash = ""
                if (size > 0L) {
                    try {
                        context.contentResolver.openFileDescriptor(child.uri, "r")?.use { pfd ->
                            hash = Blake2b.computeFastFingerprint(pfd, size)
                        }
                    } catch (_: Exception) {
                    }
                }
                out.add(
                    LocalVideoEntry(
                        uriString = child.uri.toString(),
                        fileName = name,
                        parentDirs = parentDirs,
                        sizeBytes = size,
                        mtimeEpoch = mtime,
                        fastHash = hash
                    )
                )
            }
        }
    }

    private fun makeItemId(fastHash: String): String {
        val b = Blake2b(8)
        b.update(fastHash.toByteArray(Charsets.UTF_8))
        return "cv_${b.hexdigest()}"
    }

    private fun queryDisplayName(context: Context, uri: Uri): String {
        context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
            if (c.moveToFirst()) {
                val idx = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (idx >= 0) return c.getString(idx) ?: ""
            }
        }
        return uri.lastPathSegment ?: ""
    }
}
