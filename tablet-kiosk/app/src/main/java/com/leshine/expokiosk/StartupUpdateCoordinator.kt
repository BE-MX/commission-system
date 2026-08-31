package com.leshine.expokiosk

internal fun interface StartupUpdateRun {
    fun run(onState: (UpdateState) -> Unit)
}

/** Process-scoped, thread-safe coordinator for exactly one startup update attempt. */
internal class StartupUpdateCoordinator(
    private val diagnostics: (Exception) -> Unit = {},
) {
    private val lock = Any()
    private val state = UpdateSessionState()
    private var attempted = false
    private var runner: StartupUpdateRun? = null
    private var observer: ((UpdateState) -> Unit)? = null

    fun attach(newObserver: (UpdateState) -> Unit): UpdateState? = synchronized(lock) {
        observer = newObserver
        state.current()
    }

    fun detach(currentObserver: (UpdateState) -> Unit) {
        synchronized(lock) {
            if (observer === currentObserver) observer = null
        }
    }

    fun start(
        execute: ((() -> Unit) -> Unit),
        createRunner: () -> StartupUpdateRun,
    ): Boolean {
        val shouldStart = synchronized(lock) {
            if (attempted || state.current().isReleaseTerminal()) false else {
                attempted = true
                true
            }
        }
        if (!shouldStart) return false

        try {
            execute {
                val mayCreate = synchronized(lock) {
                    attempted && !state.current().isReleaseTerminal()
                }
                if (!mayCreate) return@execute
                try {
                    val created = createRunner()
                    val mayRun = synchronized(lock) {
                        if (state.current().isReleaseTerminal()) {
                            false
                        } else {
                            runner = created
                            true
                        }
                    }
                    if (mayRun) created.run(::publish)
                } catch (exception: Exception) {
                    report(exception)
                    publish(UpdateState.Failed(SAFE_FAILURE_MESSAGE))
                }
            }
        } catch (exception: Exception) {
            report(exception)
            publish(UpdateState.Failed(SAFE_FAILURE_MESSAGE))
            return false
        }
        return true
    }

    fun publish(next: UpdateState) {
        synchronized(lock) {
            val publishedState = state.transition(next)
            observer?.invoke(publishedState)
        }
    }

    fun failInstall() {
        synchronized(lock) { attempted = true }
        publish(UpdateState.Failed(SAFE_FAILURE_MESSAGE))
    }

    fun currentState(): UpdateState? = state.current()

    fun isReleased(): Boolean = synchronized(lock) { state.current().isReleaseTerminal() }

    private fun report(exception: Exception) {
        try {
            diagnostics(exception)
        } catch (_: Exception) {
            // Diagnostics must never change the update lifecycle.
        }
    }

    private fun UpdateState?.isReleaseTerminal(): Boolean =
        this == UpdateState.NoUpdate || this is UpdateState.Failed

    companion object {
        const val SAFE_FAILURE_MESSAGE = "Update runtime unavailable"
    }
}
