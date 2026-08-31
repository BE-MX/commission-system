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
            !intent.hasExtra(PackageInstaller.EXTRA_STATUS)
        ) {
            return
        }

        val status = intent.getIntExtra(
            PackageInstaller.EXTRA_STATUS,
            PackageInstaller.STATUS_FAILURE,
        )
        when (UpdateRuntimePolicy.installStatusDecision(status)) {
            InstallStatusDecision.AWAIT_USER -> awaitUser(context, intent)
            InstallStatusDecision.SUCCESS -> Unit
            InstallStatusDecision.FAILURE -> {
                Log.w(TAG, "Package installer failed status=$status")
                launchFailure(context, status)
            }
        }
    }

    private fun awaitUser(context: Context, statusIntent: Intent) {
        context.sendBroadcast(
            Intent(ACTION_UPDATE_AWAITING_USER).setPackage(context.packageName),
        )
        val confirmation = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            statusIntent.getParcelableExtra(Intent.EXTRA_INTENT, Intent::class.java)
        } else {
            @Suppress("DEPRECATION")
            statusIntent.getParcelableExtra(Intent.EXTRA_INTENT)
        }
        if (confirmation == null) {
            launchFailure(context, PackageInstaller.STATUS_FAILURE_INVALID)
            return
        }
        try {
            context.startActivity(confirmation.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        } catch (exception: Exception) {
            Log.w(TAG, "System install confirmation could not start type=${exception.javaClass.simpleName}")
            launchFailure(context, PackageInstaller.STATUS_FAILURE_BLOCKED)
        }
    }

    private fun launchFailure(context: Context, status: Int) {
        try {
            context.startActivity(
                Intent(context, MainActivity::class.java)
                    .setAction(ACTION_UPDATE_FAILED)
                    .putExtra(EXTRA_SAFE_STATUS_CODE, status)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            )
        } catch (exception: Exception) {
            Log.w(TAG, "Kiosk recovery could not start type=${exception.javaClass.simpleName}")
        }
    }

    companion object {
        private const val TAG = "ExpoKioskUpdate"
        const val ACTION_INSTALL_STATUS = "com.leshine.expokiosk.action.INSTALL_STATUS"
        const val ACTION_UPDATE_AWAITING_USER =
            "com.leshine.expokiosk.action.UPDATE_AWAITING_USER"
        const val ACTION_UPDATE_FAILED = "com.leshine.expokiosk.action.UPDATE_FAILED"
        const val EXTRA_SAFE_STATUS_CODE = "update_status_code"
    }
}
