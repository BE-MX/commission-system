package com.leshine.expokiosk

import java.io.InputStream
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledThreadPoolExecutor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

internal fun interface DeadlineCancellation {
    fun cancel()
}

internal fun interface UpdateDeadlineScheduler {
    fun schedule(delayMillis: Long, task: () -> Unit): DeadlineCancellation
}

internal object DaemonUpdateDeadlineScheduler : UpdateDeadlineScheduler {
    private val executor = (Executors.newScheduledThreadPool(1) { task ->
        Thread(task, "expo-update-deadline").apply { isDaemon = true }
    } as ScheduledThreadPoolExecutor).apply {
        removeOnCancelPolicy = true
        executeExistingDelayedTasksAfterShutdownPolicy = false
    }

    override fun schedule(delayMillis: Long, task: () -> Unit): DeadlineCancellation {
        val future = executor.schedule(task, delayMillis, TimeUnit.MILLISECONDS)
        return DeadlineCancellation { future.cancel(false) }
    }
}

/** Adds a monotonic wall-clock ceiling on top of connect/read idle timeouts. */
internal class UpdateDeadlineGuard(
    scheduler: UpdateDeadlineScheduler,
    timeoutMillis: Long,
    private val disconnect: () -> Unit,
    private val onException: (Exception) -> Unit = {},
) : AutoCloseable {
    private val completed = AtomicBoolean(false)
    private val cancellationConsumed = AtomicBoolean(false)
    private val input = AtomicReference<InputStream?>()
    private val cancellation: DeadlineCancellation

    init {
        require(timeoutMillis > 0) { "Update deadline must be positive" }
        cancellation = scheduler.schedule(timeoutMillis, ::expire)
    }

    fun attach(stream: InputStream) {
        if (!input.compareAndSet(null, stream)) {
            throw IllegalStateException("An update deadline already owns a stream")
        }
        if (completed.get() && input.compareAndSet(stream, null)) {
            stream.close()
        }
    }

    private fun expire() {
        if (!completed.compareAndSet(false, true)) return
        try {
            try {
                input.getAndSet(null)?.close()
            } catch (exception: Exception) {
                onException(exception)
            }
        } finally {
            disconnect()
        }
    }

    override fun close() {
        if (completed.compareAndSet(false, true)) input.set(null)
        if (cancellationConsumed.compareAndSet(false, true)) cancellation.cancel()
    }
}
