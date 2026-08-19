package com.leshine.pdareporting

import android.app.Activity
import android.app.AlertDialog
import android.os.Bundle
import android.view.KeyEvent
import android.view.WindowManager
import android.widget.EditText
import android.widget.ImageView
import android.widget.Switch
import android.widget.Toast
import org.json.JSONObject
import java.io.IOException
import java.util.UUID
import java.util.concurrent.Executors

class MainActivity : Activity() {
    private val executor = Executors.newFixedThreadPool(3)
    private lateinit var api: ApiClient
    private lateinit var scannerInput: ScannerInput
    private lateinit var feedback: Feedback
    private val prefs by lazy { getSharedPreferences(PREFS, MODE_PRIVATE) }
    private var loginScreen: LoginScreen? = null
    private var reportingScreen: ReportingScreen? = null
    private var busy = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = Ui.green
        window.navigationBarColor = Ui.page
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        api = ApiClient(prefs.getString(KEY_SERVER, getString(R.string.default_server_url))!!)
        api.token = prefs.getString(KEY_TOKEN, "") ?: ""
        feedback = Feedback(this)
        scannerInput = ScannerInput(this, ::handleRawScan)

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
                    clearSession()
                    showLogin(if (error is ApiException && error.statusCode == 401) "登录已过期，请重新登录" else "无法连接服务器，请重新登录")
                }
            }
        }
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
            onManualScan = ::handleRawScan,
            onRevoke = ::revoke,
            onSettings = ::showSettings,
            onLogout = {
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
    }

    private fun handleRawScan(raw: String) {
        if (reportingScreen == null) return
        if (busy) {
            feedback.error()
            Toast.makeText(this, "上一笔还在处理中，请稍候", Toast.LENGTH_SHORT).show()
            return
        }
        val payload = ScanPayloadParser.parse(raw)
        if (payload == null) {
            feedback.error()
            reportingScreen?.showError(
                if (raw.trim().startsWith("ARK-P:")) "这是外贸流转卡，本 APP 只处理内贸报工" else "二维码无效，请扫描 ARK-D 或 ARK-DU 内贸二维码",
            )
            return
        }
        busy = true
        reportingScreen?.showScanning(payload.raw)
        executor.execute {
            try {
                val scan = api.scan(payload)
                if (!scan.optBoolean("can_submit")) {
                    throw ApiException(422, scan.optString("block_message", "当前不能报工"))
                }
                ui { handleScanResult(payload, scan) }
            } catch (error: Exception) {
                ui { handleFailure(error, written = false) }
            }
        }
    }

    private fun handleScanResult(payload: ScanPayload, scan: JSONObject) {
        val isUnit = scan.optString("report_mode") == "unit"
        if (isUnit && prefs.getBoolean(KEY_AUTO_UNIT, true)) {
            val requestId = UUID.randomUUID().toString()
            submit(scan, payload, 1, requestId)
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
        val next = scan.optJSONObject("next_step") ?: JSONObject()
        reportingScreen?.showSubmitting(scan.optString("product_name", "产品"), next.optString("process_name", "工序"))
        executor.execute {
            try {
                val result = api.submit(scan, payload, qty, requestId)
                ui {
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
                    reportingScreen?.showSuccess(message)
                    loadHistory()
                }
            } catch (error: Exception) {
                ui {
                    if (error is IOException || (error is ApiException && error.statusCode >= 500)) {
                        showRetryDialog(error.message ?: "网络异常", scan, payload, qty, requestId)
                    } else {
                        handleFailure(error, written = true)
                    }
                }
            }
        }
    }

    private fun showRetryDialog(
        message: String,
        scan: JSONObject,
        payload: ScanPayload,
        qty: Int,
        requestId: String,
    ) {
        feedback.error()
        reportingScreen?.showError("网络中断，提交结果未知")
        AlertDialog.Builder(this)
            .setTitle("提交结果未知")
            .setMessage("网络异常：$message\n\n请点“重试同一笔”。APP 会沿用同一个幂等请求号，后端不会重复累计数量。")
            .setCancelable(false)
            .setNegativeButton("返回并核对记录") { _, _ ->
                busy = false
                reportingScreen?.showError("请先核对今日记录；未看到这笔再重新扫码")
                loadHistory()
            }
            .setPositiveButton("重试同一笔") { _, _ -> submit(scan, payload, qty, requestId) }
            .show()
    }

    private fun revoke(record: HistoryRecord) {
        if (busy) return
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
        executor.execute {
            try {
                val (records, stats) = api.history()
                ui { reportingScreen?.setHistory(records, stats.first, stats.second) }
            } catch (error: Exception) {
                if (error is ApiException && error.statusCode == 401) ui { sessionExpired() }
            }
        }
    }

    private fun loadImage(path: String, view: ImageView) {
        executor.execute {
            try {
                val bytes = api.image(path)
                ui { reportingScreen?.displayImage(bytes, view) }
            } catch (_: Exception) {
                // 图片加载失败不阻塞报工，文本要求和核心操作仍可继续。
            }
        }
    }

    private fun handleFailure(error: Exception, written: Boolean) {
        if (error is ApiException && error.statusCode == 401) {
            sessionExpired()
            return
        }
        busy = false
        feedback.error()
        val prefix = if (written) "操作失败：" else "扫码失败："
        reportingScreen?.showError(prefix + readableError(error))
    }

    private fun sessionExpired() {
        clearSession()
        showLogin("登录已过期，请重新登录")
    }

    private fun showSettings() {
        scannerInput.setEnabled(false)
        val wrapper = Ui.vertical(this, 20)
        val server = EditText(this).apply {
            setText(api.baseUrl)
            hint = "https://leshine.work"
            isSingleLine = true
        }
        val autoUnit = Switch(this).apply {
            text = "逐件二维码识别后自动报 1 件"
            isChecked = prefs.getBoolean(KEY_AUTO_UNIT, true)
            setTextColor(Ui.ink)
        }
        wrapper.addView(Ui.text(this, "服务器地址", 13f, Ui.secondary, true))
        wrapper.addView(server, Ui.margin(top = 6, context = this))
        wrapper.addView(autoUnit, Ui.margin(top = 16, context = this))
        wrapper.addView(Ui.text(this, "广播扫描配置：Action = ${ScannerInput.CUSTOM_ACTION}\nExtra 可用 data 或 DataWedge 默认 data_string；键盘输出模式无需配置。", 12f, Ui.muted), Ui.margin(top = 12, context = this))

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
                    prefs.edit().putString(KEY_SERVER, normalized).putBoolean(KEY_AUTO_UNIT, autoUnit.isChecked).apply()
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
        private const val KEY_AUTO_UNIT = "auto_unit_submit"
    }
}
