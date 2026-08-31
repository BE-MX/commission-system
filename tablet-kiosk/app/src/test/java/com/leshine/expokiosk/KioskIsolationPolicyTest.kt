package com.leshine.expokiosk

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class KioskIsolationPolicyTest {
    private val kiosk = "https://154.8.205.162/expo/kiosk"
    private val origin = "https://154.8.205.162"

    @Test
    fun `configured kiosk URL is a single strict HTTPS endpoint`() {
        val endpoint = KioskUrlPolicy.requireEndpoint(kiosk)

        assertEquals(kiosk, endpoint.kioskUrl)
        assertEquals(origin, endpoint.origin)
    }

    @Test
    fun `configured kiosk URL rejects every runtime source widening`() {
        for (invalid in listOf(
            "",
            "   ",
            "http://154.8.205.162/expo/kiosk",
            "https://user@154.8.205.162/expo/kiosk",
            "https://154.8.205.162/expo/kiosk?station=a",
            "https://154.8.205.162/expo/kiosk#result",
            "https://154.8.205.162/expo/kiosk/",
            "https://154.8.205.162/login",
            "https://154.8.205.162/dashboard",
            " https://154.8.205.162/expo/kiosk",
        )) {
            assertThrows("invalid URL $invalid") { KioskUrlPolicy.requireEndpoint(invalid) }
        }
    }

    @Test
    fun `web camera permission is limited to the fixed kiosk main frame`() {
        assertTrue(
            KioskWebPermissionPolicy.allow(
                fixedOrigin = origin,
                requestOrigin = origin,
                currentMainFrameUrl = "$kiosk?station=a#capture",
                resources = arrayOf(KioskWebPermissionPolicy.VIDEO_CAPTURE),
            ),
        )

        for (request in listOf(
            PermissionCase("https://evil.example", kiosk, arrayOf(KioskWebPermissionPolicy.VIDEO_CAPTURE)),
            PermissionCase(origin, "https://154.8.205.162/login?redirect=%2Fexpo%2Fkiosk", arrayOf(KioskWebPermissionPolicy.VIDEO_CAPTURE)),
            PermissionCase(origin, "https://154.8.205.162/dashboard", arrayOf(KioskWebPermissionPolicy.VIDEO_CAPTURE)),
            PermissionCase(origin, kiosk, arrayOf(KioskWebPermissionPolicy.AUDIO_CAPTURE)),
            PermissionCase(origin, kiosk, arrayOf(KioskWebPermissionPolicy.VIDEO_CAPTURE, KioskWebPermissionPolicy.AUDIO_CAPTURE)),
            PermissionCase(origin, kiosk, emptyArray()),
        )) {
            assertFalse(
                KioskWebPermissionPolicy.allow(
                    fixedOrigin = origin,
                    requestOrigin = request.origin,
                    currentMainFrameUrl = request.mainFrame,
                    resources = request.resources,
                ),
            )
        }
    }

    @Test
    fun `lock task packages contain only self and the fixed valid printer`() {
        assertEquals(
            listOf("com.leshine.expokiosk", "com.hannto.jiyin"),
            KioskExternalPackagePolicy.lockTaskPackages(
                selfPackage = "com.leshine.expokiosk",
                printerPackage = "com.hannto.jiyin",
            ),
        )
        assertEquals(
            listOf("com.leshine.expokiosk"),
            KioskExternalPackagePolicy.lockTaskPackages("com.leshine.expokiosk", ""),
        )
        for (invalid in listOf(" com.hannto.jiyin", "com.hannto.jiyin ", "bad/package", "-bad.pkg", "com..bad")) {
            assertEquals(
                listOf("com.leshine.expokiosk"),
                KioskExternalPackagePolicy.lockTaskPackages("com.leshine.expokiosk", invalid),
            )
        }
    }

    private fun assertThrows(message: String, block: () -> Unit) {
        try {
            block()
            throw AssertionError("Expected rejection for $message")
        } catch (_: IllegalArgumentException) {
            // Expected.
        }
    }

    private data class PermissionCase(
        val origin: String,
        val mainFrame: String,
        val resources: Array<String>,
    )
}
