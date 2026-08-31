package com.leshine.expokiosk

import android.content.Context
import android.content.SharedPreferences
import android.content.pm.PackageInstaller
import java.security.SecureRandom
import java.util.Base64

internal data class ActiveInstallSessionMarker(
    val sessionId: Int,
    val token: String,
)

internal interface ActiveInstallSessionStorage {
    fun read(): ActiveInstallSessionMarker?
    fun write(marker: ActiveInstallSessionMarker): Boolean
    fun clear(): Boolean
}

private object ActiveInstallSessionLock

internal class ActiveInstallSessionGate(
    private val storage: ActiveInstallSessionStorage,
    private val tokenFactory: () -> String = ::newInstallSessionToken,
    private val lock: Any = ActiveInstallSessionLock,
) {
    fun issue(sessionId: Int): ActiveInstallSessionMarker = synchronized(lock) {
        require(sessionId >= 0) { "Install session id is invalid" }
        val marker = ActiveInstallSessionMarker(sessionId, tokenFactory())
        require(marker.token.isNotBlank()) { "Install session token is invalid" }
        check(storage.write(marker)) { "Install session marker could not be persisted" }
        marker
    }

    fun matches(sessionId: Int, token: String?): Boolean = synchronized(lock) {
        token != null && storage.read() == ActiveInstallSessionMarker(sessionId, token)
    }

    fun consume(
        sessionId: Int,
        token: String?,
        onConsumed: () -> Unit = {},
    ): Boolean = synchronized(lock) {
        if (token == null || storage.read() != ActiveInstallSessionMarker(sessionId, token)) {
            return@synchronized false
        }
        if (!storage.clear()) return@synchronized false
        onConsumed()
        true
    }

    fun beginStartup(): Boolean = synchronized(lock) {
        if (storage.read() == null) return@synchronized false
        check(storage.clear()) { "Install session marker could not be invalidated" }
        true
    }

    fun accept(
        status: Int,
        sessionId: Int,
        token: String?,
        onFailureAccepted: () -> Unit = {},
    ): InstallStatusDecision? =
        when (val decision = UpdateRuntimePolicy.installStatusDecision(status)) {
            InstallStatusDecision.AWAIT_USER -> decision.takeIf { matches(sessionId, token) }
            InstallStatusDecision.SUCCESS -> decision.takeIf { consume(sessionId, token) }
            InstallStatusDecision.FAILURE -> decision.takeIf {
                consume(sessionId, token, onFailureAccepted)
            }
        }
}

internal class SharedPreferencesInstallSessionStorage(context: Context) : ActiveInstallSessionStorage {
    private val preferences: SharedPreferences =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    override fun read(): ActiveInstallSessionMarker? {
        val sessionId = preferences.getInt(KEY_SESSION_ID, INVALID_SESSION_ID)
        val token = preferences.getString(KEY_TOKEN, null)
        return if (sessionId >= 0 && !token.isNullOrBlank()) {
            ActiveInstallSessionMarker(sessionId, token)
        } else {
            null
        }
    }

    override fun write(marker: ActiveInstallSessionMarker): Boolean = preferences.edit()
        .putInt(KEY_SESSION_ID, marker.sessionId)
        .putString(KEY_TOKEN, marker.token)
        .commit()

    override fun clear(): Boolean = preferences.edit()
        .remove(KEY_SESSION_ID)
        .remove(KEY_TOKEN)
        .commit()

    private companion object {
        const val PREFS = "active_install_session"
        const val KEY_SESSION_ID = "session_id"
        const val KEY_TOKEN = "callback_token"
        const val INVALID_SESSION_ID = -1
    }
}

internal fun activeInstallSession(context: Context): ActiveInstallSessionGate =
    ActiveInstallSessionGate(SharedPreferencesInstallSessionStorage(context.applicationContext))

private fun newInstallSessionToken(): String {
    val bytes = ByteArray(32)
    SecureRandom().nextBytes(bytes)
    return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)
}

internal data class InstallSessionRecord(
    val sessionId: Int,
    val appPackageName: String?,
)

internal fun cleanupOwnedInstallSessions(
    sessions: () -> List<InstallSessionRecord>,
    ownPackage: String,
    abandon: (Int) -> Unit,
) {
    sessions().asSequence()
        .filter { it.appPackageName == ownPackage }
        .forEach { abandon(it.sessionId) }
}

internal fun startUpdateAfterInstallRecovery(
    activeSession: ActiveInstallSessionGate,
    coordinator: StartupUpdateCoordinator,
    execute: ((() -> Unit) -> Unit),
    cleanupSessions: () -> Unit,
    createRunner: () -> StartupUpdateRun,
    diagnostics: (Exception) -> Unit = {},
): Boolean {
    if (coordinator.hasAttempted()) return !coordinator.isReleased()

    val hadStaleActive = try {
        activeSession.beginStartup()
    } catch (exception: Exception) {
        reportStartupRecoveryFailure(diagnostics, exception)
        coordinator.failInstall()
        return false
    }
    if (hadStaleActive) {
        coordinator.failInstall()
        try {
            execute {
                try {
                    cleanupSessions()
                } catch (exception: Exception) {
                    reportStartupRecoveryFailure(diagnostics, exception)
                }
            }
        } catch (exception: Exception) {
            reportStartupRecoveryFailure(diagnostics, exception)
        }
        return false
    }
    val started = coordinator.start(execute) {
        cleanupSessions()
        createRunner()
    }
    return started || !coordinator.isReleased()
}

private fun reportStartupRecoveryFailure(
    diagnostics: (Exception) -> Unit,
    exception: Exception,
) {
    try {
        diagnostics(exception)
    } catch (_: Exception) {
        // Diagnostics must not change fail-open recovery.
    }
}
