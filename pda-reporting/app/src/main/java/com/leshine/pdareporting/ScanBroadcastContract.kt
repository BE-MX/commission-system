package com.leshine.pdareporting

import android.os.Bundle

internal object ScanBroadcastContract {
    const val VENDOR_ACTION = "android.intent.ACTION_DECODE_DATA"
    const val VENDOR_EXTRA = "barcode_string"

    val requiredCategories = listOf("android.intent.category.DEFAULT")

    val dynamicActions = listOf(
        "com.leshine.pdareporting.SCAN",
        "com.sunmi.scanner.ACTION_DATA_CODE_RECEIVED",
        "nlscan.action.SCANNER_RESULT",
        "com.honeywell.aidc.action.ACTION_BARCODE_READ_EVENT",
        "com.android.server.scannerservice.broadcast",
    )

    private val extraKeys = listOf(
        VENDOR_EXTRA,
        "com.symbol.datawedge.data_string",
        "com.honeywell.aidc.extra.EXTRA_BARCODE_DATA",
        "data",
        "barcode",
        "barcodeData",
        "decode_data",
        "SCAN_BARCODE1",
        "scannerdata",
    )

    fun extract(values: Map<String, Any?>): String? {
        extraKeys.forEach { key ->
            normalize(values[key])?.let { return it }
        }
        values.values.forEach { value ->
            normalize(value)?.let { if (it.contains("ARK-D", ignoreCase = true)) return it }
        }
        return null
    }

    @Suppress("DEPRECATION")
    fun extract(extras: Bundle?): String? {
        val values = extraKeys.associateWith { key ->
            runCatching { extras?.get(key) }.getOrNull()
        }
        return extract(values)
    }

    private fun normalize(value: Any?): String? {
        val text = when (value) {
            is String -> value
            is ByteArray -> value.toString(Charsets.UTF_8).trimEnd('\u0000')
            is CharSequence -> value.toString()
            else -> return null
        }.trim()
        return text.ifBlank { null }
    }
}
