package com.leshine.expokiosk

import android.annotation.SuppressLint
import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.net.Uri
import android.net.http.SslCertificate
import android.net.http.SslError
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.webkit.CookieManager
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
    private lateinit var errorView: View
    private lateinit var errorDetail: TextView
    private lateinit var updateOverlay: UpdateOverlay
    private val io = Executors.newSingleThreadExecutor()
    private var updateReceiverRegistered = false
    private var startupUpdateRequested = false
    private var startupUpdateReleased = false
    private var activityDestroyed = false
    private var updateFailureNoticeShown = false

    private val updateStateObserver: (UpdateState) -> Unit = { state ->
        ui.post {
            if (!activityDestroyed && !startupUpdateReleased) renderUpdateState(state)
        }
    }
    private val updateAwaitingReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action == UpdateInstallReceiver.ACTION_UPDATE_AWAITING_USER) {
                StartupUpdateProcess.coordinator.publish(UpdateState.AwaitingUserAction)
            }
        }
    }

    /** 本次加载是否失败——onPageFinished 靠它决定收不收兜底页 */
    private var loadFailed = false
    private var retryDelayMs = RETRY_MIN_MS

    private val ui = Handler(Looper.getMainLooper())
    private val autoRetryTask = Runnable { if (loadFailed) reload() }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) // 屏幕常亮
        requestRuntimePermissions()

        webView = WebView(this)
        errorView = buildErrorView().apply { visibility = View.GONE }
        updateOverlay = UpdateOverlay(this)
        setContentView(FrameLayout(this).apply {
            addView(webView, FrameLayout.LayoutParams(MATCH, MATCH))
            addView(errorView, FrameLayout.LayoutParams(MATCH, MATCH))
            addView(updateOverlay, FrameLayout.LayoutParams(MATCH, MATCH))
        })
        registerUpdateReceiver()

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
            override fun shouldOverrideUrlLoading(
                view: WebView?,
                request: WebResourceRequest?,
            ): Boolean {
                // kiosk 不使用 iframe/object；拒绝所有子框架导航，避免把同源后台嵌进共享屏。
                // 普通脚本、图片、XHR 资源不会走 shouldOverrideUrlLoading，不受影响。
                if (KioskNavigationPolicy.shouldBlockSubframe(request?.isForMainFrame)) return true
                return enforceKioskNavigation(view, request?.url?.toString())
            }

            override fun onPageStarted(view: WebView?, url: String?, favicon: android.graphics.Bitmap?) {
                // shouldOverrideUrlLoading 不覆盖所有 ROM/应用主动 loadUrl 的差异；页面开始加载时再验一次，
                // 防止任何漏网主框架导航短暂显示方舟后台。
                if (enforceKioskNavigation(view, url)) return
                loadFailed = false
            }

            override fun doUpdateVisitedHistory(view: WebView?, url: String?, isReload: Boolean) {
                // Vue 的 history.pushState 不一定触发网络导航回调；历史记录一变化仍由原生层复核，
                // 因而网页路由守卫失效时也不能在 APP 内切到 MainLayout。
                enforceKioskNavigation(view, url)
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

            /** 自签证书只按固定 SHA-256 指纹放行；其余 SSL 错误全部拒绝。 */
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

            /** 主框架加载失败时显示固定来源的重试页，不提供任何切源入口。 */
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
                runOnUiThread {
                    if (KioskWebPermissionPolicy.allow(
                            fixedOrigin = KioskUrl.origin(this@MainActivity),
                            requestOrigin = request.origin?.toString(),
                            currentMainFrameUrl = webView.url,
                            resources = request.resources,
                        )
                    ) {
                        request.grant(arrayOf(PermissionRequest.RESOURCE_VIDEO_CAPTURE))
                    } else {
                        request.deny()
                    }
                }
            }

            override fun onShowFileChooser(
                view: WebView?,
                filePathCallback: ValueCallback<Array<Uri>>?,
                params: FileChooserParams?,
            ): Boolean {
                filePathCallback?.onReceiveValue(emptyArray())
                toast(getString(R.string.file_selection_disabled))
                return true
            }
        }

        webView.addJavascriptInterface(
            KioskPrintBridge(
                context = this,
                executor = io,
                runOnUi = { action -> runOnUiThread(action) },
                notifyWeb = ::notifyWeb,
            ),
            "Android",
        )
        Log.i(TAG, "loadUrl ${KioskUrl.get(this)}")
        webView.loadUrl(KioskUrl.get(this))

        if (consumeInstallFailure(intent)) StartupUpdateProcess.coordinator.failInstall()
        startStartupUpdateOnce()
    }

    @Suppress("DEPRECATION")
    private fun startStartupUpdateOnce() {
        if (startupUpdateRequested || startupUpdateReleased) return
        startupUpdateRequested = true

        val latest = StartupUpdateProcess.coordinator.attach(updateStateObserver)
        renderUpdateState(latest ?: UpdateState.Checking)
        val appContext = applicationContext
        val keepUpdateAttempt = startUpdateAfterInstallRecovery(
            activeSession = activeInstallSession(appContext),
            coordinator = StartupUpdateProcess.coordinator,
            execute = { task -> io.execute(task) },
            cleanupSessions = {
                val packageInstaller = appContext.packageManager.packageInstaller
                cleanupOwnedInstallSessions(
                    sessions = {
                        packageInstaller.mySessions.map {
                            InstallSessionRecord(it.sessionId, it.appPackageName)
                        }
                    },
                    ownPackage = appContext.packageName,
                    abandon = packageInstaller::abandonSession,
                )
            },
            createRunner = {
                val packageInfo = appContext.packageManager.getPackageInfo(
                    appContext.packageName,
                    0,
                )
                val currentVersionCode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                    packageInfo.longVersionCode
                } else {
                    packageInfo.versionCode.toLong()
                }
                val engine = UpdateEngine(
                    currentVersionCode = currentVersionCode,
                    source = HttpUpdateSource(appContext, KioskUrl.origin(appContext)),
                    verifier = AndroidApkVerifier(appContext),
                    installer = AndroidUpdateInstaller(appContext),
                    downloadTarget = appContext.cacheDir.resolve(UPDATE_APK_NAME),
                    diagnostics = AndroidUpdateDiagnostics(),
                )
                StartupUpdateRun(engine::run)
            },
            diagnostics = { exception ->
                Log.w(TAG, "Install session recovery failed type=${exception.javaClass.simpleName}")
            },
        )
        if (!keepUpdateAttempt) releaseAfterInstallFailure()
    }

    private fun renderUpdateState(state: UpdateState) {
        val presentation = UpdatePresentation.from(state)
        if (presentation.blocksKiosk) {
            updateOverlay.render(presentation)
        } else {
            updateOverlay.hide()
            if (presentation.message == UpdateMessage.FAILURE && !updateFailureNoticeShown) {
                updateFailureNoticeShown = true
                Toast.makeText(this, R.string.update_failed_safe, Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun releaseAfterInstallFailure() {
        StartupUpdateProcess.coordinator.failInstall()
        startupUpdateReleased = true
        StartupUpdateProcess.coordinator.detach(updateStateObserver)
        updateOverlay.hide()
        if (!updateFailureNoticeShown) {
            updateFailureNoticeShown = true
            Toast.makeText(this, R.string.update_failed_safe, Toast.LENGTH_SHORT).show()
        }
    }

    private fun registerUpdateReceiver() {
        if (updateReceiverRegistered) return
        val filter = IntentFilter(UpdateInstallReceiver.ACTION_UPDATE_AWAITING_USER)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(updateAwaitingReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            ContextCompat.registerReceiver(
                this,
                updateAwaitingReceiver,
                filter,
                ContextCompat.RECEIVER_NOT_EXPORTED,
            )
        }
        updateReceiverRegistered = true
    }

    private fun unregisterUpdateReceiver() {
        if (!updateReceiverRegistered) return
        unregisterReceiver(updateAwaitingReceiver)
        updateReceiverRegistered = false
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (consumeInstallFailure(intent)) {
            releaseAfterInstallFailure()
        }
    }

    private fun consumeInstallFailure(intent: Intent?): Boolean {
        if (intent?.action != UpdateInstallReceiver.ACTION_UPDATE_FAILED) return false
        val token = intent.getStringExtra(UpdateInstallReceiver.EXTRA_FAILURE_TOKEN)
        intent.removeExtra(UpdateInstallReceiver.EXTRA_FAILURE_TOKEN)
        return InstallFailureSignal.consume(applicationContext, token)
    }

    /**
     * APP 原生层的最终边界：只放行同源 kiosk，以及明确回到 kiosk 的登录页。
     * Vue 路由与请求拦截器负责正常体验；这里负责即使网页层失效也绝不展示方舟后台。
     */
    private fun enforceKioskNavigation(view: WebView?, requestedUrl: String?): Boolean =
        when (val decision = KioskNavigationPolicy.decide(KioskUrl.get(this), requestedUrl)) {
            NavigationDecision.Allow -> false
            is NavigationDecision.Redirect -> {
                Log.w(TAG, "blocked non-kiosk navigation $requestedUrl -> ${decision.url}")
                view?.stopLoading()
                if (view?.url != decision.url) view?.loadUrl(decision.url)
                true
            }
        }

    // ---------------- 加载失败兜底页 ----------------

    /** Do not drive WebView pause/resume from page callbacks; Honor WebView can lose its first frame. */
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
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
            addView(retry, LinearLayout.LayoutParams(dp(150), dp(56)))
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

    /** Device owners use true Lock Task; ordinary installs stay immersive without screen pinning. */
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

    private fun lockTaskWhitelist(): Array<String> = KioskExternalPackagePolicy
        .lockTaskPackages(packageName, getString(R.string.printer_package))
        .toTypedArray()

    /** 展位不允许返回退出 kiosk：吞掉返回键。 */
    @Suppress("OVERRIDE_DEPRECATION")
    override fun onBackPressed() { /* no-op */ }

    private fun requestRuntimePermissions() {
        val perms = mutableListOf(android.Manifest.permission.CAMERA)
        if (Build.VERSION.SDK_INT < 29) perms.add(android.Manifest.permission.WRITE_EXTERNAL_STORAGE)
        val need = perms.filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }
        if (need.isNotEmpty()) ActivityCompat.requestPermissions(this, need.toTypedArray(), PERM_REQ)
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()

    /** 回调网页（可选）：网页可定义 window.__onPrintResult(ok) 做提示/日志。 */
    private fun notifyWeb(ok: Boolean) {
        webView.evaluateJavascript("window.__onPrintResult && window.__onPrintResult($ok)", null)
    }

    override fun onDestroy() {
        activityDestroyed = true
        StartupUpdateProcess.coordinator.detach(updateStateObserver)
        unregisterUpdateReceiver()
        ui.removeCallbacksAndMessages(null)
        super.onDestroy()
    }

    companion object {
        private const val TAG = "ExpoKiosk"
        private const val PERM_REQ = 100
        private const val RETRY_MIN_MS = 5000L
        private const val RETRY_MAX_MS = 60000L
        private const val UPDATE_APK_NAME = "kiosk-update.part.apk"
        private val MATCH = ViewGroup.LayoutParams.MATCH_PARENT
        private val WRAP = ViewGroup.LayoutParams.WRAP_CONTENT
    }
}
