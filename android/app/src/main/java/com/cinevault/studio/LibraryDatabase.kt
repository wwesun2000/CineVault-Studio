package com.cinevault.studio

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import org.json.JSONArray
import org.json.JSONObject

class LibraryDatabase(context: Context) :
    SQLiteOpenHelper(context, "cinevault_android.db", null, 1) {

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            """
            CREATE TABLE IF NOT EXISTS media_items (
                item_id TEXT PRIMARY KEY,
                fast_hash TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_name TEXT NOT NULL,
                parent_dirs_json TEXT NOT NULL DEFAULT '[]',
                size_bytes INTEGER NOT NULL DEFAULT 0,
                mtime_epoch REAL NOT NULL DEFAULT 0.0,
                source_type TEXT NOT NULL DEFAULT 'local_disk',
                media_category TEXT NOT NULL DEFAULT 'western_adult',
                jav_code TEXT NOT NULL DEFAULT '',
                studio TEXT NOT NULL DEFAULT '',
                is_unknown_studio INTEGER NOT NULL DEFAULT 0,
                director TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                performers_json TEXT NOT NULL DEFAULT '[]',
                release_date TEXT NOT NULL DEFAULT '',
                tags_json TEXT NOT NULL DEFAULT '[]',
                duration_sec REAL NOT NULL DEFAULT 0.0,
                rating REAL NOT NULL DEFAULT 0.0,
                rating_half_steps INTEGER NOT NULL DEFAULT 0,
                user_keywords_json TEXT NOT NULL DEFAULT '[]',
                cover_path TEXT NOT NULL DEFAULT '',
                cover_source TEXT NOT NULL DEFAULT 'placeholder',
                diff_status TEXT NOT NULL DEFAULT 'unchanged',
                is_incomplete INTEGER NOT NULL DEFAULT 0,
                last_played_pos_sec REAL NOT NULL DEFAULT 0.0,
                play_count INTEGER NOT NULL DEFAULT 0,
                synopsis TEXT NOT NULL DEFAULT ''
            )
            """.trimIndent()
        )
        db.execSQL("CREATE INDEX IF NOT EXISTS idx_android_hash ON media_items(fast_hash)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        onCreate(db)
    }

    fun loadAllAsJsonArray(): JSONArray {
        val arr = JSONArray()
        val db = readableDatabase
        db.rawQuery("SELECT * FROM media_items ORDER BY release_date DESC, file_name ASC", null).use { c ->
            while (c.moveToNext()) {
                val obj = JSONObject()
                obj.put("item_id", c.getString(c.getColumnIndexOrThrow("item_id")))
                obj.put("fast_hash", c.getString(c.getColumnIndexOrThrow("fast_hash")))
                obj.put("file_path", c.getString(c.getColumnIndexOrThrow("file_path")))
                obj.put("file_name", c.getString(c.getColumnIndexOrThrow("file_name")))
                obj.put("parent_dirs", JSONArray(c.getString(c.getColumnIndexOrThrow("parent_dirs_json"))))
                obj.put("size_bytes", c.getLong(c.getColumnIndexOrThrow("size_bytes")))
                obj.put("mtime_epoch", c.getDouble(c.getColumnIndexOrThrow("mtime_epoch")))
                obj.put("source_type", c.getString(c.getColumnIndexOrThrow("source_type")))
                obj.put("media_category", c.getString(c.getColumnIndexOrThrow("media_category")))
                obj.put("jav_code", c.getString(c.getColumnIndexOrThrow("jav_code")))
                obj.put("studio", c.getString(c.getColumnIndexOrThrow("studio")))
                obj.put("is_unknown_studio", c.getInt(c.getColumnIndexOrThrow("is_unknown_studio")) != 0)
                obj.put("director", c.getString(c.getColumnIndexOrThrow("director")))
                obj.put("title", c.getString(c.getColumnIndexOrThrow("title")))
                obj.put("performers", JSONArray(c.getString(c.getColumnIndexOrThrow("performers_json"))))
                obj.put("release_date", c.getString(c.getColumnIndexOrThrow("release_date")))
                obj.put("tags", JSONArray(c.getString(c.getColumnIndexOrThrow("tags_json"))))
                obj.put("duration_sec", c.getDouble(c.getColumnIndexOrThrow("duration_sec")))
                obj.put("rating", c.getDouble(c.getColumnIndexOrThrow("rating")))
                obj.put("rating_half_steps", c.getInt(c.getColumnIndexOrThrow("rating_half_steps")))
                obj.put("user_keywords", JSONArray(c.getString(c.getColumnIndexOrThrow("user_keywords_json"))))
                obj.put("cover_path", c.getString(c.getColumnIndexOrThrow("cover_path")))
                obj.put("cover_source", c.getString(c.getColumnIndexOrThrow("cover_source")))
                obj.put("diff_status", c.getString(c.getColumnIndexOrThrow("diff_status")))
                obj.put("is_incomplete", c.getInt(c.getColumnIndexOrThrow("is_incomplete")) != 0)
                obj.put("last_played_pos_sec", c.getDouble(c.getColumnIndexOrThrow("last_played_pos_sec")))
                obj.put("play_count", c.getInt(c.getColumnIndexOrThrow("play_count")))
                obj.put("synopsis", c.getString(c.getColumnIndexOrThrow("synopsis")))
                arr.put(obj)
            }
        }
        return arr
    }

    fun upsertJsonItems(items: List<JSONObject>) {
        if (items.isEmpty()) return
        val db = writableDatabase
        db.beginTransaction()
        try {
            for (obj in items) {
                val cv = ContentValues().apply {
                    put("item_id", obj.optString("item_id"))
                    put("fast_hash", obj.optString("fast_hash"))
                    put("file_path", obj.optString("file_path"))
                    put("file_name", obj.optString("file_name"))
                    put("parent_dirs_json", (obj.optJSONArray("parent_dirs") ?: JSONArray()).toString())
                    put("size_bytes", obj.optLong("size_bytes", 0L))
                    put("mtime_epoch", obj.optDouble("mtime_epoch", 0.0))
                    put("source_type", obj.optString("source_type", "local_disk"))
                    put("media_category", obj.optString("media_category", "western_adult"))
                    put("jav_code", obj.optString("jav_code", ""))
                    put("studio", obj.optString("studio", ""))
                    put("is_unknown_studio", if (obj.optBoolean("is_unknown_studio", false)) 1 else 0)
                    put("director", obj.optString("director", ""))
                    put("title", obj.optString("title", ""))
                    put("performers_json", (obj.optJSONArray("performers") ?: JSONArray()).toString())
                    put("release_date", obj.optString("release_date", ""))
                    put("tags_json", (obj.optJSONArray("tags") ?: JSONArray()).toString())
                    put("duration_sec", obj.optDouble("duration_sec", 0.0))
                    put("rating", obj.optDouble("rating", 0.0))
                    put("rating_half_steps", obj.optInt("rating_half_steps", 0))
                    put("user_keywords_json", (obj.optJSONArray("user_keywords") ?: JSONArray()).toString())
                    put("cover_path", obj.optString("cover_path", ""))
                    put("cover_source", obj.optString("cover_source", "placeholder"))
                    put("diff_status", obj.optString("diff_status", "unchanged"))
                    put("is_incomplete", if (obj.optBoolean("is_incomplete", false)) 1 else 0)
                    put("last_played_pos_sec", obj.optDouble("last_played_pos_sec", 0.0))
                    put("play_count", obj.optInt("play_count", 0))
                    put("synopsis", obj.optString("synopsis", ""))
                }
                db.insertWithOnConflict("media_items", null, cv, SQLiteDatabase.CONFLICT_REPLACE)
            }
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    fun updateRating(itemId: String, rating: Double): Boolean {
        val halfSteps = (rating * 2.0).toInt().coerceIn(0, 10)
        val clamped = halfSteps / 2.0
        val cv = ContentValues().apply {
            put("rating", clamped)
            put("rating_half_steps", halfSteps)
        }
        return writableDatabase.update("media_items", cv, "item_id = ?", arrayOf(itemId)) > 0
    }

    fun updateUserKeywords(itemId: String, keywordsJson: String): Boolean {
        val cv = ContentValues().apply {
            put("user_keywords_json", keywordsJson)
        }
        return writableDatabase.update("media_items", cv, "item_id = ?", arrayOf(itemId)) > 0
    }
}
