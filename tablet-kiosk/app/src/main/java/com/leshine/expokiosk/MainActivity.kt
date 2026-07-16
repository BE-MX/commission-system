package com.leshine.expokiosk

import android.annotation.SuppressLint
import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.MediaStore
import android.view.View
import android.view.WindowManager
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.PermissionRequest
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

/**
 * 莱莎展会 AI 试戴 — 平板 kiosk 壳。
 *
 * 职责：全屏沉浸加载 leshine.work/expo/kiosk；给网页授摄像头权限；提供原生「一键打印」桥
 * （下载合成原图 → 写进系统相册 → 查回确认存好 → 才启动打印 App，严格此顺序）；
 * 设备所有者时开 Lock Task 真锁定（白名单含自身 + 打印 App）。
 */
class MainActivity : ComponentActivity() {

    private lateinit var webView: WebView
    private val io = Executors.newSingleThreadExecutor()
    private var pendingFileCallback: ValueCallback<Array<Uri>>? = null

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) // 屏幕常亮
        requestRuntimePermissions()

        webView = WebView(this)
        setContentView(webView)

        with(webView.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true                       // 登录态/流程依赖 localStorage
            mediaPlaybackRequiresUserGesture = false       // 允许 getUserMedia 直接起摄像头
            cacheMode = WebSettings.LOAD_DEFAULT
            allowFileAccess = false
        }
        CookieManager.getInstance().apply {
            setAcceptCookie(true)
            setAcceptThirdPartyCookies(webView, true)       // refresh_token 是 cookie，要收
        }

        webView.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView?, url: String?) {
                // 保险：标记桌面模式，杜绝任何移动端重定向（/expo 已豁免，这里再兜一层）
                view?.evaluateJavascript("try{sessionStorage.setItem('ark_desktop_mode','1')}catch(e){}", null)
            }
        }

        webView.webChromeClient = object : WebChromeClient() {
            override fun onPermissionRequest(request: PermissionRequest) {
                runOnUiThread { request.grant(request.resources) } // 摄像头/麦克风授给网页
            }
            override fun onShowFileChooser(
                view: WebView?,
                filePathCallback: ValueCallback<Array<Uri>>?,
                params: FileChooserParams?,
            ): Boolean {
                pendingFileCallback = filePathCallback
                val intent = params?.createIntent() ?: run { pendingFileCallback = null; return false }
                return try {
                    startActivityForResult(intent, FILE_CHOOSER_REQ)
                    true
                } catch (e: Exception) {
                    pendingFileCallback = null
                    false
                }
            }
        }

        webView.addJavascriptInterface(WebBridge(), "Android")
        webView.loadUrl(getString(R.string.start_url))
    }

    override fun onResume() {
        super.onResume()
        hideSystemBars()
        setupLockTask()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) hideSystemBars()
    }

    @Suppress("DEPRECATION")
    private fun hideSystemBars() {
        window.decorView.systemUiVisibility = (
            View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                or View.SYSTEM_UI_FLAG_FULLSCREEN
                or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                or View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
            )
    }

    /**
     * 仅当本应用是「设备所有者」时才真 Lock Task 锁定（含打印 App 白名单）。
     * 非设备所有者**不调** startLockTask()——否则会触发烦人的「屏幕固定」（可被 Back+Recents 退出、
     * 且每次 onResume 反复固定）。要硬锁展位平板请按 README 用 ADB 设为设备所有者；
     * 不设时应用仍是全屏沉浸，只是不强制固定屏幕。
     */
    private fun setupLockTask() {
        try {
            val dpm = getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
            if (dpm.isDeviceOwnerApp(packageName)) {
                val admin = ComponentName(this, AdminReceiver::class.java)
                val pkgs = mutableListOf(packageName)
                getString(R.string.printer_package).trim().takeIf { it.isNotEmpty() }?.let { pkgs.add(it) }
                dpm.setLockTaskPackages(admin, pkgs.toTypedArray())
                startLockTask()
            }
        } catch (e: Exception) { /* 忽略，仍是全屏沉浸 */ }
    }

    /** 展位不允许返回退出 kiosk：吞掉返回键。 */
    @Suppress("OVERRIDE_DEPRECATION")
    override fun onBackPressed() { /* no-op */ }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == FILE_CHOOSER_REQ) {
            val result = if (resultCode == RESULT_OK)
                WebChromeClient.FileChooserParams.parseResult(resultCode, data) else null
            pendingFileCallback?.onReceiveValue(result ?: arrayOf())
            pendingFileCallback = null
        }
    }

    private fun requestRuntimePermissions() {
        val perms = mutableListOf(android.Manifest.permission.CAMERA)
        if (Build.VERSION.SDK_INT < 29) perms.add(android.Manifest.permission.WRITE_EXTERNAL_STORAGE)
        val need = perms.filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }
        if (need.isNotEmpty()) ActivityCompat.requestPermissions(this, need.toTypedArray(), PERM_REQ)
    }

    // ---------------- 网页可调的原生桥 ----------------

    inner class WebBridge {
        /** 网页「打印」按钮调用：存相册 → 确认 → 开打印 App。imageUrl 传合成原图绝对地址。 */
        @JavascriptInterface
        fun printPhoto(imageUrl: String) {
            io.execute {
                val savedUri = try { downloadAndSaveToGallery(imageUrl) } catch (e: Exception) { null }
                runOnUiThread {
                    if (savedUri == null) {
                        toast("保存到相册失败，请重试")
                        notifyWeb(false)
                    } else {
                        // 确认已入相册后才打开打印 App（严格顺序）
                        notifyWeb(true)
                        toast("已保存到相册，正在打开打印")
                        openPrinterApp(savedUri)
                    }
                }
            }
        }
    }

    /** 下载图片字节 → 写入 MediaStore 相册 → 查回确认。成功返回 content Uri，失败返回 null。 */
    private fun downloadAndSaveToGallery(imageUrl: String): Uri? {
        val conn = (URL(imageUrl).openConnection() as HttpURLConnection).apply {
            connectTimeout = 15000
            readTimeout = 20000
            instanceFollowRedirects = true
        }
        conn.connect()
        if (conn.responseCode !in 200..299) return null
        val bytes = conn.inputStream.use { it.readBytes() }
        if (bytes.isEmpty()) return null

        val lower = imageUrl.lowercase()
        val isJpg = lower.endsWith(".jpg") || lower.endsWith(".jpeg")
        val mime = if (isJpg) "image/jpeg" else "image/png"
        val ext = if (isJpg) "jpg" else "png"

        val values = ContentValues().apply {
            put(MediaStore.Images.Media.DISPLAY_NAME, "leshine_tryon_${System.currentTimeMillis()}.$ext")
            put(MediaStore.Images.Media.MIME_TYPE, mime)
            if (Build.VERSION.SDK_INT >= 29) {
                put(MediaStore.Images.Media.RELATIVE_PATH, "Pictures/LeShineTryOn")
                put(MediaStore.Images.Media.IS_PENDING, 1)
            }
        }
        val resolver = contentResolver
        val uri = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values) ?: return null
        val ok = resolver.openOutputStream(uri)?.use { out ->
            out.write(bytes); out.flush(); true
        } ?: false
        if (!ok) { resolver.delete(uri, null, null); return null }
        if (Build.VERSION.SDK_INT >= 29) {
            values.clear()
            values.put(MediaStore.Images.Media.IS_PENDING, 0)
            resolver.update(uri, values, null, null)
        }
        // 查回确认真落相册（拿不到 _ID 视为失败）
        val confirmed = resolver.query(uri, arrayOf(MediaStore.Images.Media._ID), null, null, null)
            ?.use { it.moveToFirst() } ?: false
        return if (confirmed) uri else null
    }

    /** 优先按配置包名直启打印 App；无配置/未装则用系统「打开方式」让工作人员选。 */
    private fun openPrinterApp(savedUri: Uri) {
        val pkg = getString(R.string.printer_package).trim()
        if (pkg.isNotEmpty()) {
            val launch = packageManager.getLaunchIntentForPackage(pkg)
            if (launch != null) {
                launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                try { startActivity(launch); return } catch (e: Exception) { /* 落到兜底 */ }
            } else {
                toast("未找到打印 App（包名 $pkg），请在 strings.xml 配置正确包名")
            }
        }
        val view = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(savedUri, "image/*")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        try { startActivity(Intent.createChooser(view, "打开打印")) } catch (e: Exception) {
            toast("无法打开打印 App")
        }
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()

    /** 回调网页（可选）：网页可定义 window.__onPrintResult(ok) 做提示/日志。 */
    private fun notifyWeb(ok: Boolean) {
        webView.evaluateJavascript("window.__onPrintResult && window.__onPrintResult($ok)", null)
    }

    companion object {
        private const val FILE_CHOOSER_REQ = 1001
        private const val PERM_REQ = 100
    }
}
