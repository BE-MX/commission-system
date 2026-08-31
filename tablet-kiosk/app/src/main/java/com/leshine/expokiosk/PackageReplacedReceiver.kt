package com.leshine.expokiosk

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

class PackageReplacedReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action != Intent.ACTION_MY_PACKAGE_REPLACED) return
        try {
            context.startActivity(
                Intent(context, MainActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            )
        } catch (exception: Exception) {
            Log.w(TAG, "Kiosk restart after update failed type=${exception.javaClass.simpleName}")
        }
    }

    companion object {
        private const val TAG = "ExpoKioskUpdate"
    }
}
