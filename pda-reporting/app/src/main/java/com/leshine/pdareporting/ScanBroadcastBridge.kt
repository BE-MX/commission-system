package com.leshine.pdareporting

internal object ScanBroadcastBridge {
    @Volatile
    private var listener: ((String, String?) -> Unit)? = null

    @Synchronized
    fun attach(value: (String, String?) -> Unit) {
        listener = value
    }

    @Synchronized
    fun detach(value: (String, String?) -> Unit) {
        if (listener === value) listener = null
    }

    fun publish(action: String, code: String?) {
        listener?.invoke(action, code)
    }
}
