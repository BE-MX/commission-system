package com.leshine.pdareporting

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
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
    private val onMalformedBroadcast: (String) -> Unit,
) {
    private val handler = Handler(Looper.getMainLooper())
    private val keyBuffer = StringBuilder()
    private var lastKeyAt = 0L
    private var registered = false
    private var enabled = false

    private val idleSubmit = Runnable { submitKeyBuffer() }
    private val bridgeListener: (String, String?) -> Unit = ::handleBroadcast

    private val receiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (!enabled || intent == null) return
            handleBroadcast(intent.action.orEmpty(), ScanBroadcastContract.extract(intent.extras))
        }
    }

    fun start() {
        if (registered) return
        val filter = IntentFilter().apply {
            ScanBroadcastContract.dynamicActions.forEach(::addAction)
            ScanBroadcastContract.requiredCategories.forEach(::addCategory)
        }
        ContextCompat.registerReceiver(context, receiver, filter, ContextCompat.RECEIVER_EXPORTED)
        ScanBroadcastBridge.attach(bridgeListener)
        registered = true
    }

    fun stop() {
        if (!registered) return
        ScanBroadcastBridge.detach(bridgeListener)
        context.unregisterReceiver(receiver)
        registered = false
        handler.removeCallbacks(idleSubmit)
        keyBuffer.clear()
    }

    private fun handleBroadcast(action: String, code: String?) {
        if (!enabled) return
        if (code == null) {
            onMalformedBroadcast(action)
        } else {
            onCode(code, ScanSource.BROADCAST)
        }
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

    companion object {
        private const val KEY_SEQUENCE_GAP_MS = 250L
        private const val IDLE_SUBMIT_MS = 180L
    }
}
