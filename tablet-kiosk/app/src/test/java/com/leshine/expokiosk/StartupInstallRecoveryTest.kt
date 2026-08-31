package com.leshine.expokiosk

import android.content.pm.PackageInstaller
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import kotlin.concurrent.thread
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class StartupInstallRecoveryTest {
    @Test
    fun `pending callback accepted first forces startup to skip replacement`() {
        val storage = BlockingInstallSessionStorage()
        val gate = ActiveInstallSessionGate(storage) { "token-a" }
        val session = gate.issue(10)
        storage.blockNextRead()
        val callback = AtomicReference<InstallStatusDecision?>()
        val started = AtomicReference<Boolean>()
        var creates = 0

        val callbackThread = thread {
            callback.set(gate.accept(PackageInstaller.STATUS_PENDING_USER_ACTION, 10, session.token))
        }
        storage.awaitRead()
        val startupThread = thread {
            started.set(startUpdateAfterInstallRecovery(
                activeSession = gate,
                coordinator = StartupUpdateCoordinator(),
                execute = ::runNow,
                cleanupSessions = {},
                createRunner = {
                    creates += 1
                    StartupUpdateRun {}
                },
            ))
        }
        storage.releaseRead()
        callbackThread.join()
        startupThread.join()

        assertEquals(InstallStatusDecision.AWAIT_USER, callback.get())
        assertFalse(started.get())
        assertEquals(0, creates)
    }

    @Test
    fun `startup claim first rejects old pending and failure callbacks`() {
        val storage = BlockingInstallSessionStorage()
        val gate = ActiveInstallSessionGate(storage) { "token-a" }
        val session = gate.issue(10)
        storage.blockNextClear()
        val started = AtomicReference<Boolean>()
        val pending = AtomicReference<InstallStatusDecision?>()

        val startupThread = thread {
            started.set(startUpdateAfterInstallRecovery(
                activeSession = gate,
                coordinator = StartupUpdateCoordinator(),
                execute = ::runNow,
                cleanupSessions = {},
                createRunner = { StartupUpdateRun {} },
            ))
        }
        storage.awaitClear()
        val callbackThread = thread {
            pending.set(gate.accept(PackageInstaller.STATUS_PENDING_USER_ACTION, 10, session.token))
        }
        storage.releaseClear()
        startupThread.join()
        callbackThread.join()

        assertFalse(started.get())
        assertNull(pending.get())
        assertNull(gate.accept(PackageInstaller.STATUS_FAILURE_INVALID, 10, session.token))
    }

    @Test
    fun `old failure consumption releases coordinator before startup can claim`() {
        val storage = BlockingInstallSessionStorage()
        val gate = ActiveInstallSessionGate(storage) { "token-a" }
        val session = gate.issue(10)
        val coordinator = StartupUpdateCoordinator()
        storage.blockNextClear()
        val failure = AtomicReference<InstallStatusDecision?>()
        val started = AtomicReference<Boolean>()
        var creates = 0

        val failureThread = thread {
            failure.set(gate.accept(
                status = PackageInstaller.STATUS_FAILURE_INVALID,
                sessionId = session.sessionId,
                token = session.token,
                onFailureAccepted = coordinator::failInstall,
            ))
        }
        storage.awaitClear()
        val startupThread = thread {
            started.set(startUpdateAfterInstallRecovery(
                activeSession = gate,
                coordinator = coordinator,
                execute = ::runNow,
                cleanupSessions = {},
                createRunner = {
                    creates += 1
                    StartupUpdateRun {}
                },
            ))
        }
        storage.releaseClear()
        failureThread.join()
        startupThread.join()

        assertEquals(InstallStatusDecision.FAILURE, failure.get())
        assertFalse(started.get())
        assertEquals(0, creates)
    }

    @Test
    fun `stale active session schedules cleanup but never creates replacement`() {
        val storage = BlockingInstallSessionStorage()
        val gate = ActiveInstallSessionGate(storage) { "token-a" }
        gate.issue(10)
        var cleanups = 0
        var creates = 0

        val started = startUpdateAfterInstallRecovery(
            activeSession = gate,
            coordinator = StartupUpdateCoordinator(),
            execute = ::runNow,
            cleanupSessions = { cleanups += 1 },
            createRunner = {
                creates += 1
                StartupUpdateRun {}
            },
        )

        assertFalse(started)
        assertEquals(1, cleanups)
        assertEquals(0, creates)
    }

    @Test
    fun `recreated activity keeps an existing startup attempt instead of releasing it`() {
        val coordinator = StartupUpdateCoordinator()
        var originalTask: (() -> Unit)? = null
        coordinator.start(execute = { originalTask = it }) { StartupUpdateRun {} }
        var cleanups = 0
        var creates = 0

        val remainsActive = startUpdateAfterInstallRecovery(
            activeSession = ActiveInstallSessionGate(BlockingInstallSessionStorage()),
            coordinator = coordinator,
            execute = ::runNow,
            cleanupSessions = { cleanups += 1 },
            createRunner = {
                creates += 1
                StartupUpdateRun {}
            },
        )

        assertTrue(remainsActive)
        assertEquals(0, cleanups)
        assertEquals(0, creates)
        assertTrue(originalTask != null)
        assertFalse(coordinator.currentState() is UpdateState.Failed)
    }

    @Test
    fun `startup recovery fails open on ordinary exceptions and propagates errors`() {
        val ordinaryCoordinator = StartupUpdateCoordinator()
        val ordinary = IllegalStateException("storage unavailable")
        val ordinaryStarted = startUpdateAfterInstallRecovery(
            activeSession = ActiveInstallSessionGate(ThrowingStorage(ordinary)),
            coordinator = ordinaryCoordinator,
            execute = ::runNow,
            cleanupSessions = {},
            createRunner = { StartupUpdateRun {} },
        )

        assertFalse(ordinaryStarted)
        assertTrue(ordinaryCoordinator.currentState() is UpdateState.Failed)

        val fatal = AssertionError("fatal")
        try {
            startUpdateAfterInstallRecovery(
                activeSession = ActiveInstallSessionGate(ThrowingStorage(fatal)),
                coordinator = StartupUpdateCoordinator(),
                execute = ::runNow,
                cleanupSessions = {},
                createRunner = { StartupUpdateRun {} },
            )
            fail("Expected fatal error")
        } catch (error: AssertionError) {
            assertSame(fatal, error)
        }
    }

    private class BlockingInstallSessionStorage : ActiveInstallSessionStorage {
        private var marker: ActiveInstallSessionMarker? = null
        private var readEntered: CountDownLatch? = null
        private var releaseRead: CountDownLatch? = null
        private var clearEntered: CountDownLatch? = null
        private var releaseClear: CountDownLatch? = null

        fun blockNextRead() {
            readEntered = CountDownLatch(1)
            releaseRead = CountDownLatch(1)
        }

        fun awaitRead() = check(readEntered!!.await(5, TimeUnit.SECONDS))
        fun releaseRead() = releaseRead!!.countDown()

        fun blockNextClear() {
            clearEntered = CountDownLatch(1)
            releaseClear = CountDownLatch(1)
        }

        fun awaitClear() = check(clearEntered!!.await(5, TimeUnit.SECONDS))
        fun releaseClear() = releaseClear!!.countDown()

        override fun read(): ActiveInstallSessionMarker? {
            readEntered?.countDown()
            releaseRead?.await(5, TimeUnit.SECONDS)
            readEntered = null
            releaseRead = null
            return marker
        }

        override fun write(marker: ActiveInstallSessionMarker): Boolean {
            this.marker = marker
            return true
        }

        override fun clear(): Boolean {
            clearEntered?.countDown()
            releaseClear?.await(5, TimeUnit.SECONDS)
            clearEntered = null
            releaseClear = null
            marker = null
            return true
        }
    }

    private class ThrowingStorage(private val throwable: Throwable) : ActiveInstallSessionStorage {
        override fun read(): ActiveInstallSessionMarker? = throw throwable
        override fun write(marker: ActiveInstallSessionMarker): Boolean = true
        override fun clear(): Boolean = true
    }

    private fun runNow(task: () -> Unit) = task()
}
