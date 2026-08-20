package com.leshine.pdareporting

import android.app.AlertDialog
import android.content.Context
import android.graphics.Color
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.HorizontalScrollView
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import org.json.JSONObject

class UnitReportDialog(
    private val context: Context,
    private val loadImage: (String, ImageView) -> Unit,
    private val onClosed: () -> Unit,
) {
    private val handler = Handler(Looper.getMainLooper())
    private val banner = Ui.text(context, "", 18f, Color.WHITE, true).apply {
        gravity = Gravity.CENTER
        setPadding(Ui.dp(context, 14), Ui.dp(context, 14), Ui.dp(context, 14), Ui.dp(context, 14))
        visibility = View.GONE
    }
    private val details = Ui.vertical(context)
    private val closeButton = Ui.button(context, "关闭") { dialog?.dismiss() }.apply {
        textSize = 18f
        minHeight = Ui.dp(context, 56)
    }
    private val root = Ui.vertical(context, 18).apply {
        minimumHeight = (context.resources.displayMetrics.heightPixels * 0.72f).toInt()
        addView(banner)
        addView(
            ScrollView(context).apply { addView(details) },
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f).apply {
                topMargin = Ui.dp(context, 10)
            },
        )
        addView(closeButton, Ui.margin(height = Ui.dp(context, 56), top = 14, context = context))
    }
    private val hideBanner = Runnable { banner.visibility = View.GONE }
    private var dialog: AlertDialog? = null
    private var disposed = false

    fun show(scan: JSONObject, presentation: UnitReportPresentation) {
        if (disposed) return
        updateDetails(scan)
        val current = dialog
        if (current?.isShowing == true) {
            applyPresentation(presentation)
            return
        }

        (root.parent as? ViewGroup)?.removeView(root)
        val created = AlertDialog.Builder(context)
            .setTitle("确认报工信息")
            .setView(root)
            .create()
        dialog = created
        created.setCanceledOnTouchOutside(false)
        created.setOnDismissListener {
            handler.removeCallbacks(hideBanner)
            banner.visibility = View.GONE
            dialog = null
            if (!disposed) onClosed()
        }
        created.show()
        val metrics = context.resources.displayMetrics
        created.window?.setLayout(
            (metrics.widthPixels * 0.94f).toInt(),
            (metrics.heightPixels * 0.88f).toInt(),
        )
        applyPresentation(presentation)
    }

    fun render(presentation: UnitReportPresentation): Boolean {
        if (dialog?.isShowing != true || disposed) return false
        applyPresentation(presentation)
        return true
    }

    fun isShowing(): Boolean = dialog?.isShowing == true

    fun dismiss() {
        dialog?.dismiss()
    }

    fun dispose() {
        disposed = true
        handler.removeCallbacks(hideBanner)
        dialog?.setOnDismissListener(null)
        dialog?.dismiss()
        dialog = null
    }

    private fun applyPresentation(presentation: UnitReportPresentation) {
        handler.removeCallbacks(hideBanner)
        banner.text = presentation.message
        banner.visibility = View.VISIBLE
        when (presentation.tone) {
            UnitReportTone.PROGRESS -> {
                banner.setTextColor(Ui.warning)
                banner.background = Ui.rounded(Color.rgb(255, 247, 227), 12, context, Color.rgb(229, 192, 112))
            }
            UnitReportTone.SUCCESS -> {
                banner.setTextColor(Color.WHITE)
                banner.background = Ui.rounded(Ui.green, 12, context)
            }
            UnitReportTone.ERROR -> {
                banner.setTextColor(Ui.danger)
                banner.background = Ui.rounded(Color.rgb(255, 239, 237), 12, context, Color.rgb(235, 180, 175))
            }
        }
        closeButton.isEnabled = presentation.closeEnabled
        closeButton.alpha = if (presentation.closeEnabled) 1f else 0.5f
        dialog?.setCancelable(presentation.closeEnabled)
        presentation.autoHideAfterMs?.let { handler.postDelayed(hideBanner, it) }
    }

    private fun updateDetails(scan: JSONObject) {
        details.removeAllViews()
        val next = scan.optJSONObject("next_step") ?: JSONObject()
        val orderLabel = listOf(scan.optString("domestic_no"), scan.optString("order_no"))
            .filter { it.isNotBlank() && it != "null" }
            .joinToString(" · ")
            .ifBlank { "-" }
        primaryRow("产品", scan.optString("product_name", "-"), accent = true)
        primaryRow("客户", scan.optString("customer_name", "-"))
        primaryRow("订单", orderLabel)
        primaryRow("单件编号", scan.optString("unit_code", "-"), accent = true)
        primaryRow("当前工序", next.optString("process_name", "-"), accent = true)
        addRequirements(scan)
        addProgress(scan)
    }

    private fun primaryRow(label: String, value: String, accent: Boolean = false) {
        val row = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(0, Ui.dp(context, 9), 0, Ui.dp(context, 9))
        }
        row.addView(Ui.text(context, label, 15f, Ui.secondary, true))
        row.addView(
            Ui.text(context, value.ifBlank { "-" }, 19f, if (accent) Ui.green else Ui.ink, true),
            Ui.margin(top = 5, context = context),
        )
        details.addView(row)
    }

    private fun secondaryRow(label: String, value: String): View {
        val row = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.TOP
            setPadding(0, Ui.dp(context, 6), 0, Ui.dp(context, 6))
        }
        row.addView(Ui.text(context, label, 13f, Ui.secondary, true), Ui.margin(Ui.dp(context, 72), context = context))
        row.addView(
            Ui.text(context, value.ifBlank { "-" }, 14f, Ui.ink),
            LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f),
        )
        return row
    }

    private fun addRequirements(scan: JSONObject) {
        val textRows = listOf(
            "发型" to scan.optString("hairstyle"),
            "颜色" to scan.optString("color"),
            "要求" to scan.optString("style_requirement"),
            "备注" to scan.optString("remark"),
        ).filter { it.second.isNotBlank() && it.second != "null" }
        val paths = mutableListOf<String>()
        listOf("hairstyle_images", "color_images", "style_images", "remark_images").forEach { key ->
            val array = scan.optJSONArray(key) ?: return@forEach
            for (index in 0 until array.length()) paths += array.optString(index)
        }
        if (textRows.isEmpty() && paths.isEmpty()) return

        details.addView(Ui.text(context, "图文要求", 15f, Ui.ink, true), Ui.margin(top = 16, bottom = 5, context = context))
        textRows.forEach { (label, value) -> details.addView(secondaryRow(label, value)) }
        if (paths.isNotEmpty()) {
            val strip = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }
            paths.forEach { path ->
                val image = ImageView(context).apply {
                    scaleType = ImageView.ScaleType.CENTER_CROP
                    setBackgroundColor(Ui.greenSoft)
                }
                strip.addView(image, Ui.margin(Ui.dp(context, 104), Ui.dp(context, 104), right = 8, context = context))
                loadImage(path, image)
            }
            details.addView(HorizontalScrollView(context).apply { addView(strip) }, Ui.margin(top = 8, context = context))
        }
    }

    private fun addProgress(scan: JSONObject) {
        val steps = scan.optJSONArray("steps") ?: return
        if (steps.length() == 0) return
        details.addView(Ui.text(context, "工序进度", 15f, Ui.ink, true), Ui.margin(top = 16, bottom = 5, context = context))
        for (index in 0 until steps.length()) {
            val step = steps.optJSONObject(index) ?: continue
            details.addView(
                secondaryRow(
                    "第 ${step.optInt("step_order")} 道",
                    "${step.optString("process_name")}  ${step.optInt("completed_qty")} / ${step.optInt("order_qty")} 件",
                ),
            )
        }
    }
}
