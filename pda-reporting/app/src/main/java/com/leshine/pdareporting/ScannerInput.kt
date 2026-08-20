package com.leshine.pdareporting

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.KeyEvent
import androidx.core.content.ContextCompat

/**
 * Receives scan-head output without opening the camera.
 *
 * Keyboard-wedge mode works on virtually every PDA and is the default. Broadcast
 * mode covers common vendor defaults plus a stable custom action that can be used
 * by Zebra DataWedge or an OEM scanner profile.
 */
class ScannerInput(
    private val context: Context,
    private val onCode: (String, ScanSource) -> Unit,
) {
    private val handler = Handler(Looper.getMainLooper())
    private val keyBuffer = StringBuilder()
    private var lastKeyAt = 0L
    private var registered = false
    private var enabled = false

    private val idleSubmit = Runnable { submitKeyBuffer() }

    private val receiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (!enabled || intent == null) return
            extractCode(intent)?.let { onCode(it, ScanSource.BROADCAST) }
        }
    }

    fun start() {
        if (registered) return
        val filter = IntentFilter().apply {
            COMMON_ACTIONS.forEach(::addAction)
            addCategory(Intent.CATEGORY_DEFAULT)
        }
        ContextCompat.registerReceiver(context, receiver, filter, ContextCompat.RECEIVER_EXPORTED)
        registered = true
    }

    fun stop() {
        if (!registered) return
        context.unregisterReceiver(receiver)
        registered = false
        handler.removeCallbacks(idleSubmit)
        keyBuffer.clear()
    }

    fun setEnabled(value: Boolean) {
        enabled = value
        if (!value) {
            handler.removeCallbacks(idleSubmit)
            keyBuffer.clear()
        }
    }

    /** Return true when a hardware scan keystroke was consumed. */
    fun onKeyEvent(event: KeyEvent): Boolean {
        if (!enabled || event.action != KeyEvent.ACTION_DOWN) return false

        if (event.keyCode == KeyEvent.KEYCODE_ENTER || event.keyCode == KeyEvent.KEYCODE_TAB) {
            if (keyBuffer.isEmpty()) return false
            submitKeyBuffer()
            return true
        }

        val unicode = event.unicodeChar
        if (unicode == 0 || Character.isISOControl(unicode)) return false
        val now = event.eventTime
        if (lastKeyAt > 0 && now - lastKeyAt > KEY_SEQUENCE_GAP_MS) keyBuffer.clear()
        lastKeyAt = now
        keyBuffer.append(unicode.toChar())
        handler.removeCallbacks(idleSubmit)
        handler.postDelayed(idleSubmit, IDLE_SUBMIT_MS)
        return true
    }

    private fun submitKeyBuffer() {
        handler.removeCallbacks(idleSubmit)
        val value = keyBuffer.toString().trim()
        keyBuffer.clear()
        lastKeyAt = 0L
        if (value.length >= 8) onCode(value, ScanSource.KEYBOARD)
    }

    private fun extractCode(intent: Intent): String? {
        EXTRA_KEYS.forEach { key ->
            extractValue(intent.extras, key)?.let { if (it.isNotBlank()) return it.trim() }
        }
        intent.extras?.keySet()?.forEach { key ->
            val value = extractValue(intent.extras, key) ?: return@forEach
            if (value.contains("ARK-D", ignoreCase = true)) return value.trim()
        }
        return null
    }

    @Suppress("DEPRECATION")
    private fun extractValue(extras: Bundle?, key: String): String? {
        val value = extras?.get(key) ?: return null
        return when (value) {
            is String -> value
            is ByteArray -> value.toString(Charsets.UTF_8).trimEnd('\u0000')
            is CharSequence -> value.toString()
            else -> null
        }
    }

    companion object {
        const val CUSTOM_ACTION = "com.leshine.pdareporting.SCAN"
        private const val KEY_SEQUENCE_GAP_MS = 250L
        private const val IDLE_SUBMIT_MS = 180L

        private val COMMON_ACTIONS = listOf(
            CUSTOM_ACTION,
            "com.sunmi.scanner.ACTION_DATA_CODE_RECEIVED",
            "android.intent.ACTION_DECODE_DATA",
            "nlscan.action.SCANNER_RESULT",
            "com.honeywell.aidc.action.ACTION_BARCODE_READ_EVENT",
            "com.android.server.scannerservice.broadcast",
        )

        private val EXTRA_KEYS = listOf(
            "com.symbol.datawedge.data_string",
            "com.honeywell.aidc.extra.EXTRA_BARCODE_DATA",
            "data",
            "barcode",
            "barcode_string",
            "barcodeData",
            "decode_data",
            "SCAN_BARCODE1",
            "scannerdata",
        )
    }
}
