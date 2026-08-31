package com.leshine.expokiosk

import android.content.pm.PackageInstaller
import java.io.ByteArrayInputStream
import java.nio.file.Files
import java.security.MessageDigest
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

    private fun assertThrows(message: String, block: () -> Unit) {
        try {
            block()
            throw AssertionError("Expected IllegalArgumentException for $message")
        } catch (_: IllegalArgumentException) {
            // Expected.
        }
    }
}
