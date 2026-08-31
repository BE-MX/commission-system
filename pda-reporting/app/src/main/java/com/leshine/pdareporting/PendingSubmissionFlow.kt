package com.leshine.pdareporting

sealed interface PendingOutcomes<out T> {
    data object None : PendingOutcomes<Nothing>
    data class Ready<T>(val value: T) : PendingOutcomes<T>
    data class Corrupt(val serialized: String) : PendingOutcomes<Nothing>
}

object PendingSubmissionFlow {
    fun <T> parseOutcomes(serialized: String?, decode: (String) -> T): PendingOutcomes<T> {
        if (serialized == null) return PendingOutcomes.None
        return runCatching { PendingOutcomes.Ready(decode(serialized)) }
            .getOrElse { PendingOutcomes.Corrupt(serialized) }
    }
}
