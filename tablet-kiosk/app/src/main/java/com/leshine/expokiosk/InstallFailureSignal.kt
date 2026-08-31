package com.leshine.expokiosk

import android.content.Context
import java.security.MessageDigest
import java.util.UUID

internal interface OneTimeTokenStorage {
    fun read(): String?
    fun write(token: String): Boolean
    fun clear(): Boolean
}

internal class OneTimeTokenGate(
    private val storage: OneTimeTokenStorage,
    private val generateToken: () -> String = { UUID.randomUUID().toString() },
) {
    fun issue(): String {
        val token = generateToken()
        require(token.isNotBlank()) { "Failure token generator returned an empty value" }
        check(storage.write(token)) { "Failure token could not be persisted" }
        return token
    }

    fun consume(candidate: String?): Boolean {
        if (candidate.isNullOrBlank()) return false
        val expected = storage.read()?.takeIf(String::isNotBlank) ?: return false
        if (!MessageDigest.isEqual(expected.toByteArray(), candidate.toByteArray())) return false
        return storage.clear()
    }
}

/** Process-atomic access to the app-private, one-time install failure token. */
internal object InstallFailureSignal {
    private const val PREFS = "install_failure_signal"
    private const val KEY_TOKEN = "pending_token"
    private val lock = Any()

    fun issue(context: Context): String = synchronized(lock) {
        OneTimeTokenGate(SharedPreferencesTokenStorage(context.applicationContext)).issue()
    }

    fun consume(context: Context, candidate: String?): Boolean = synchronized(lock) {
        OneTimeTokenGate(SharedPreferencesTokenStorage(context.applicationContext)).consume(candidate)
    }

    private class SharedPreferencesTokenStorage(context: Context) : OneTimeTokenStorage {
        private val preferences = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

        override fun read(): String? = preferences.getString(KEY_TOKEN, null)

        override fun write(token: String): Boolean =
            preferences.edit().putString(KEY_TOKEN, token).commit()

        override fun clear(): Boolean = preferences.edit().remove(KEY_TOKEN).commit()
    }
}
