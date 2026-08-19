package com.leshine.pdareporting

data class ScanPayload(
    val type: Type,
    val id: Long,
    val sign: String,
    val raw: String,
) {
    enum class Type { ITEM, UNIT }
}

object ScanPayloadParser {
    private val unitPattern = Regex("^ARK-DU:(\\d+):([a-f0-9]+)$", RegexOption.IGNORE_CASE)
    private val itemPattern = Regex("^ARK-D:(\\d+):([a-f0-9]+)$", RegexOption.IGNORE_CASE)

    fun parse(input: String): ScanPayload? {
        val raw = input.trim().replace("\u0000", "")
        unitPattern.matchEntire(raw)?.let {
            val id = it.groupValues[1].toLongOrNull() ?: return null
            return ScanPayload(ScanPayload.Type.UNIT, id, it.groupValues[2].lowercase(), raw)
        }
        itemPattern.matchEntire(raw)?.let {
            val id = it.groupValues[1].toLongOrNull() ?: return null
            return ScanPayload(ScanPayload.Type.ITEM, id, it.groupValues[2].lowercase(), raw)
        }
        return null
    }
}

data class AuthSession(val token: String, val userName: String)

data class HistoryRecord(
    val logId: Long,
    val productName: String,
    val processName: String,
    val reportQty: Int,
    val orderLabel: String,
    val reportedAt: String,
    val revoked: Boolean,
    val unitCodes: List<String>,
)
