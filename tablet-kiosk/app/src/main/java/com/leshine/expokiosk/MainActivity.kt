package com.leshine.expokiosk

import android.annotation.SuppressLint
import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.net.http.SslCertificate
import android.net.http.SslError
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import android.util.Log
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.PermissionRequest
import android.webkit.SslErrorHandler
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors
import kotlin.math.abs

/**
 * 莱莎展会 AI 试戴 — 平板 kiosk 壳。
 *
 * 职责：全屏沉浸加载 leshine.work/expo/kiosk；给网页授摄像头权限；提供原生「一键打印」桥
 * （下载合成原图 → 写进系统相册 → 查回确认存好 → 才启动打印 App，严格此顺序）；
 * 设备所有者时开 Lock Task 真锁定（白名单含自身 + 打印 App）。
 */
class MainActivity : ComponentActivity() {

    private lateinit var webView: WebView
    private lateinit var errorView: View
    private lateinit var errorDetail: TextView
    private val io = Executors.newSingleThreadExecutor()
    private var pendingFileCallback: ValueCallback<Array<Uri>>? = null

    /** 本次加载是否失败——onPageFinished 靠它决定收不收兜底页 */
    private var loadFailed = false
    private var configOpen = false
    private var retryDelayMs = RETRY_MIN_MS

    // 三指长按呼出地址设置：只观察不消费触摸，避免挡住网页交互
    private val ui = Handler(Looper.getMainLooper())
    private val openConfigTask = Runnable { openConfigDialog() }
    private val autoRetryTask = Runnable { if (loadFailed) reload() }
    private var hotspotArmed = false
    private var hotspotDownX = 0f
    private var hotspotDownY = 0f

    /** ACTION_IMAGE_CAPTURE 的落图 Uri：相机成功时 data 为 null，全靠它把照片还给网页 */
    private var cameraOutputUri: Uri? = null
    private var isResumed = false
    private val fileChooserGuard = Runnable {
        // 选择器没起来（典型：Lock Task 拦了非白名单 App，系统静默拒绝、不回 result）——
        // 不主动归还 callback 的话，Chromium 会一直以为选择器开着，之后所有 file input 全哑
        if (pendingFileCallback != null && isResumed) {
            releasePendingFileCallback()
            toast("打不开相机/相册，请找工作人员")
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) // 屏幕常亮
        requestRuntimePermissions()

        webView = WebView(this)
        errorView = buildErrorView().apply { visibility = View.GONE }
        setContentView(FrameLayout(this).apply {
            addView(webView, FrameLayout.LayoutParams(MATCH, MATCH))
            addView(errorView, FrameLayout.LayoutParams(MATCH, MATCH))
        })

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
            override fun onPageStarted(view: WebView?, url: String?, favicon: android.graphics.Bitmap?) {
                loadFailed = false
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                Log.i(TAG, "onPageFinished loadFailed=$loadFailed url=$url")
                // 保险：标记桌面模式，杜绝任何移动端重定向（/expo 已豁免，这里再兜一层）
                view?.evaluateJavascript("try{sessionStorage.setItem('ark_desktop_mode','1')}catch(e){}", null)
                if (!loadFailed) hideError() // 顺带把退避计数清零
                // 首帧保险：个别 ROM 上 WebView 渲染完成却不触发绘制（2026-07-24 荣耀平板实测过一次，
                // DOM 正常但整屏纯黑），主动要一次重绘，代价可忽略
                view?.postDelayed({ view.invalidate() }, 120)
            }

            /**
             * IP 直连申请不到 CA 证书，服务器挂的是自签证书。这里**只认指纹**：与 strings.xml
             * 里 pin 的那张一致才放行，其余任何 SSL 错误一律拒绝——不是无脑 proceed()，
             * 展馆公共 WiFi 下的中间人照样挡得住。
             * 换成正规 CA 证书后（备案下来上域名）本回调根本不会触发，代码不用改。
             */
            override fun onReceivedSslError(
                view: WebView?,
                handler: SslErrorHandler?,
                error: SslError?,
            ) {
                val der = error?.certificate
                    ?.let { SslCertificate.saveState(it).getByteArray("x509-certificate") }
                if (PinnedTls.matches(this@MainActivity, der)) {
                    Log.i(TAG, "ssl pinned ok ${error?.url}")
                    handler?.proceed()
                } else {
                    Log.w(TAG, "ssl pin MISMATCH ${error?.url} primary=${error?.primaryError}")
                    handler?.cancel()
                    showError(error?.url, "证书校验未通过")
                }
            }

            /** 主框架加载不出来（IP 写错/服务器没起/断网）→ 展示带「改地址」的兜底页，不留白屏 */
            override fun onReceivedError(
                view: WebView?,
                request: WebResourceRequest?,
                error: WebResourceError?,
            ) {
                if (request?.isForMainFrame == true) {
                    Log.w(TAG, "onReceivedError ${request.url} ${error?.description}")
                    showError(request.url?.toString(), error?.description?.toString())
                }
            }

            override fun onReceivedHttpError(
                view: WebView?,
                request: WebResourceRequest?,
                errorResponse: WebResourceResponse?,
            ) {
                if (request?.isForMainFrame == true) {
                    showError(request.url?.toString(), "HTTP ${errorResponse?.statusCode}")
                }
            }
        }

        webView.webChromeClient = object : WebChromeClient() {
            override fun onPermissionRequest(request: PermissionRequest) {
                runOnUiThread { request.grant(request.resources) } // 摄像头/麦克风授给网页
            }
            /**
             * http 入口下网页相机被浏览器禁用，这里是**唯一**的拍照路径，必须把系统相机塞进选择器：
             * FileChooserParams.createIntent() 只给 ACTION_GET_CONTENT，完全忽略 <input capture>，
             * 直接用它的话客户只会看到一个空相册的文件列表，流程当场断掉。
             */
            override fun onShowFileChooser(
                view: WebView?,
                filePathCallback: ValueCallback<Array<Uri>>?,
                params: FileChooserParams?,
            ): Boolean {
                releasePendingFileCallback() // 上一次没归还的先还掉，否则 Chromium 认为选择器还开着
                pendingFileCallback = filePathCallback
                val pick = params?.createIntent() ?: run { pendingFileCallback = null; return false }
                cameraOutputUri = createPendingImageUri()
                val chooser = Intent.createChooser(pick, getString(R.string.chooser_title)).apply {
                    cameraOutputUri?.let {
                        putExtra(
                            Intent.EXTRA_INITIAL_INTENTS,
                            arrayOf(Intent(MediaStore.ACTION_IMAGE_CAPTURE).putExtra(MediaStore.EXTRA_OUTPUT, it)),
                        )
                    }
                }
                return try {
                    startActivityForResult(chooser, FILE_CHOOSER_REQ)
                    armFileChooserGuard()
                    true
                } catch (e: Exception) {
                    discardCameraOutput()
                    pendingFileCallback = null
                    false
                }
            }
        }

        webView.addJavascriptInterface(WebBridge(), "Android")
        Log.i(TAG, "loadUrl ${KioskUrl.get(this)}")
        webView.loadUrl(KioskUrl.get(this))
    }

    // ---------------- 文件选择 / 系统相机 ----------------

    /** 先在相册占个坑给 ACTION_IMAGE_CAPTURE 写入；拿不到 Uri 就退化为只有相册可选 */
    private fun createPendingImageUri(): Uri? = try {
        val values = ContentValues().apply {
            put(MediaStore.Images.Media.DISPLAY_NAME, "leshine_shot_${System.currentTimeMillis()}.jpg")
            put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg")
            if (Build.VERSION.SDK_INT >= 29) {
                put(MediaStore.Images.Media.RELATIVE_PATH, "Pictures/LeShineTryOn")
            }
        }
        contentResolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
    } catch (e: Exception) {
        null
    }

    /** 客户走了相册分支或直接取消 → 把占位的空记录删掉，别在相册留一堆 0 字节图 */
    private fun discardCameraOutput() {
        cameraOutputUri?.let { runCatching { contentResolver.delete(it, null, null) } }
        cameraOutputUri = null
    }

    private fun releasePendingFileCallback() {
        pendingFileCallback?.onReceiveValue(arrayOf())
        pendingFileCallback = null
        ui.removeCallbacks(fileChooserGuard)
    }

    private fun armFileChooserGuard() {
        ui.removeCallbacks(fileChooserGuard)
        ui.postDelayed(fileChooserGuard, CHOOSER_GUARD_MS)
    }

    // ---------------- 现场地址配置（三指长按 2.5 秒） ----------------

    /**
     * 只观察触摸、不消费：**三根手指同时按住 2.5 秒**弹地址设置框，抬指或大幅移动即取消。
     *
     * 早先用的是「右上角 72dp 长按」，实测与 kiosk 自己的「⌂ 主页」「✕ 关闭」按钮完全重叠
     * （xk-head 高 52px、右边距 22px），客户长按主页键就能拿到一个自由输入 URL 的框——
     * 换成与页面布局无关的三指手势，客户不可能误触，工作人员一说就会。
     */
    override fun dispatchTouchEvent(ev: MotionEvent): Boolean {
        when (ev.actionMasked) {
            MotionEvent.ACTION_POINTER_DOWN -> {
                if (ev.pointerCount >= CONFIG_FINGERS) {
                    hotspotArmed = true
                    hotspotDownX = centroidX(ev)
                    hotspotDownY = centroidY(ev)
                    ui.postDelayed(openConfigTask, HOTSPOT_HOLD_MS)
                }
            }
            MotionEvent.ACTION_MOVE -> {
                // 手抖给足余量，但三指滑动（如系统截屏手势）要判为取消
                val slop = 64 * resources.displayMetrics.density
                if (hotspotArmed &&
                    (abs(centroidX(ev) - hotspotDownX) > slop || abs(centroidY(ev) - hotspotDownY) > slop)
                ) cancelHotspot()
            }
            // 任何一指抬起就作废，保证「三指同时按住」这一条严格成立
            MotionEvent.ACTION_POINTER_UP,
            MotionEvent.ACTION_UP,
            MotionEvent.ACTION_CANCEL,
            -> cancelHotspot()
        }
        return super.dispatchTouchEvent(ev)
    }

    private fun centroidX(ev: MotionEvent): Float {
        var sum = 0f
        for (i in 0 until ev.pointerCount) sum += ev.getX(i)
        return sum / ev.pointerCount
    }

    private fun centroidY(ev: MotionEvent): Float {
        var sum = 0f
        for (i in 0 until ev.pointerCount) sum += ev.getY(i)
        return sum / ev.pointerCount
    }

    private fun cancelHotspot() {
        if (!hotspotArmed) return
        hotspotArmed = false
        ui.removeCallbacks(openConfigTask)
    }

    private fun openConfigDialog() {
        if (configOpen) return
        configOpen = true
        KioskUrl.showDialog(
            activity = this,
            onDismiss = { configOpen = false },
            onApply = { url ->
                hideError()
                webView.loadUrl(url)
            },
        )
    }

    // ---------------- 加载失败兜底页 ----------------

    /**
     * 注意：**这里绝不能碰 webView.onPause()/onResume()**。
     * 1.4/1.5 版为「盖住就别让底下跑」在 showError 里 onPause、hideError 里 onResume，而 hideError
     * 是在 onPageFinished 里调的——等于在页面回调里驱动本该跟随 Activity 生命周期的开关。
     * 荣耀平板（com.hihonor.webview）上会让合成器丢掉首帧：DOM 渲染完好（CDP 截图正常）、
     * Android 侧却一直不绘制，表现为**整屏纯黑**，直到任意外部事件触发一次重绘才突然出现。
     * 2026-07-24 用 CDP 实测确诊。省那点 CPU（展位平板插着电）远不值这个风险，errorView 遮盖已足够。
     */
    private fun showError(failedUrl: String?, reason: String?) {
        loadFailed = true
        ui.removeCallbacks(autoRetryTask)
        errorDetail.text = "${failedUrl ?: KioskUrl.get(this)}\n${reason.orEmpty()}"
        errorView.visibility = View.VISIBLE
        // 展位无人值守：展馆 WiFi 抖一下不能就此挂着等人来点「重试」，退避自动重连
        ui.postDelayed(autoRetryTask, retryDelayMs)
        retryDelayMs = (retryDelayMs * 2).coerceAtMost(RETRY_MAX_MS)
    }

    private fun hideError() {
        ui.removeCallbacks(autoRetryTask)
        retryDelayMs = RETRY_MIN_MS
        loadFailed = false
        errorView.visibility = View.GONE
    }

    private fun reload() {
        hideError()
        webView.loadUrl(KioskUrl.get(this))
    }

    private fun buildErrorView(): View {
        val d = resources.displayMetrics.density
        fun dp(v: Int) = (v * d).toInt()

        val title = TextView(this).apply {
            setText(R.string.error_title)
            setTextColor(0xFFFFFFFF.toInt())
            textSize = 22f
            gravity = Gravity.CENTER
        }
        errorDetail = TextView(this).apply {
            setTextColor(0xFF9AA0A6.toInt())
            textSize = 14f
            gravity = Gravity.CENTER
        }
        val retry = Button(this).apply {
            setText(R.string.error_retry)
            setOnClickListener { reload() }
        }
        val config = Button(this).apply {
            setText(R.string.error_config)
            setOnClickListener { openConfigDialog() }
        }
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
            addView(retry, LinearLayout.LayoutParams(dp(150), dp(56)).apply { rightMargin = dp(16) })
            addView(config, LinearLayout.LayoutParams(dp(150), dp(56)))
        }
        return LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setBackgroundColor(0xFF000000.toInt())
            setPadding(dp(32), dp(32), dp(32), dp(32))
            isClickable = true // 吃掉触摸，别穿到底下的 WebView
            addView(title, ViewGroup.LayoutParams(MATCH, WRAP))
            addView(errorDetail, LinearLayout.LayoutParams(MATCH, WRAP).apply {
                topMargin = dp(12); bottomMargin = dp(28)
            })
            addView(row, LinearLayout.LayoutParams(WRAP, WRAP))
        }
    }

    override fun onResume() {
        super.onResume()
        isResumed = true
        hideSystemBars()
        setupLockTask()
    }

    override fun onPause() {
        isResumed = false
        super.onPause()
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
                dpm.setLockTaskPackages(admin, lockTaskWhitelist())
                startLockTask()
            }
        } catch (e: Exception) { /* 忽略，仍是全屏沉浸 */ }
    }

    /**
     * Lock Task 白名单：自身 + 打印 App + **系统相机 + 文档选择器**。
     * 后两个漏掉的话，锁定状态下 startActivityForResult 会被系统静默拒绝（不抛异常也不回 result），
     * 客户点「拍照/选图」毫无反应，且 file input 从此彻底哑掉——展位上等于试戴流程全断。
     */
    private fun lockTaskWhitelist(): Array<String> {
        val pkgs = linkedSetOf(packageName)
        getString(R.string.printer_package).trim().takeIf { it.isNotEmpty() }?.let { pkgs.add(it) }
        runCatching {
            packageManager.resolveActivity(Intent(MediaStore.ACTION_IMAGE_CAPTURE), 0)
                ?.activityInfo?.packageName?.let { pkgs.add(it) }
        }
        runCatching {
            val getContent = Intent(Intent.ACTION_GET_CONTENT).apply {
                type = "image/*"
                addCategory(Intent.CATEGORY_OPENABLE)
            }
            packageManager.resolveActivity(getContent, 0)?.activityInfo?.packageName?.let { pkgs.add(it) }
        }
        return pkgs.toTypedArray()
    }

    /** 展位不允许返回退出 kiosk：吞掉返回键。 */
    @Suppress("OVERRIDE_DEPRECATION")
    override fun onBackPressed() { /* no-op */ }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != FILE_CHOOSER_REQ) return
        ui.removeCallbacks(fileChooserGuard)

        val picked = if (resultCode == RESULT_OK) {
            WebChromeClient.FileChooserParams.parseResult(resultCode, data)
        } else null
        // 相机分支：ACTION_IMAGE_CAPTURE 把图写进了 EXTRA_OUTPUT，回来的 data 通常是 null，
        // parseResult 拿不到任何东西——此时必须回退到我们自己占的那个 Uri
        val usedCamera = picked.isNullOrEmpty() && resultCode == RESULT_OK && cameraOutputUri != null
        val result: Array<Uri> = when {
            !picked.isNullOrEmpty() -> picked
            usedCamera -> arrayOf(cameraOutputUri!!)
            else -> arrayOf()
        }
        if (usedCamera) cameraOutputUri = null else discardCameraOutput()

        pendingFileCallback?.onReceiveValue(result)
        pendingFileCallback = null
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
            PinnedTls.apply(this@MainActivity, this) // https 自签证书下不装这个会直接握手失败
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

    override fun onDestroy() {
        ui.removeCallbacksAndMessages(null)
        super.onDestroy()
    }

    companion object {
        private const val TAG = "ExpoKiosk"
        private const val FILE_CHOOSER_REQ = 1001
        private const val PERM_REQ = 100
        private const val CONFIG_FINGERS = 3
        private const val HOTSPOT_HOLD_MS = 2500L
        private const val CHOOSER_GUARD_MS = 2500L
        private const val RETRY_MIN_MS = 5000L
        private const val RETRY_MAX_MS = 60000L
        private val MATCH = ViewGroup.LayoutParams.MATCH_PARENT
        private val WRAP = ViewGroup.LayoutParams.WRAP_CONTENT
    }
}
