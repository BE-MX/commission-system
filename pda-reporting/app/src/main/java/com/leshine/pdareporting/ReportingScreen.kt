package com.leshine.pdareporting

import android.app.AlertDialog
import android.content.Context
import android.graphics.BitmapFactory
import android.graphics.Color
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.HorizontalScrollView
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import org.json.JSONObject

class ReportingScreen(
    context: Context,
    userName: String,
    private val onManualScan: (String) -> Unit,
    private val onRevoke: (HistoryRecord) -> Unit,
    private val onSettings: () -> Unit,
    private val onLogout: () -> Unit,
) : LinearLayout(context) {
    private val statusCard = Ui.vertical(context, 18)
    private val statusTitle = Ui.text(context, "扫描头已就绪", 19f, Ui.green, true)
    private val statusDetail = Ui.text(context, "按下 PDA 扫描键，对准内贸二维码", 13f, Ui.secondary)
    private val countText = metric("0", "今日次数")
    private val qtyText = metric("0", "今日件数")
    private val historyList = Ui.vertical(context)
    private val emptyText = Ui.text(context, "今天还没有报工记录\n扫描第一张流转卡开始报工", 14f, Ui.muted).apply {
        gravity = Gravity.CENTER
        setPadding(0, Ui.dp(context, 32), 0, Ui.dp(context, 32))
    }

    init {
        orientation = VERTICAL
        setBackgroundColor(Ui.page)

        val header = LinearLayout(context).apply {
            orientation = HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(Ui.dp(context, 18), Ui.dp(context, 14), Ui.dp(context, 10), Ui.dp(context, 14))
            background = Ui.rounded(Ui.green, 0, context)
        }
        val titles = Ui.vertical(context).apply {
            addView(Ui.text(context, "内贸扫描报工", 21f, Color.WHITE, true))
            addView(Ui.text(context, "$userName · PDA 模式", 12f, Color.argb(210, 255, 255, 255)), Ui.margin(top = 4, context = context))
        }
        header.addView(titles, LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        header.addView(headerAction("设置", onSettings))
        header.addView(headerAction("退出", onLogout))
        addView(header)

        val body = Ui.vertical(context, 14)
        val scroll = ScrollView(context).apply {
            isFillViewport = true
            addView(body, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        }
        addView(scroll, LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))

        statusCard.apply {
            background = Ui.rounded(Color.WHITE, 16, context, Ui.border)
            elevation = Ui.dp(context, 2).toFloat()
            addView(statusTitle)
            addView(statusDetail, Ui.margin(top = 7, context = context))
            addView(
                Ui.text(context, "▦  硬件扫描头输入", 13f, Ui.green, true).apply {
                    gravity = Gravity.CENTER
                    setPadding(0, Ui.dp(context, 13), 0, Ui.dp(context, 13))
                    background = Ui.rounded(Ui.greenSoft, 10, context)
                },
                Ui.margin(top = 16, context = context),
            )
        }
        body.addView(statusCard)

        val metrics = LinearLayout(context).apply { orientation = HORIZONTAL }
        metrics.addView(countText.first, LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        metrics.addView(qtyText.first, LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { leftMargin = Ui.dp(context, 10) })
        body.addView(metrics, Ui.margin(top = 12, context = context))

        body.addView(
            Ui.button(context, "手动输入二维码（调试 / 兜底）", primary = false) { showManualDialog() },
            Ui.margin(top = 12, context = context),
        )

        val historyHeader = LinearLayout(context).apply {
            orientation = HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            addView(Ui.text(context, "今日报工记录", 17f, Ui.ink, true), LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            addView(Ui.text(context, "仅本人", 12f, Ui.muted))
        }
        body.addView(historyHeader, Ui.margin(top = 24, bottom = 10, context = context))
        body.addView(historyList)
        historyList.addView(emptyText)
    }

    private fun headerAction(label: String, action: () -> Unit) = TextView(context).apply {
        text = label
        textSize = 13f
        setTextColor(Color.WHITE)
        gravity = Gravity.CENTER
        setPadding(Ui.dp(context, 10), Ui.dp(context, 9), Ui.dp(context, 10), Ui.dp(context, 9))
        setOnClickListener { action() }
    }

    private fun metric(value: String, label: String): Pair<View, TextView> {
        val number = Ui.text(context, value, 26f, Ui.green, true)
        val card = Ui.vertical(context, 14).apply {
            gravity = Gravity.CENTER
            background = Ui.rounded(Color.WHITE, 14, context, Ui.border)
            addView(number)
            addView(Ui.text(context, label, 12f, Ui.secondary), Ui.margin(top = 5, context = context))
        }
        return card to number
    }

    fun showScanning(raw: String) {
        statusCard.background = Ui.rounded(Ui.greenSoft, 16, context, Ui.greenBright)
        statusTitle.text = "二维码已读取，正在校验"
        statusTitle.setTextColor(Ui.green)
        statusDetail.text = raw.take(48)
    }

    fun showSubmitting(product: String, process: String) {
        statusCard.background = Ui.rounded(Color.rgb(255, 247, 227), 16, context, Color.rgb(229, 192, 112))
        statusTitle.text = "正在提交报工"
        statusTitle.setTextColor(Ui.warning)
        statusDetail.text = "$product · $process"
    }

    fun showSuccess(message: String) {
        statusCard.background = Ui.rounded(Ui.greenSoft, 16, context, Ui.greenBright)
        statusTitle.text = "✓ 报工成功"
        statusTitle.setTextColor(Ui.green)
        statusDetail.text = message
    }

    fun showError(message: String) {
        statusCard.background = Ui.rounded(Color.rgb(255, 239, 237), 16, context, Color.rgb(235, 180, 175))
        statusTitle.text = "扫描 / 报工失败"
        statusTitle.setTextColor(Ui.danger)
        statusDetail.text = message
    }

    fun showReady() {
        statusCard.background = Ui.rounded(Color.WHITE, 16, context, Ui.border)
        statusTitle.text = "扫描头已就绪"
        statusTitle.setTextColor(Ui.green)
        statusDetail.text = "按下 PDA 扫描键，对准内贸二维码"
    }

    fun setHistory(records: List<HistoryRecord>, count: Int, qty: Int) {
        countText.second.text = count.toString()
        qtyText.second.text = qty.toString()
        historyList.removeAllViews()
        if (records.isEmpty()) {
            historyList.addView(emptyText)
            return
        }
        records.forEach { record -> historyList.addView(historyRow(record), Ui.margin(bottom = 9, context = context)) }
    }

    private fun historyRow(record: HistoryRecord): View {
        val row = LinearLayout(context).apply {
            orientation = HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(Ui.dp(context, 14), Ui.dp(context, 13), Ui.dp(context, 10), Ui.dp(context, 13))
            background = Ui.rounded(Color.WHITE, 12, context, Ui.border)
            alpha = if (record.revoked) 0.5f else 1f
        }
        val content = Ui.vertical(context).apply {
            addView(Ui.text(context, record.productName, 15f, Ui.ink, true))
            val unitSuffix = if (record.unitCodes.isEmpty()) "" else " · ${record.unitCodes.joinToString("、")}" 
            addView(Ui.text(context, "${record.processName} × ${record.reportQty} 件$unitSuffix", 13f, Ui.green, true), Ui.margin(top = 5, context = context))
            val bottom = listOf(record.orderLabel, record.reportedAt).filter { it.isNotBlank() }.joinToString(" · ")
            addView(Ui.text(context, bottom, 11f, Ui.muted), Ui.margin(top = 5, context = context))
        }
        row.addView(content, LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        if (record.revoked) {
            row.addView(Ui.text(context, "已撤销", 12f, Ui.muted, true))
        } else {
            row.addView(Ui.button(context, "撤销", primary = false) { confirmRevoke(record) }, Ui.margin(Ui.dp(context, 74), Ui.dp(context, 42), left = 8, context = context))
        }
        return row
    }

    private fun confirmRevoke(record: HistoryRecord) {
        AlertDialog.Builder(context)
            .setTitle("撤销报工")
            .setMessage("确定撤销「${record.processName} × ${record.reportQty} 件」？下游已经使用这些件时，后端会阻止撤销。")
            .setNegativeButton("取消", null)
            .setPositiveButton("确认撤销") { _, _ -> onRevoke(record) }
            .show()
    }

    private fun showManualDialog() {
        val input = EditText(context).apply {
            hint = "ARK-D:... 或 ARK-DU:..."
            setPadding(Ui.dp(context, 14), Ui.dp(context, 8), Ui.dp(context, 14), Ui.dp(context, 8))
            isSingleLine = true
        }
        AlertDialog.Builder(context)
            .setTitle("手动输入二维码")
            .setView(input)
            .setNegativeButton("取消", null)
            .setPositiveButton("识别") { _, _ -> onManualScan(input.text.toString()) }
            .show()
    }

    fun showQuantityConfirmation(
        scan: JSONObject,
        onConfirm: (Int) -> Unit,
        onCancel: () -> Unit,
        loadImage: (String, ImageView) -> Unit,
    ) {
        val next = scan.getJSONObject("next_step")
        val maxQty = next.optInt("reportable_qty", 1).coerceAtLeast(1)
        val content = Ui.vertical(context, 18)
        content.addView(infoBlock("产品", scan.optString("product_name", "-"), true))
        content.addView(infoBlock("客户", scan.optString("customer_name", "-")))
        val orderLabel = listOf(scan.optString("domestic_no"), scan.optString("order_no"))
            .filter { it.isNotBlank() && it != "null" }.joinToString(" · ").ifBlank { "-" }
        content.addView(infoBlock("订单", orderLabel))
        val isUnit = scan.optString("report_mode") == "unit"
        if (isUnit) content.addView(infoBlock("单件编号", scan.optString("unit_code", "-"), true))
        content.addView(infoBlock("当前工序", next.optString("process_name", "-"), true))

        val qtyLabel = Ui.text(
            context,
            if (isUnit) "本次固定报工 1 件" else "报工数量（最多 $maxQty 件）",
            14f,
            Ui.ink,
            true,
        )
        content.addView(qtyLabel, Ui.margin(top = 16, context = context))
        val qtyInput = EditText(context).apply {
            inputType = InputType.TYPE_CLASS_NUMBER
            setText(maxQty.toString())
            selectAll()
            isEnabled = !isUnit
            textSize = 24f
            gravity = Gravity.CENTER
            background = Ui.rounded(Color.WHITE, 10, context, Ui.greenBright)
        }
        content.addView(qtyInput, Ui.margin(height = Ui.dp(context, 56), top = 8, context = context))
        content.addView(
            Ui.text(
                context,
                if (isUnit) "单件二维码只对应这一件产品；同一道工序重复扫描会被后端拦截。"
                else "默认报当前全部可报数量；改小即拆批，剩余数量之后继续扫同一张卡。",
                12f,
                Ui.secondary,
            ),
            Ui.margin(top = 7, context = context),
        )

        addRequirements(content, scan, loadImage)
        addProgress(content, scan)

        val scroll = ScrollView(context).apply {
            setPadding(Ui.dp(context, 4), 0, Ui.dp(context, 4), 0)
            addView(content)
        }
        val dialog = AlertDialog.Builder(context)
            .setTitle("确认报工信息")
            .setView(scroll)
            .setNegativeButton("取消", null)
            .setPositiveButton("确认报工", null)
            .create()
        var confirmed = false
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                val qty = qtyInput.text.toString().toIntOrNull() ?: 0
                if (qty !in 1..maxQty) {
                    qtyInput.error = "请输入 1 到 $maxQty"
                } else {
                    confirmed = true
                    dialog.dismiss()
                    onConfirm(qty)
                }
            }
        }
        dialog.setOnDismissListener { if (!confirmed) onCancel() }
        dialog.show()
    }

    private fun infoBlock(label: String, value: String, emphasize: Boolean = false): View {
        val row = LinearLayout(context).apply {
            orientation = HORIZONTAL
            gravity = Gravity.TOP
            setPadding(0, Ui.dp(context, 6), 0, Ui.dp(context, 6))
        }
        row.addView(Ui.text(context, label, 13f, Ui.secondary), Ui.margin(Ui.dp(context, 78), context = context))
        row.addView(Ui.text(context, value.ifBlank { "-" }, if (emphasize) 16f else 14f, if (emphasize) Ui.green else Ui.ink, emphasize), LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        return row
    }

    private fun addRequirements(content: LinearLayout, scan: JSONObject, loadImage: (String, ImageView) -> Unit) {
        val textRows = listOf(
            "发型" to scan.optString("hairstyle"),
            "颜色" to scan.optString("color"),
            "要求" to scan.optString("style_requirement"),
            "备注" to scan.optString("remark"),
        ).filter { it.second.isNotBlank() && it.second != "null" }
        val paths = mutableListOf<String>()
        listOf("hairstyle_images", "color_images", "style_images", "remark_images").forEach { key ->
            val array = scan.optJSONArray(key) ?: return@forEach
            for (i in 0 until array.length()) paths += array.optString(i)
        }
        if (textRows.isEmpty() && paths.isEmpty()) return

        content.addView(Ui.text(context, "图文要求", 15f, Ui.ink, true), Ui.margin(top = 18, bottom = 5, context = context))
        textRows.forEach { (label, value) -> content.addView(infoBlock(label, value)) }
        if (paths.isNotEmpty()) {
            val strip = LinearLayout(context).apply { orientation = HORIZONTAL }
            paths.forEach { path ->
                val image = ImageView(context).apply {
                    scaleType = ImageView.ScaleType.CENTER_CROP
                    setBackgroundColor(Ui.greenSoft)
                }
                strip.addView(image, Ui.margin(Ui.dp(context, 104), Ui.dp(context, 104), right = 8, context = context))
                loadImage(path, image)
            }
            content.addView(HorizontalScrollView(context).apply { addView(strip) }, Ui.margin(top = 8, context = context))
        }
    }

    private fun addProgress(content: LinearLayout, scan: JSONObject) {
        val steps = scan.optJSONArray("steps") ?: return
        if (steps.length() == 0) return
        content.addView(Ui.text(context, "工序进度", 15f, Ui.ink, true), Ui.margin(top = 18, bottom = 5, context = context))
        for (i in 0 until steps.length()) {
            val step = steps.getJSONObject(i)
            content.addView(infoBlock(
                "第 ${step.optInt("step_order")} 道",
                "${step.optString("process_name")}  ${step.optInt("completed_qty")} / ${step.optInt("order_qty")} 件",
            ))
        }
    }

    fun displayImage(bytes: ByteArray, view: ImageView) {
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size)?.let(view::setImageBitmap)
    }
}
