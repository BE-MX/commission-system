package com.leshine.expokiosk

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class UpdatePolicyTest {
    private val digest = "a".repeat(64)
    private val signer = "b".repeat(64)
    private val manifest = UpdateManifest(10, "1.9", 4, digest)
    private val current = ApkIdentity(
        packageName = "com.leshine.expokiosk",
        versionCode = 9,
        versionName = "1.8",
        signers = setOf(signer),
    )
    private val candidate = ApkIdentity(
        packageName = "com.leshine.expokiosk",
        versionCode = 10,
        versionName = "1.9",
        signers = setOf(signer),
    )

    @Test
    fun `builds fixed HTTPS update URLs from the kiosk origin`() {
        val kioskUrl = "https://154.8.205.162/expo/kiosk?station=hall-a#result"

        assertEquals(
            "https://154.8.205.162/expo-app/latest.json",
            UpdatePolicy.manifestUrl(kioskUrl),
        )
        assertEquals(
            "https://154.8.205.162/expo-app/leshine-expo-kiosk.apk",
            UpdatePolicy.apkUrl(kioskUrl),
        )
    }

    @Test
    fun `preserves explicit HTTP and default ports`() {
        assertEquals(
            "http://10.0.0.8:8080/expo-app/latest.json",
            UpdatePolicy.manifestUrl("http://10.0.0.8:8080/expo/kiosk"),
        )
        assertEquals(
            "https://example.com:443/expo-app/leshine-expo-kiosk.apk",
            UpdatePolicy.apkUrl("https://example.com:443/expo/kiosk"),
        )
        assertEquals(
            "http://example.com/expo-app/latest.json",
            UpdatePolicy.manifestUrl("http://example.com/expo/kiosk"),
        )
    }

    @Test
    fun `formats IPv6 origins correctly`() {
        assertEquals(
            "https://[2001:db8::8]:8443/expo-app/latest.json",
            UpdatePolicy.manifestUrl("https://[2001:db8::8]:8443/expo/kiosk"),
        )
    }

    @Test
    fun `rejects non-http and hostless kiosk URLs`() {
        for (url in listOf(
            "ftp://154.8.205.162/expo/kiosk",
            "file:///expo/kiosk",
            "https:///expo/kiosk",
            "not a url",
        )) {
            assertThrowsIllegalArgument(url) { UpdatePolicy.manifestUrl(url) }
            assertThrowsIllegalArgument(url) { UpdatePolicy.apkUrl(url) }
        }
    }

    @Test
    fun `accepts a newer package with exact identity and integrity`() {
        assertEquals(
            DownloadedApkDecision.Accept,
            UpdatePolicy.validateDownloaded(manifest, current, candidate, 4, digest),
        )
    }

    @Test
    fun `rejects a manifest that is not newer`() {
        assertRejected(
            "newer",
            manifest.copy(versionCode = 9),
            candidate.copy(versionCode = 9),
        )
    }

    @Test
    fun `rejects candidate version mismatches`() {
        assertRejected("version", candidate = candidate.copy(versionCode = 11))
        assertRejected("version", candidate = candidate.copy(versionName = "1.9.1"))
    }

    @Test
    fun `rejects unexpected package identities`() {
        assertRejected("package", candidate = candidate.copy(packageName = "com.evil.kiosk"))
        assertRejected(
            "package",
            current = current.copy(packageName = "com.legacy.kiosk"),
            candidate = candidate.copy(packageName = "com.legacy.kiosk"),
        )
    }

    @Test
    fun `rejects empty and changed signer sets`() {
        assertRejected("signer", candidate = candidate.copy(signers = emptySet()))
        assertRejected("signer", candidate = candidate.copy(signers = setOf("c".repeat(64))))
    }

    @Test
    fun `rejects mismatched and out-of-range sizes`() {
        assertRejected("size", size = 5)
        assertRejected("size", manifest = manifest.copy(apkSize = 0), size = 0)
        assertRejected(
            "size",
            manifest = manifest.copy(apkSize = UpdatePolicy.MAX_APK_BYTES + 1),
            size = UpdatePolicy.MAX_APK_BYTES + 1,
        )
    }

    @Test
    fun `rejects a mismatched digest`() {
        assertRejected("sha256", sha256 = "d".repeat(64))
    }

    private fun assertRejected(
        reasonFragment: String,
        manifest: UpdateManifest = this.manifest,
        current: ApkIdentity = this.current,
        candidate: ApkIdentity = this.candidate,
        size: Long = manifest.apkSize,
        sha256: String = manifest.sha256,
    ) {
        val decision = UpdatePolicy.validateDownloaded(
            manifest,
            current,
            candidate,
            size,
            sha256,
        )
        assertTrue(decision is DownloadedApkDecision.Reject)
        assertTrue(
            decision.toString(),
            (decision as DownloadedApkDecision.Reject).reason.contains(reasonFragment, ignoreCase = true),
        )
    }

    private fun assertThrowsIllegalArgument(message: String, block: () -> Unit) {
        try {
            block()
            throw AssertionError("Expected IllegalArgumentException for $message")
        } catch (_: IllegalArgumentException) {
            // Expected.
        }
    }
}
