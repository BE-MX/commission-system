package com.leshine.expokiosk

import android.content.pm.PackageInstaller
import java.io.ByteArrayInputStream
import java.io.InputStream
import java.nio.file.Files
import java.security.MessageDigest
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AndroidUpdateRuntimeTest {
    @Test
    fun `accepts only HTTP 200`() {
        UpdateRuntimePolicy.requireSuccessfulHttpStatus(200)

        for (status in listOf(199, 201, 400, 500) + (300..399)) {
            assertThrows("status $status") {
                UpdateRuntimePolicy.requireSuccessfulHttpStatus(status)
            }
        }
    }

    @Test
    fun `session cleanup reports ordinary exceptions`() {
        val failure = IllegalStateException("cleanup failed")
        val reported = mutableListOf<Exception>()

        abandonInstallSession(
            sessionId = 42,
            abandon = { throw failure },
            onException = reported::add,
        )

        assertEquals(listOf(failure), reported)
    }

    @Test
    fun `session cleanup does not swallow fatal errors`() {
        val fatal = AssertionError("fatal")

        try {
            abandonInstallSession(
                sessionId = 42,
                abandon = { throw fatal },
                onException = {},
            )
            throw AssertionError("Expected the fatal error to propagate")
        } catch (error: AssertionError) {
            assertTrue(error === fatal)
        }
    }

    @Test
    fun `streams an APK to the engine target with exact size hash and progress`() {
        val payload = ByteArray(70_000) { (it % 251).toByte() }
        val target = Files.createTempFile("runtime-download-", ".apk").toFile()
        target.deleteOnExit()
        val progress = mutableListOf<Int>()

        val artifact = streamApkToTarget(
            input = ByteArrayInputStream(payload),
            target = target,
            expectedSize = payload.size.toLong(),
            hardLimit = UpdatePolicy.MAX_APK_BYTES,
            onProgress = progress::add,
        )

        assertEquals(target, artifact.file)
        assertEquals(payload.size.toLong(), artifact.size)
        assertEquals(
            MessageDigest.getInstance("SHA-256")
                .digest(payload)
                .joinToString("") { "%02x".format(it) },
            artifact.sha256,
        )
        assertTrue(payload.contentEquals(target.readBytes()))
        assertTrue(progress.isNotEmpty())
        assertEquals(100, progress.last())
        assertTrue(progress.all { it in 0..100 })
        assertEquals(progress.sorted(), progress)
    }

    @Test
    fun `stops streaming immediately when bytes exceed the manifest size`() {
        val target = Files.createTempFile("runtime-overflow-", ".apk").toFile()
        target.deleteOnExit()

        assertThrows("manifest size") {
            streamApkToTarget(
                input = ByteArrayInputStream(ByteArray(33_000)),
                target = target,
                expectedSize = 32_999,
                hardLimit = UpdatePolicy.MAX_APK_BYTES,
                onProgress = {},
            )
        }

        assertTrue(target.length() <= 32_999)
    }

    @Test
    fun `rejects a truncated APK after streaming`() {
        val target = Files.createTempFile("runtime-short-", ".apk").toFile()
        target.deleteOnExit()

        assertThrows("manifest size") {
            streamApkToTarget(
                input = ByteArrayInputStream(ByteArray(3)),
                target = target,
                expectedSize = 4,
                hardLimit = UpdatePolicy.MAX_APK_BYTES,
                onProgress = {},
            )
        }
    }

    @Test
    fun `rejects invalid download bounds before opening the stream`() {
        val target = Files.createTempFile("runtime-bounds-", ".apk").toFile()
        target.deleteOnExit()

        for (size in listOf(0L, UpdatePolicy.MAX_APK_BYTES + 1)) {
            assertThrows("size $size") {
                streamApkToTarget(
                    input = ByteArrayInputStream(byteArrayOf(1)),
                    target = target,
                    expectedSize = size,
                    hardLimit = UpdatePolicy.MAX_APK_BYTES,
                    onProgress = {},
                )
            }
        }
    }

    @Test
    fun `progress is clamped to a stable percentage`() {
        assertEquals(0, UpdateRuntimePolicy.downloadProgress(0, 100))
        assertEquals(50, UpdateRuntimePolicy.downloadProgress(50, 100))
        assertEquals(100, UpdateRuntimePolicy.downloadProgress(101, 100))
        assertEquals(0, UpdateRuntimePolicy.downloadProgress(-1, 100))
        assertEquals(0, UpdateRuntimePolicy.downloadProgress(1, 0))
    }

    @Test
    fun `signer fingerprints are lowercase SHA-256`() {
        assertEquals(
            "039058c6f2c0cb492c533b0a4d14ef77cc0f78abccced5287d84a1a2011cfb81",
            UpdateRuntimePolicy.signerFingerprint(byteArrayOf(1, 2, 3)),
        )
    }

    @Test
    fun `silent install is requested only for a device owner on Android 12 or newer`() {
        assertEquals(
            InstallUserActionPolicy.SILENT_ALLOWED,
            UpdateRuntimePolicy.installUserActionPolicy(deviceOwner = true, sdkInt = 31),
        )
        assertEquals(
            InstallUserActionPolicy.SYSTEM_CONFIRMATION,
            UpdateRuntimePolicy.installUserActionPolicy(deviceOwner = false, sdkInt = 31),
        )
        assertEquals(
            InstallUserActionPolicy.SYSTEM_CONFIRMATION,
            UpdateRuntimePolicy.installUserActionPolicy(deviceOwner = true, sdkInt = 30),
        )
    }

    @Test
    fun `maps package installer statuses to receiver actions`() {
        assertEquals(
            InstallStatusDecision.AWAIT_USER,
            UpdateRuntimePolicy.installStatusDecision(PackageInstaller.STATUS_PENDING_USER_ACTION),
        )
        assertEquals(
            InstallStatusDecision.SUCCESS,
            UpdateRuntimePolicy.installStatusDecision(PackageInstaller.STATUS_SUCCESS),
        )
        assertEquals(
            InstallStatusDecision.FAILURE,
            UpdateRuntimePolicy.installStatusDecision(PackageInstaller.STATUS_FAILURE_INVALID),
        )
    }

    @Test
    fun `total deadline closes the active stream and disconnects`() {
        val scheduler = FakeDeadlineScheduler()
        val stream = TrackingInputStream()
        var disconnects = 0
        val guard = UpdateDeadlineGuard(
            scheduler = scheduler,
            timeoutMillis = 10_000,
            disconnect = { disconnects += 1 },
        )
        guard.attach(stream)

        scheduler.trigger()

        assertTrue(stream.closed)
        assertEquals(1, disconnects)
        assertFalse(scheduler.cancelled)
    }

    @Test
    fun `normal deadline completion cancels once and is idempotent`() {
        val scheduler = FakeDeadlineScheduler()
        var disconnects = 0
        val guard = UpdateDeadlineGuard(
            scheduler = scheduler,
            timeoutMillis = 120_000,
            disconnect = { disconnects += 1 },
        )

        guard.close()
        guard.close()
        scheduler.trigger()

        assertTrue(scheduler.cancelled)
        assertEquals(0, disconnects)
    }

    @Test
    fun `deadline does not swallow fatal close errors`() {
        val scheduler = FakeDeadlineScheduler()
        val fatal = AssertionError("fatal")
        val guard = UpdateDeadlineGuard(
            scheduler = scheduler,
            timeoutMillis = 10_000,
            disconnect = {},
        )
        guard.attach(object : InputStream() {
            override fun read(): Int = -1
            override fun close() { throw fatal }
        })

        try {
            scheduler.trigger()
            throw AssertionError("Expected fatal error")
        } catch (error: AssertionError) {
            assertSame(fatal, error)
        }
    }

    @Test
    fun `active install session rejects stale wrong and replayed callbacks`() {
        val storage = MemoryInstallSessionStorage()
        val tokens = ArrayDeque(listOf("token-a", "token-b"))
        val gate = ActiveInstallSessionGate(storage) { tokens.removeFirst() }
        val sessionA = gate.issue(10)
        val sessionB = gate.issue(11)

        assertEquals(null, gate.accept(PackageInstaller.STATUS_SUCCESS, sessionA.sessionId, sessionA.token))
        assertEquals(null, gate.accept(PackageInstaller.STATUS_SUCCESS, sessionB.sessionId, "wrong"))
        assertEquals(
            InstallStatusDecision.AWAIT_USER,
            gate.accept(PackageInstaller.STATUS_PENDING_USER_ACTION, sessionB.sessionId, sessionB.token),
        )
        assertTrue(gate.matches(sessionB.sessionId, sessionB.token))
        assertEquals(
            InstallStatusDecision.FAILURE,
            gate.accept(PackageInstaller.STATUS_FAILURE_INVALID, sessionB.sessionId, sessionB.token),
        )
        assertEquals(null, gate.accept(PackageInstaller.STATUS_FAILURE_INVALID, sessionB.sessionId, sessionB.token))

        val sessionC = gate.issue(12)
        assertEquals(
            InstallStatusDecision.SUCCESS,
            gate.accept(PackageInstaller.STATUS_SUCCESS, sessionC.sessionId, sessionC.token),
        )
        assertFalse(gate.matches(sessionC.sessionId, sessionC.token))
    }

    @Test
    fun `startup cleanup invalidates marker and abandons only this app sessions`() {
        val events = mutableListOf<String>()
        val storage = MemoryInstallSessionStorage(onClear = { events += "invalidate" })
        val gate = ActiveInstallSessionGate(storage) { "token" }
        gate.issue(1)
        val abandoned = mutableListOf<Int>()

        cleanupStaleInstallSessions(
            activeSession = gate,
            sessions = {
                events += "enumerate"
                listOf(
                    InstallSessionRecord(1, "com.leshine.expokiosk"),
                    InstallSessionRecord(2, "other.app"),
                    InstallSessionRecord(3, "com.leshine.expokiosk"),
                )
            },
            ownPackage = "com.leshine.expokiosk",
            abandon = abandoned::add,
        )

        assertFalse(gate.matches(1, "token"))
        assertEquals(listOf("invalidate", "enumerate"), events)
        assertEquals(listOf(1, 3), abandoned)
    }

    @Test
    fun `cleanup exception prevents a replacement runner while fatal errors propagate`() {
        var runnerCreated = false
        val ordinary = IllegalStateException("cleanup failed")
        try {
            prepareUpdateRunner(
                cleanup = { throw ordinary },
                createRunner = { runnerCreated = true; "runner" },
            )
            throw AssertionError("Expected cleanup exception")
        } catch (error: IllegalStateException) {
            assertSame(ordinary, error)
        }
        assertFalse(runnerCreated)

        val fatal = AssertionError("fatal")
        try {
            prepareUpdateRunner(cleanup = { throw fatal }, createRunner = { "runner" })
            throw AssertionError("Expected fatal error")
        } catch (error: AssertionError) {
            assertSame(fatal, error)
        }
    }

    private class FakeDeadlineScheduler : UpdateDeadlineScheduler {
        private var task: (() -> Unit)? = null
        var cancelled = false

        override fun schedule(delayMillis: Long, task: () -> Unit): DeadlineCancellation {
            this.task = task
            return DeadlineCancellation { cancelled = true }
        }

        fun trigger() {
            if (!cancelled) task?.invoke()
        }
    }

    private class TrackingInputStream : InputStream() {
        var closed = false
        override fun read(): Int = -1
        override fun close() { closed = true }
    }

    private class MemoryInstallSessionStorage(
        private val onClear: () -> Unit = {},
    ) : ActiveInstallSessionStorage {
        private var marker: ActiveInstallSessionMarker? = null
        override fun read(): ActiveInstallSessionMarker? = marker
        override fun write(marker: ActiveInstallSessionMarker): Boolean {
            this.marker = marker
            return true
        }
        override fun clear(): Boolean {
            onClear()
            marker = null
            return true
        }
    }

    private fun assertThrows(message: String, block: () -> Unit) {
        try {
            block()
            throw AssertionError("Expected IllegalArgumentException for $message")
        } catch (_: IllegalArgumentException) {
            // Expected.
        }
    }
}
