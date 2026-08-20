package com.leshine.pdareporting

enum class UnitReportTone {
    PROGRESS,
    SUCCESS,
    ERROR,
}

data class UnitReportPresentation(
    val tone: UnitReportTone,
    val message: String,
    val closeEnabled: Boolean,
    val nextScanEnabled: Boolean,
    val autoHideAfterMs: Long? = null,
)

object UnitReportFlow {
    const val SUCCESS_VISIBLE_MS = 3_000L

    fun shouldAutoSubmit(reportMode: String): Boolean = reportMode == "unit"

    fun scanning(): UnitReportPresentation = UnitReportPresentation(
        tone = UnitReportTone.PROGRESS,
        message = "正在识别下一件…",
        closeEnabled = false,
        nextScanEnabled = false,
    )

    fun submitting(): UnitReportPresentation = UnitReportPresentation(
        tone = UnitReportTone.PROGRESS,
        message = "正在报工…",
        closeEnabled = false,
        nextScanEnabled = false,
    )

    fun success(detail: String): UnitReportPresentation = UnitReportPresentation(
        tone = UnitReportTone.SUCCESS,
        message = "✓ 报工成功\n$detail",
        closeEnabled = true,
        nextScanEnabled = true,
        autoHideAfterMs = SUCCESS_VISIBLE_MS,
    )

    fun error(message: String): UnitReportPresentation = UnitReportPresentation(
        tone = UnitReportTone.ERROR,
        message = message,
        closeEnabled = true,
        nextScanEnabled = true,
    )

    fun resultUnknown(): UnitReportPresentation = UnitReportPresentation(
        tone = UnitReportTone.ERROR,
        message = "提交结果未知，请按提示重试或返回核对记录",
        closeEnabled = true,
        nextScanEnabled = false,
    )
}
