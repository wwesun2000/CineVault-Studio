package com.cinevault.studio

import android.annotation.SuppressLint
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.webkit.WebViewAssetLoader
import org.json.JSONObject
import java.io.File
import java.util.concurrent.Executors

class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var db: LibraryDatabase
    private val ioExecutor = Executors.newSingleThreadExecutor()

    private val pickImportLauncher =
        registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri: Uri? ->
            if (uri == null) return@registerForActivityResult
            ioExecutor.execute {
                val resJson = try {
                    CvpackImporter.importFromUri(this, uri, db)
                } catch (e: Exception) {
                    JSONObject().apply {
                        put("status", "error")
                        put("message", e.message ?: "导入失败")
                    }
                }
                runOnUiThread {
                    val js = "window.onAndroidImportComplete && window.onAndroidImportComplete(${JSONObject.quote(resJson.toString())});"
                    webView.evaluateJavascript(js, null)
                }
            }
        }

    private val pickFolderLauncher =
        registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { treeUri: Uri? ->
            if (treeUri == null) return@registerForActivityResult
            try {
                contentResolver.takePersistableUriPermission(
                    treeUri,
                    Intent.FLAG_GRANT_READ_URI_PERMISSION
                )
            } catch (_: Exception) {
            }
            ioExecutor.execute {
                val resJson = try {
                    CvpackImporter.scanSafTreeAndReconcile(this, treeUri, db)
                } catch (e: Exception) {
                    JSONObject().apply {
                        put("status", "error")
                        put("message", e.message ?: "扫描失败")
                    }
                }
                runOnUiThread {
                    val js = "window.onAndroidScanComplete && window.onAndroidScanComplete(${JSONObject.quote(resJson.toString())});"
                    webView.evaluateJavascript(js, null)
                }
            }
        }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        db = LibraryDatabase(this)
        val coversDir = File(filesDir, "covers").apply { mkdirs() }

        val assetLoader = WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .addPathHandler("/covers/", WebViewAssetLoader.InternalStoragePathHandler(this, coversDir))
            .build()

        webView = WebView(this)
        setContentView(webView)

        val ws: WebSettings = webView.settings
        ws.javaScriptEnabled = true
        ws.domStorageEnabled = true
        ws.allowFileAccess = true
        ws.mediaPlaybackRequiresUserGesture = false

        webView.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(
                view: WebView,
                request: WebResourceRequest
            ): WebResourceResponse? {
                return assetLoader.shouldInterceptRequest(request.url)
            }
        }

        webView.addJavascriptInterface(AndroidBridge(), "CineVaultAndroid")
        webView.loadUrl("https://appassets.androidplatform.net/assets/index.html")
    }

    override fun onDestroy() {
        ioExecutor.shutdownNow()
        super.onDestroy()
    }

    inner class AndroidBridge {

        @JavascriptInterface
        fun getLibraryJson(): String {
            return db.loadAllAsJsonArray().toString()
        }

        @JavascriptInterface
        fun updateRating(itemId: String, rating: Double): Boolean {
            return db.updateRating(itemId, rating)
        }

        @JavascriptInterface
        fun updateKeywords(itemId: String, keywordsJson: String): Boolean {
            return db.updateUserKeywords(itemId, keywordsJson)
        }

        @JavascriptInterface
        fun pickImportFile() {
            runOnUiThread {
                pickImportLauncher.launch(arrayOf("*/*"))
            }
        }

        @JavascriptInterface
        fun pickScanFolder() {
            runOnUiThread {
                pickFolderLauncher.launch(null)
            }
        }

        @JavascriptInterface
        fun playInVlc(filePath: String, title: String, startSec: Double) {
            runOnUiThread {
                if (filePath.isBlank()) {
                    Toast.makeText(this@MainActivity, "文件路径为空", Toast.LENGTH_SHORT).show()
                    return@runOnUiThread
                }
                val videoUri = when {
                    filePath.startsWith("content://") ||
                        filePath.startsWith("http://") ||
                        filePath.startsWith("https://") ||
                        filePath.startsWith("smb://") -> Uri.parse(filePath)
                    filePath.startsWith("\\\\") -> {
                        val smbPath = "smb:" + filePath.replace("\\", "/")
                        Uri.parse(smbPath)
                    }
                    else -> Uri.fromFile(File(filePath))
                }

                val vlcIntent = Intent(Intent.ACTION_VIEW).apply {
                    setDataAndType(videoUri, "video/*")
                    setPackage("org.videolan.vlc")
                    putExtra("title", title)
                    if (startSec > 1.0) {
                        putExtra("position", (startSec * 1000).toLong())
                    }
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                }

                try {
                    startActivity(vlcIntent)
                } catch (_: Exception) {
                    val fallback = Intent(Intent.ACTION_VIEW).apply {
                        setDataAndType(videoUri, "video/*")
                        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    }
                    try {
                        startActivity(Intent.createChooser(fallback, "选择播放器播放"))
                    } catch (_: Exception) {
                        Toast.makeText(
                            this@MainActivity,
                            "未找到 VLC 或兼容视频播放器，且该文件可能仅存在于电脑端路径",
                            Toast.LENGTH_LONG
                        ).show()
                    }
                }
            }
        }
    }
}
