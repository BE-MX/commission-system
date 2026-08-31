package com.leshine.pdareporting

import android.content.SharedPreferences
import org.json.JSONObject

class PendingSubmissionStore(private val prefs: SharedPreferences) {
    fun persist(
        scan: JSONObject,
        payload: ScanPayload,
        qty: Int,
        requestId: String,
        outcomes: JSONObject?,
    ): Boolean =
        prefs.edit()
            .putString(KEY_SCAN, scan.toString())
            .putString(KEY_RAW, payload.raw)
            .putInt(KEY_QTY, qty)
            .putString(KEY_REQUEST_ID, requestId)
            .putString(KEY_OUTCOMES, outcomes?.toString())
            .commit()

    fun get(): PendingSubmission? {
        val requestId = prefs.getString(KEY_REQUEST_ID, "").orEmpty()
        if (requestId.isBlank()) return null
        val scan = prefs.getString(KEY_SCAN, "").orEmpty()
        val raw = prefs.getString(KEY_RAW, "").orEmpty()
        val qty = prefs.getInt(KEY_QTY, 0)
        if (scan.isBlank() || raw.isBlank() || qty < 1) {
            clear(requestId)
            return null
        }
        val outcomes = prefs.getString(KEY_OUTCOMES, null)
        if (outcomes != null && runCatching { JSONObject(outcomes) }.isFailure) {
            clear(requestId)
            return null
        }
        return PendingSubmission(scan, raw, qty, requestId, outcomes)
    }

    fun clear(requestId: String) {
        if (prefs.getString(KEY_REQUEST_ID, "") != requestId) return
        prefs.edit()
            .remove(KEY_SCAN)
            .remove(KEY_RAW)
            .remove(KEY_QTY)
            .remove(KEY_REQUEST_ID)
            .remove(KEY_OUTCOMES)
            .apply()
    }

    private companion object {
        const val KEY_SCAN = "pending_scan"
        const val KEY_RAW = "pending_raw"
        const val KEY_QTY = "pending_qty"
        const val KEY_REQUEST_ID = "pending_request_id"
        const val KEY_OUTCOMES = "pending_outcomes"
    }
}
