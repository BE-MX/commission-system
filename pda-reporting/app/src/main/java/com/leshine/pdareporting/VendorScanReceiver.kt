package com.leshine.pdareporting

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class VendorScanReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context?, intent: Intent?) {
        if (intent?.action != ScanBroadcastContract.VENDOR_ACTION) return
        ScanBroadcastBridge.publish(intent.action.orEmpty(), ScanBroadcastContract.extract(intent.extras))
    }
}
