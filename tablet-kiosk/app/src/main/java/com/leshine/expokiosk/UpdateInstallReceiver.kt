package com.leshine.expokiosk

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.os.Build
import android.util.Log

class UpdateInstallReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action != ACTION_INSTALL_STATUS ||
            !intent.hasExtra(PackageInstaller.EXTRA_STATUS) ||
            !intent.hasExtra(PackageInstaller.EXTRA_SESSION_ID)
        ) {
            return
        }

        val status = intent.getIntExtra(
            PackageInstaller.EXTRA_STATUS,
            PackageInstaller.STATUS_FAILURE,
        )
        val sessionId = intent.getIntExtra(PackageInstaller.EXTRA_SESSION_ID, -1)
        val token = intent.getStringExtra(EXTRA_INSTALL_SESSION_TOKEN)
        val activeSession = activeInstallSession(context)
        val decision = try {
            activeSession.accept(
                status = status,
                sessionId = sessionId,
                token = token,
                onFailureAccepted = StartupUpdateProcess.coordinator::failInstall,
            )
        } catch (exception: Exception) {
            Log.w(TAG, "Install callback validation failed type=${exception.javaClass.simpleName}")
            null
        } ?: return
        when (decision) {
            InstallStatusDecision.AWAIT_USER -> awaitUser(
                context = context,
                statusIntent = intent,
                activeSession = activeSession,
                sessionId = sessionId,
                token = token,
            )
            InstallStatusDecision.SUCCESS -> Unit
            InstallStatusDecision.FAILURE -> {
                Log.w(TAG, "Package installer failed status=$status")
                launchFailure(context, status)
            }
        }
    }

    private fun awaitUser(
        context: Context,
        statusIntent: Intent,
        activeSession: ActiveInstallSessionGate,
        sessionId: Int,
        token: String?,
    ) {
        val confirmation = try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                statusIntent.getParcelableExtra(Intent.EXTRA_INTENT, Intent::class.java)
            } else {
                @Suppress("DEPRECATION")
                statusIntent.getParcelableExtra(Intent.EXTRA_INTENT)
            }
        } catch (exception: Exception) {
            Log.w(TAG, "System install confirmation was invalid type=${exception.javaClass.simpleName}")
            failMatchedPending(
                context,
                activeSession,
                sessionId,
                token,
                PackageInstaller.STATUS_FAILURE_INVALID,
            )
            return
        }
        if (confirmation == null) {
            failMatchedPending(
                context,
                activeSession,
                sessionId,
                token,
                PackageInstaller.STATUS_FAILURE_INVALID,
            )
            return
        }
        try {
            context.sendBroadcast(
                Intent(ACTION_UPDATE_AWAITING_USER).setPackage(context.packageName),
            )
            context.startActivity(confirmation.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        } catch (exception: Exception) {
            Log.w(TAG, "System install confirmation could not start type=${exception.javaClass.simpleName}")
            failMatchedPending(
                context,
                activeSession,
                sessionId,
                token,
                PackageInstaller.STATUS_FAILURE_BLOCKED,
            )
        }
    }

    private fun failMatchedPending(
        context: Context,
        activeSession: ActiveInstallSessionGate,
        sessionId: Int,
        token: String?,
        status: Int,
    ) {
        val consumed = try {
            activeSession.consume(
                sessionId = sessionId,
                token = token,
                onConsumed = StartupUpdateProcess.coordinator::failInstall,
            )
        } catch (exception: Exception) {
            Log.w(TAG, "Install callback cleanup failed type=${exception.javaClass.simpleName}")
            false
        }
        if (consumed) launchFailure(context, status)
    }

    private fun launchFailure(context: Context, status: Int) {
        InstallFailureRecovery(
            failProcess = { StartupUpdateProcess.coordinator.failInstall() },
            issueToken = { InstallFailureSignal.issue(context) },
            launch = { token ->
                context.startActivity(
                    Intent(context, MainActivity::class.java)
                        .setAction(ACTION_UPDATE_FAILED)
                        .putExtra(EXTRA_SAFE_STATUS_CODE, status)
                        .putExtra(EXTRA_FAILURE_TOKEN, token)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
                )
            },
            diagnostics = { stage, exception ->
                Log.w(TAG, "Kiosk recovery failed stage=$stage type=${exception.javaClass.simpleName}")
            },
        ).run()
    }

    companion object {
        private const val TAG = "ExpoKioskUpdate"
        const val ACTION_INSTALL_STATUS = "com.leshine.expokiosk.action.INSTALL_STATUS"
        const val ACTION_UPDATE_AWAITING_USER =
            "com.leshine.expokiosk.action.UPDATE_AWAITING_USER"
        const val ACTION_UPDATE_FAILED = "com.leshine.expokiosk.action.UPDATE_FAILED"
        const val EXTRA_SAFE_STATUS_CODE = "update_status_code"
        const val EXTRA_FAILURE_TOKEN = "install_failure_token"
        const val EXTRA_INSTALL_SESSION_TOKEN = "install_session_token"
    }
}
