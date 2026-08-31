package com.leshine.expokiosk

import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.MediaStore
import android.webkit.JavascriptInterface
import android.widget.Toast
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executor

internal class KioskPrintBridge(
    private val context: Context,
    private val executor: Executor,
    private val runOnUi: ((() -> Unit) -> Unit),
    private val notifyWeb: (Boolean) -> Unit,
) {
    @JavascriptInterface
    fun printPhoto(imageUrl: String) {
        executor.execute {
            val savedUri = try {
                downloadAndSaveToGallery(imageUrl)
            } catch (_: Exception) {
                null
            }
            runOnUi {
                if (savedUri == null) {
                    toast("保存到相册失败，请重试")
                    notifyWeb(false)
                } else {
                    notifyWeb(true)
                    toast("已保存到相册，正在打开打印")
                    openPrinterApp()
                }
            }
        }
    }

    private fun downloadAndSaveToGallery(imageUrl: String): Uri? {
        val connection = (URL(imageUrl).openConnection() as HttpURLConnection).apply {
            connectTimeout = 15_000
            readTimeout = 20_000
            instanceFollowRedirects = true
            PinnedTls.apply(context, this)
        }
        connection.connect()
        if (connection.responseCode !in 200..299) return null
        val bytes = connection.inputStream.use { it.readBytes() }
        if (bytes.isEmpty()) return null

        val lower = imageUrl.lowercase()
        val isJpg = lower.endsWith(".jpg") || lower.endsWith(".jpeg")
        val mime = if (isJpg) "image/jpeg" else "image/png"
        val extension = if (isJpg) "jpg" else "png"
        val values = ContentValues().apply {
            put(
                MediaStore.Images.Media.DISPLAY_NAME,
                "leshine_tryon_${System.currentTimeMillis()}.$extension",
            )
            put(MediaStore.Images.Media.MIME_TYPE, mime)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                put(MediaStore.Images.Media.RELATIVE_PATH, "Pictures/LeShineTryOn")
                put(MediaStore.Images.Media.IS_PENDING, 1)
            }
        }
        val resolver = context.contentResolver
        val uri = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values) ?: return null
        val written = resolver.openOutputStream(uri)?.use { output ->
            output.write(bytes)
            output.flush()
            true
        } ?: false
        if (!written) {
            resolver.delete(uri, null, null)
            return null
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            values.clear()
            values.put(MediaStore.Images.Media.IS_PENDING, 0)
            resolver.update(uri, values, null, null)
        }
        val confirmed = resolver.query(
            uri,
            arrayOf(MediaStore.Images.Media._ID),
            null,
            null,
            null,
        )?.use { it.moveToFirst() } ?: false
        return uri.takeIf { confirmed }
    }

    private fun openPrinterApp() {
        val packageName = KioskExternalPackagePolicy.configuredPrinter(
            context.getString(R.string.printer_package),
        )
        val launch = packageName?.let {
            context.packageManager.getLaunchIntentForPackage(it)?.setPackage(it)
        }
        if (launch == null) {
            toast(context.getString(R.string.printer_unavailable))
            return
        }
        try {
            context.startActivity(launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        } catch (_: Exception) {
            toast(context.getString(R.string.printer_unavailable))
        }
    }

    private fun toast(message: String) =
        Toast.makeText(context, message, Toast.LENGTH_SHORT).show()
}
