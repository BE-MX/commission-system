package com.leshine.pdareporting

import android.app.Activity
import android.app.AlertDialog
import android.graphics.BitmapFactory
import android.os.Bundle
import android.view.KeyEvent
import android.view.WindowManager
import android.widget.EditText
import android.widget.ImageView
import android.widget.Toast
import org.json.JSONObject
import java.io.IOException
import java.util.UUID
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.Executors
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

class MainActivity : Activity() {
    private val executor = Executors.newFixedThreadPool(3)
    private val imageExecutor = ThreadPoolExecutor(
        2,
        2,
        0L,
        TimeUnit.MILLISECONDS,
        ArrayBlockingQueue(8),
        ThreadPoolExecutor.DiscardOldestPolicy(),
    )
    private val historyGeneration = AtomicInteger()
    private lateinit var api: ApiClient
    private lateinit var scannerInput: ScannerInput
    private lateinit var feedback: Feedback
    private val prefs by lazy { getSharedPreferences(PREFS, MODE_PRIVATE) }
    private val pendingStore by lazy { PendingSubmissionStore(prefs) }
    private var loginScreen: LoginScreen? = null
    private var reportingScreen: ReportingScreen? = null
    private var busy = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = Ui.green
        window.navigationBarColor = Ui.page
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        val defaultServer = getString(R.string.default_server_url)
        val storedServer = prefs.getString(KEY_SERVER, defaultServer).orEmpty()
        val safeServer = runCatching { ApiClient.normalizeBaseUrl(storedServer) }.getOrElse {
            prefs.edit().putString(KEY_SERVER, defaultServer).apply()
            defaultServer
        }
        api = ApiClient(safeServer)
        api.token = prefs.getString(KEY_TOKEN, "") ?: ""
        feedback = Feedback(this)
        scannerInput = ScannerInput(this, ::handleRawScan, ::handleMalformedBroadcast)

        if (api.token.isBlank()) showLogin() else verifySession()
    }

    override fun onStart() {
        super.onStart()
        scannerInput.start()
    }

    override fun onStop() {
        scannerInput.stop()
        super.onStop()
    }

    override fun onDestroy() {
        executor.shutdownNow()
        imageExecutor.shutdownNow()
        super.onDestroy()
    }

    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        // Dialog fields (batch quantity, manual fallback and settings) must receive
        // normal keyboard input. Scanner interception resumes as soon as focus leaves
        // an EditText; the primary reporting page itself has no editable field.
        if (currentFocus is EditText) return super.dispatchKeyEvent(event)
        return if (scannerInput.onKeyEvent(event)) true else super.dispatchKeyEvent(event)
    }

    private fun verifySession() {
        showLoadingPage("正在恢复登录…")
        executor.execute {
            try {
                val name = api.verify().ifBlank { prefs.getString(KEY_USER_NAME, "") ?: "" }
                ui { showReporting(name) }
            } catch (error: Exception) {
                ui {
                    if (error is ApiException && error.statusCode == 401) {
                        clearSession()
                        showLogin("登录已过期，请重新登录")
                    } else {
                        showConnectionRetry(readableError(error))
                    }
                }
            }
        }
    }

    private fun showConnectionRetry(message: String) {
        showLoadingPage("服务器暂时无法连接")
        AlertDialog.Builder(this)
            .setTitle("登录状态尚未验证")
            .setMessage("$message\n\n登录信息已保留，网络恢复后可直接重试。")
            .setCancelable(false)
            .setNegativeButton("重新登录 / 设置") { _, _ ->
                clearSession()
                showLogin("如服务器地址有变化，请先打开服务器设置")
            }
            .setPositiveButton("重试") { _, _ -> verifySession() }
            .show()
    }

    private fun showLoadingPage(message: String) {
        scannerInput.setEnabled(false)
        val root = Ui.vertical(this, 24).apply {
            gravity = android.view.Gravity.CENTER
            setBackgroundColor(Ui.page)
            addView(Ui.text(this@MainActivity, message, 17f, Ui.secondary, true))
        }
        setContentView(root)
    }

    private fun showLogin(message: String? = null) {
        scannerInput.setEnabled(false)
        reportingScreen = null
        loginScreen = LoginScreen(
            this,
            prefs.getString(KEY_USERNAME, "") ?: "",
            onLogin = ::login,
            onSettings = ::showSettings,
        ).also { screen ->
            setContentView(screen)
            message?.let(screen::showError)
        }
    }

    private fun login(username: String, password: String) {
        val screen = loginScreen ?: return
        val previousUser = prefs.getString(KEY_USERNAME, "").orEmpty()
        if (pendingStore.get() != null && previousUser.isNotBlank() && username != previousUser) {
            screen.showError("存在上一账号的待确认报工，请使用原账号登录并先处理")
            return
        }
        screen.setLoading(true)
        executor.execute {
            try {
                val session = api.login(username, password)
                api.token = session.token
                prefs.edit()
                    .putString(KEY_TOKEN, session.token)
                    .putString(KEY_USER_NAME, session.userName)
                    .putString(KEY_USERNAME, username)
                    .apply()
                ui { showReporting(session.userName) }
            } catch (error: Exception) {
                ui {
                    screen.setLoading(false)
                    screen.showError(readableError(error))
                }
            }
        }
    }

    private fun showReporting(userName: String) {
        loginScreen = null
        reportingScreen = ReportingScreen(
            this,
            userName,
            onManualScan = { handleRawScan(it, ScanSource.MANUAL) },
            onRevoke = ::revoke,
            onSettings = ::showSettings,
            onLogout = logout@{
                if (busy || pendingStore.get() != null) {
                    AlertDialog.Builder(this)
                        .setTitle("暂不能退出")
                        .setMessage("还有一笔扫码或提交正在处理。请确认结果后再退出，避免重复报工。")
                        .setPositiveButton("知道了", null)
                        .show()
                    return@logout
                }
                AlertDialog.Builder(this)
                    .setTitle("退出登录")
                    .setMessage("退出后需要重新输入方舟账号密码。")
                    .setNegativeButton("取消", null)
                    .setPositiveButton("退出") { _, _ -> clearSession(); showLogin() }
                    .show()
            },
        ).also(::setContentView)
        busy = false
        scannerInput.setEnabled(true)
        loadHistory()
        pendingStore.get()?.let {
            busy = true
            showRetryDialog("检测到上次提交结果尚未确认", it)
        }
    }

    private fun handleRawScan(raw: String, @Suppress("UNUSED_PARAMETER") source: ScanSource) {
        if (reportingScreen == null) return
        if (busy) {
            feedback.error()
            Toast.makeText(this, "上一笔还在处理中，请稍候", Toast.LENGTH_SHORT).show()
            return
        }
        pendingStore.get()?.let {
            busy = true
            showRetryDialog("上一笔提交结果仍待确认，请先处理", it)
            return
        }
        val payload = ScanPayloadParser.parse(raw)
        if (payload == null) {
            feedback.error()
            val message = if (raw.trim().startsWith("ARK-P:")) {
                "这是外贸流转卡，本 APP 只处理内贸报工"
            } else {
                "二维码无效，请扫描 ARK-D 或 ARK-DU 内贸二维码"
            }
            if (reportingScreen?.showUnitError(message) != true) reportingScreen?.showError(message)
            return
        }
        busy = true
        if (reportingScreen?.showUnitScanning() != true) reportingScreen?.showScanning(payload.raw)
        executor.execute {
            try {
                val scan = api.scan(payload)
                if (!scan.optBoolean("can_submit")) {
                    throw ApiException(422, scan.optString("block_message", "当前不能报工"))
                }
                ui { handleScanResult(payload, scan) }
            } catch (error: Exception) {
                ui {
                    handleFailure(
                        error,
                        written = false,
                        preferUnitDialog = reportingScreen?.isUnitDialogShowing() == true,
                    )
                }
            }
        }
    }

    private fun handleMalformedBroadcast(action: String) {
        if (reportingScreen == null || busy) return
        feedback.error()
        val message = "已收到 PDA 扫描广播，但 barcode_string 为空；请检查扫描设置中的广播数据标签\n$action"
        if (reportingScreen?.showUnitError(message) != true) reportingScreen?.showError(message)
    }

    private fun handleScanResult(payload: ScanPayload, scan: JSONObject) {
        if (UnitReportFlow.shouldAutoSubmit(scan.optString("report_mode"))) {
            reportingScreen?.showUnitReport(scan, ::loadImage)
            submit(scan, payload, 1, UUID.randomUUID().toString())
            return
        }
        reportingScreen?.showQuantityConfirmation(
            scan = scan,
            onConfirm = { qty -> submit(scan, payload, qty, UUID.randomUUID().toString()) },
            onCancel = { busy = false; reportingScreen?.showReady() },
            loadImage = ::loadImage,
        )
    }

    private fun submit(scan: JSONObject, payload: ScanPayload, qty: Int, requestId: String) {
        val unitMode = UnitReportFlow.shouldAutoSubmit(scan.optString("report_mode"))
        if (!pendingStore.persist(scan, payload, qty, requestId)) {
            handleFailure(
                IllegalStateException("无法保存待提交事务，请检查设备存储"),
                written = true,
                preferUnitDialog = unitMode,
            )
            return
        }
        val next = scan.optJSONObject("next_step") ?: JSONObject()
        if (unitMode) {
            reportingScreen?.showUnitSubmitting()
        } else {
            reportingScreen?.showSubmitting(scan.optString("product_name", "产品"), next.optString("process_name", "工序"))
        }
        executor.execute {
            try {
                val result = api.submit(scan, payload, qty, requestId)
                ui {
                    pendingStore.clear(requestId)
                    val codes = result.optJSONArray("unit_codes")?.let { array ->
                        (0 until array.length()).joinToString("、") { array.optString(it) }
                    }.orEmpty()
                    val replayed = result.optBoolean("replayed")
                    val message = buildString {
                        append(result.optString("process_name", "工序"))
                        append(" · ${result.optInt("reported_qty", qty)} 件")
                        if (codes.isNotBlank()) append(" · $codes")
                        if (replayed) append("（已去重）")
                    }
                    busy = false
                    feedback.success()
                    if (!unitMode || reportingScreen?.showUnitSuccess(message) != true) {
                        reportingScreen?.showSuccess(message)
                    }
                    loadHistory()
                }
            } catch (error: Exception) {
                ui {
                    if (error is ApiException && error.statusCode in 400..499) {
                        if (error.statusCode != 401) pendingStore.clear(requestId)
                        handleFailure(error, written = true, preferUnitDialog = unitMode)
                    } else {
                        // A transport, 5xx or response-decoding failure may happen after
                        // the server committed. Keep the transaction and retry its ID.
                        showRetryDialog(
                            error.message ?: "网络异常",
                            PendingSubmission(scan.toString(), payload.raw, qty, requestId),
                        )
                    }
                }
            }
        }
    }

    private fun showRetryDialog(message: String, pending: PendingSubmission) {
        val payload = ScanPayloadParser.parse(pending.rawPayload)
        val scan = runCatching { JSONObject(pending.scan) }.getOrNull()
        if (payload == null || scan == null) {
            pendingStore.clear(pending.requestId)
            handleFailure(IllegalStateException("待确认提交数据损坏，请重新扫码"), written = true)
            return
        }
        feedback.error()
        if (reportingScreen?.showUnitResultUnknown() != true) {
            reportingScreen?.showError("网络中断，提交结果未知")
        }
        AlertDialog.Builder(this)
            .setTitle("提交结果未知")
            .setMessage("$message\n\n请点“重试同一笔”。APP 会沿用同一个幂等请求号，后端不会重复累计数量。若暂时返回核对记录，下一次扫码仍会先提示处理这笔。")
            .setCancelable(false)
            .setNegativeButton("返回并核对记录") { _, _ ->
                reportingScreen?.dismissUnitReport()
                busy = false
                reportingScreen?.showError("请先核对今日记录；下一次扫码会再次提示处理待确认提交")
                loadHistory()
            }
            .setPositiveButton("重试同一笔") { _, _ -> submit(scan, payload, pending.qty, pending.requestId) }
            .show()
    }

    private fun revoke(record: HistoryRecord) {
        if (busy || pendingStore.get() != null) {
            Toast.makeText(this, "请先处理待确认提交，再撤销记录", Toast.LENGTH_SHORT).show()
            return
        }
        busy = true
        reportingScreen?.showSubmitting(record.productName, "撤销 ${record.processName}")
        executor.execute {
            try {
                api.revoke(record.logId)
                ui {
                    busy = false
                    feedback.success()
                    reportingScreen?.showSuccess("已撤销 ${record.processName} × ${record.reportQty} 件")
                    loadHistory()
                }
            } catch (error: Exception) {
                ui {
                    handleFailure(error, written = true)
                    loadHistory()
                }
            }
        }
    }

    private fun loadHistory() {
        val generation = historyGeneration.incrementAndGet()
        val tokenSnapshot = api.token
        executor.execute {
            try {
                val (records, stats) = api.history()
                ui {
                    if (generation == historyGeneration.get()) {
                        reportingScreen?.setHistory(records, stats.first, stats.second)
                    }
                }
            } catch (error: Exception) {
                if (error is ApiException && error.statusCode == 401) ui {
                    if (generation == historyGeneration.get() && tokenSnapshot == api.token) sessionExpired()
                }
            }
        }
    }

    private fun loadImage(path: String, view: ImageView) {
        imageExecutor.execute {
            try {
                val bytes = api.image(path)
                val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
                var sample = 1
                while (bounds.outWidth / sample > IMAGE_EDGE_PX * 2 || bounds.outHeight / sample > IMAGE_EDGE_PX * 2) {
                    sample *= 2
                }
                val bitmap = BitmapFactory.decodeByteArray(
                    bytes,
                    0,
                    bytes.size,
                    BitmapFactory.Options().apply { inSampleSize = sample },
                ) ?: return@execute
                ui { reportingScreen?.displayImage(bitmap, view) }
            } catch (_: Exception) {
                // 图片加载失败不阻塞报工，文本要求和核心操作仍可继续。
            }
        }
    }

    private fun handleFailure(error: Exception, written: Boolean, preferUnitDialog: Boolean = false) {
        if (error is ApiException && error.statusCode == 401) {
            sessionExpired()
            return
        }
        busy = false
        feedback.error()
        val prefix = if (written) "操作失败：" else "扫码失败："
        val message = prefix + readableError(error)
        if (!preferUnitDialog || reportingScreen?.showUnitError(message) != true) {
            reportingScreen?.showError(message)
        }
    }

    private fun sessionExpired() {
        clearSession()
        showLogin("登录已过期，请重新登录")
    }

    private fun showSettings() {
        if (busy) {
            Toast.makeText(this, "当前操作处理完成后才能修改设置", Toast.LENGTH_SHORT).show()
            return
        }
        scannerInput.setEnabled(false)
        val wrapper = Ui.vertical(this, 20)
        val server = EditText(this).apply {
            setText(api.baseUrl)
            hint = "https://leshine.work"
            isSingleLine = true
        }
        wrapper.addView(Ui.text(this, "服务器地址", 13f, Ui.secondary, true))
        wrapper.addView(server, Ui.margin(top = 6, context = this))
        wrapper.addView(
            Ui.text(
                this,
                "实体键广播配置：Action = ${ScanBroadcastContract.VENDOR_ACTION}\n数据标签 = ${ScanBroadcastContract.VENDOR_EXTRA}",
                12f,
                Ui.muted,
            ),
            Ui.margin(top = 12, context = this),
        )

        val dialog = AlertDialog.Builder(this)
            .setTitle("PDA 设置")
            .setView(wrapper)
            .setNegativeButton("取消", null)
            .setPositiveButton("保存", null)
            .create()
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                try {
                    val normalized = ApiClient.normalizeBaseUrl(server.text.toString())
                    val serverChanged = normalized != api.baseUrl
                    if (serverChanged && pendingStore.get() != null) {
                        server.error = "存在待确认报工，处理完成前不能切换服务器"
                        return@setOnClickListener
                    }
                    prefs.edit().putString(KEY_SERVER, normalized).apply()
                    api.updateBaseUrl(normalized)
                    dialog.dismiss()
                    if (serverChanged) {
                        clearSession()
                        showLogin("服务器已切换，请重新登录")
                    }
                } catch (error: IllegalArgumentException) {
                    server.error = error.message
                }
            }
        }
        dialog.setOnDismissListener { scannerInput.setEnabled(reportingScreen != null) }
        dialog.show()
    }

    private fun clearSession() {
        busy = false
        api.token = ""
        prefs.edit().remove(KEY_TOKEN).remove(KEY_USER_NAME).apply()
    }

    private fun readableError(error: Exception): String = when (error) {
        is ApiException -> error.message
        is IOException -> "网络连接失败，请检查 Wi-Fi 和服务器地址"
        else -> error.message ?: "未知错误"
    }

    private fun ui(action: () -> Unit) {
        if (!isFinishing && !isDestroyed) runOnUiThread(action)
    }

    companion object {
        private const val PREFS = "pda_reporting"
        private const val KEY_SERVER = "server_url"
        private const val KEY_TOKEN = "access_token"
        private const val KEY_USER_NAME = "user_name"
        private const val KEY_USERNAME = "username"
        private const val IMAGE_EDGE_PX = 320
    }
}
