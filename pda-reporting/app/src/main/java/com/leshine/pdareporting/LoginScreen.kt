package com.leshine.pdareporting

import android.content.Context
import android.graphics.Color
import android.text.InputType
import android.view.Gravity
import android.view.ViewGroup
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView

class LoginScreen(
    context: Context,
    savedUsername: String,
    private val onLogin: (String, String) -> Unit,
    private val onSettings: () -> Unit,
) : ScrollView(context) {
    private val username = field("工号 / 用户名", savedUsername)
    private val password = field("密码", "").apply {
        inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
    }
    private val submit = Ui.button(context, "登录并开始报工") { submit() }
    private val progress = ProgressBar(context).apply { visibility = GONE }
    private val error = Ui.text(context, "", 13f, Ui.danger).apply { visibility = GONE }

    init {
        isFillViewport = true
        setBackgroundColor(Ui.page)

        val root = Ui.vertical(context, 24).apply {
            gravity = Gravity.CENTER_HORIZONTAL
        }
        addView(root, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))

        val mark = TextView(context).apply {
            text = "▣"
            textSize = 52f
            gravity = Gravity.CENTER
            setTextColor(Color.WHITE)
            background = Ui.rounded(Ui.green, 24, context)
        }
        root.addView(mark, Ui.margin(Ui.dp(context, 88), Ui.dp(context, 88), top = 42, context = context))
        root.addView(Ui.text(context, "莱莎内贸报工", 26f, Ui.ink, true), Ui.margin(top = 20, context = context))
        root.addView(Ui.text(context, "PDA 扫描头专用", 14f, Ui.secondary), Ui.margin(top = 8, context = context))

        val card = Ui.vertical(context, 20).apply {
            background = Ui.rounded(Color.WHITE, 16, context, Ui.border)
            elevation = Ui.dp(context, 3).toFloat()
        }
        card.addView(Ui.text(context, "账号登录", 18f, Ui.ink, true))
        card.addView(Ui.text(context, "使用方舟账号登录，报工记录仍归入本人", 13f, Ui.secondary), Ui.margin(top = 6, context = context))
        card.addView(username, Ui.margin(top = 22, context = context))
        card.addView(password, Ui.margin(top = 12, context = context))
        card.addView(error, Ui.margin(top = 12, context = context))

        val action = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        action.addView(submit, LinearLayout.LayoutParams(0, Ui.dp(context, 50), 1f))
        action.addView(progress, Ui.margin(Ui.dp(context, 44), Ui.dp(context, 44), left = 12, context = context))
        card.addView(action, Ui.margin(top = 18, context = context))
        root.addView(card, Ui.margin(top = 30, context = context))

        val settings = Ui.button(context, "服务器设置", primary = false, onClick = onSettings)
        root.addView(settings, Ui.margin(top = 16, context = context))
        root.addView(
            Ui.text(context, "扫描头请设置为“键盘输出 + 回车”；无需相机权限。", 12f, Ui.muted).apply {
                gravity = Gravity.CENTER
            },
            Ui.margin(top = 22, bottom = 30, context = context),
        )

        password.setOnEditorActionListener { _, _, _ -> submit(); true }
    }

    private fun field(hintText: String, initial: String) = EditText(context).apply {
        hint = hintText
        setText(initial)
        textSize = 16f
        setTextColor(Ui.ink)
        setHintTextColor(Ui.muted)
        setPadding(Ui.dp(context, 14), 0, Ui.dp(context, 14), 0)
        background = Ui.rounded(Color.WHITE, 10, context, Ui.border)
        layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(context, 52))
        isSingleLine = true
    }

    private fun submit() {
        val user = username.text.toString().trim()
        val pass = password.text.toString()
        if (user.isBlank() || pass.isBlank()) {
            showError("请输入工号和密码")
            return
        }
        if (pass.length < 6) {
            showError("密码至少 6 位")
            return
        }
        onLogin(user, pass)
    }

    fun setLoading(value: Boolean) {
        submit.isEnabled = !value
        username.isEnabled = !value
        password.isEnabled = !value
        progress.visibility = if (value) VISIBLE else GONE
        if (value) error.visibility = GONE
    }

    fun showError(message: String) {
        error.text = message
        error.visibility = VISIBLE
    }
}
