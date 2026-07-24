package com.leshine.expokiosk

import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.text.InputType
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.Toast
import java.net.URL

/**
 * kiosk 服务器地址的运行时配置。
 *
 * 展位现场唯一会变的东西就是服务器地址（云实例换 IP、备案后换域名、现场局域网兜底），
 * 为此重打包重装 APK 是纯浪费——所以地址存 SharedPreferences，工作人员现改现用，
 * 没存过时回落到 strings.xml 的 start_url。
 *
 * **只存 origin（协议+主机+端口），路径由代码固定拼 [KIOSK_PATH]**：这样即便有人摸到这个入口，
 * 最坏也只能把平板指向另一台服务器的 kiosk 页，而不能把展位平板变成一台自由浏览器。
 */
object KioskUrl {

    private const val PREFS = "kiosk_prefs"
    private const val KEY_ORIGIN = "server_origin"
    private const val KIOSK_PATH = "/expo/kiosk"

    fun get(ctx: Context): String {
        val origin = savedOrigin(ctx)
        return if (origin != null) origin + KIOSK_PATH else ctx.getString(R.string.start_url)
    }

    /**
     * 弹地址设置框。保存/恢复默认后回调新地址，由调用方决定何时 reload；
     * 无论走哪个按钮或点框外关闭，都会回调 [onDismiss]（调用方靠它复位"框已开"标志）。
     * 输入非法时不关框，免得工作人员重新做一遍手势。
     */
    fun showDialog(activity: Activity, onDismiss: () -> Unit, onApply: (String) -> Unit) {
        val input = EditText(activity).apply {
            inputType = InputType.TYPE_TEXT_VARIATION_URI
            setSingleLine()
            setText(currentOrigin(activity))
            setSelection(text.length)
        }
        val pad = (16 * activity.resources.displayMetrics.density).toInt()
        val wrap = LinearLayout(activity).apply {
            setPadding(pad, pad, pad, 0)
            addView(input)
        }

        val dialog = AlertDialog.Builder(activity)
            .setTitle(R.string.config_title)
            .setMessage(R.string.config_hint)
            .setView(wrap)
            .setPositiveButton(R.string.config_save, null) // onClick 在 show() 后接管，非法输入不关框
            .setNeutralButton(R.string.config_reset) { _, _ ->
                prefs(activity).edit().remove(KEY_ORIGIN).apply()
                onApply(get(activity))
            }
            .setNegativeButton(R.string.config_cancel, null)
            .create()

        dialog.setOnDismissListener { onDismiss() }
        dialog.show()
        dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
            val origin = normalizeOrigin(input.text.toString())
            if (origin == null) {
                Toast.makeText(activity, R.string.config_invalid, Toast.LENGTH_LONG).show()
                return@setOnClickListener
            }
            prefs(activity).edit().putString(KEY_ORIGIN, origin).apply()
            dialog.dismiss()
            onApply(get(activity))
        }
    }

    private fun prefs(ctx: Context) = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    private fun savedOrigin(ctx: Context): String? =
        prefs(ctx).getString(KEY_ORIGIN, null)?.takeIf { it.isNotBlank() }

    /** 回填输入框用：存过就用存的，没存过就从 strings.xml 的默认地址里剥出 origin */
    private fun currentOrigin(ctx: Context): String =
        savedOrigin(ctx) ?: normalizeOrigin(ctx.getString(R.string.start_url)).orEmpty()

    /**
     * 把工作人员输入的任意写法归一成 `scheme://host[:port]`：补协议（默认 http，现场基本是 IP 直连）、
     * **丢弃路径/查询/片段**。按解析结果重建而非字符串拼接——拼接在 `1.2.3.4/?a=1`、`1.2.3.4#x`
     * 这类输入上会产出能加载、却指向站点根的坏地址（不触发兜底页，现场极难排查）。
     */
    private fun normalizeOrigin(raw: String): String? {
        var s = raw.trim()
        if (s.isEmpty()) return null
        if (!s.startsWith("http://", true) && !s.startsWith("https://", true)) s = "http://$s"
        return try {
            val u = URL(s)
            val scheme = u.protocol.lowercase()
            if (scheme != "http" && scheme != "https") return null
            val host = u.host?.takeIf { it.isNotBlank() } ?: return null
            if (u.port > 0) "$scheme://$host:${u.port}" else "$scheme://$host"
        } catch (e: Exception) {
            null
        }
    }
}
