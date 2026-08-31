package com.leshine.pdareporting

import android.content.SharedPreferences
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PendingSubmissionStoreTest {
    @Test
    fun malformed_outcomes_are_classified_as_unsafe_to_retry() {
        val result = PendingSubmissionFlow.parseOutcomes("[") { throw IllegalArgumentException("bad json") }

        assertTrue(result is PendingOutcomes.Corrupt)
    }

    @Test
    fun valid_outcomes_are_decoded_once_for_retry() {
        var decodeCount = 0
        val result = PendingSubmissionFlow.parseOutcomes("{\"dandong\":1}") {
            decodeCount += 1
            linkedMapOf("dandong" to 1)
        }

        assertTrue(result is PendingOutcomes.Ready)
        assertEquals(linkedMapOf("dandong" to 1), (result as PendingOutcomes.Ready).value)
        assertEquals(1, decodeCount)
    }

    @Test
    fun malformed_outcomes_keep_pending_request_for_manual_reconciliation() {
        val prefs = MemoryPreferences(
            mutableMapOf(
                "pending_scan" to "{}",
                "pending_raw" to "ARK-D:1:abcdef",
                "pending_qty" to 1,
                "pending_request_id" to "stable-request-id",
                "pending_outcomes" to "[",
            ),
        )

        val pending = PendingSubmissionStore(prefs).get()

        assertNotNull(pending)
        assertEquals("stable-request-id", pending?.requestId)
        assertEquals("[", pending?.outcomes)
        assertEquals("stable-request-id", prefs.getString("pending_request_id", null))
        assertTrue(prefs.contains("pending_outcomes"))
    }
}

private class MemoryPreferences(
    private val values: MutableMap<String, Any?> = mutableMapOf(),
) : SharedPreferences {
    override fun getAll(): MutableMap<String, *> = values.toMutableMap()
    override fun getString(key: String?, defValue: String?): String? = values[key] as? String ?: defValue
    override fun getStringSet(key: String?, defValues: MutableSet<String>?): MutableSet<String>? =
        @Suppress("UNCHECKED_CAST") ((values[key] as? Set<String>)?.toMutableSet() ?: defValues)
    override fun getInt(key: String?, defValue: Int): Int = values[key] as? Int ?: defValue
    override fun getLong(key: String?, defValue: Long): Long = values[key] as? Long ?: defValue
    override fun getFloat(key: String?, defValue: Float): Float = values[key] as? Float ?: defValue
    override fun getBoolean(key: String?, defValue: Boolean): Boolean = values[key] as? Boolean ?: defValue
    override fun contains(key: String?): Boolean = values.containsKey(key)
    override fun edit(): SharedPreferences.Editor = MemoryEditor(values)
    override fun registerOnSharedPreferenceChangeListener(listener: SharedPreferences.OnSharedPreferenceChangeListener?) = Unit
    override fun unregisterOnSharedPreferenceChangeListener(listener: SharedPreferences.OnSharedPreferenceChangeListener?) = Unit
}

private class MemoryEditor(
    private val values: MutableMap<String, Any?>,
) : SharedPreferences.Editor {
    private val updates = mutableMapOf<String, Any?>()
    private val removals = mutableSetOf<String>()
    private var clearAll = false

    override fun putString(key: String?, value: String?): SharedPreferences.Editor = update(key, value)
    override fun putStringSet(key: String?, values: MutableSet<String>?): SharedPreferences.Editor = update(key, values)
    override fun putInt(key: String?, value: Int): SharedPreferences.Editor = update(key, value)
    override fun putLong(key: String?, value: Long): SharedPreferences.Editor = update(key, value)
    override fun putFloat(key: String?, value: Float): SharedPreferences.Editor = update(key, value)
    override fun putBoolean(key: String?, value: Boolean): SharedPreferences.Editor = update(key, value)
    override fun remove(key: String?): SharedPreferences.Editor = apply { if (key != null) removals += key }
    override fun clear(): SharedPreferences.Editor = apply { clearAll = true }
    override fun commit(): Boolean { applyChanges(); return true }
    override fun apply() = applyChanges()

    private fun update(key: String?, value: Any?): SharedPreferences.Editor = apply {
        if (key != null) updates[key] = value
    }

    private fun applyChanges() {
        if (clearAll) values.clear()
        removals.forEach(values::remove)
        updates.forEach { (key, value) -> if (value == null) values.remove(key) else values[key] = value }
    }
}
