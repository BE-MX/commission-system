package com.leshine.expokiosk

import android.util.Log

/** Process-only holder shared by the activity and install status receiver. */
internal object StartupUpdateProcess {
    val coordinator = StartupUpdateCoordinator { exception ->
        Log.w("ExpoKioskUpdate", "Update startup failed type=${exception.javaClass.simpleName}")
    }
}
