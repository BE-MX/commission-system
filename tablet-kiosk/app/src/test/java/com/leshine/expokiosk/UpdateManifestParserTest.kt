package com.leshine.expokiosk

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class UpdateManifestParserTest {
    private val digest = "a".repeat(64)

    @Test
    fun `parses a valid update manifest`() {
        val raw = """
            {
              "version_code": 10,
              "version_name": "1.9",
              "apk_size": 4,
              "sha256": "$digest"
            }
        """.trimIndent()

        assertEquals(
            UpdateManifest(10, "1.9", 4, digest),
            UpdateManifestParser.parse(raw).getOrThrow(),
        )
    }

    @Test
    fun `rejects missing fields and unknown fields`() {
        val invalid = listOf(
            "{}",
            """{"version_code":10,"version_name":"1.9","apk_size":4}""",
            """{"version_code":10,"version_name":"1.9","apk_size":4,"sha256":"$digest","apk_url":"https://evil.example/app.apk"}""",
        )

        invalid.forEach { raw ->
            assertTrue(raw, UpdateManifestParser.parse(raw).isFailure)
        }
    }

    @Test
    fun `rejects invalid version fields`() {
        val invalid = listOf(
            manifest(versionCode = "0"),
            manifest(versionCode = "-1"),
            manifest(versionName = ""),
            manifest(versionName = "   "),
        )

        invalid.forEach { raw ->
            assertTrue(raw, UpdateManifestParser.parse(raw).isFailure)
        }
    }

    @Test
    fun `rejects apk sizes outside the allowed range`() {
        val invalid = listOf(
            manifest(apkSize = "0"),
            manifest(apkSize = "-1"),
            manifest(apkSize = (100L * 1024 * 1024 + 1).toString()),
        )

        invalid.forEach { raw ->
            assertTrue(raw, UpdateManifestParser.parse(raw).isFailure)
        }
    }

    @Test
    fun `rejects malformed sha256 digests`() {
        val invalid = listOf(
            manifest(sha256 = "a".repeat(63)),
            manifest(sha256 = "a".repeat(65)),
            manifest(sha256 = "A".repeat(64)),
            manifest(sha256 = "g".repeat(64)),
        )

        invalid.forEach { raw ->
            assertTrue(raw, UpdateManifestParser.parse(raw).isFailure)
        }
    }

    @Test
    fun `rejects fields with the wrong JSON types`() {
        val invalid = listOf(
            manifest(versionCode = "\"10\""),
            manifest(versionName = "10"),
            manifest(apkSize = "\"4\""),
            manifest(sha256 = "null"),
        )

        invalid.forEach { raw ->
            assertTrue(raw, UpdateManifestParser.parse(raw).isFailure)
        }
    }

    private fun manifest(
        versionCode: String = "10",
        versionName: String = "\"1.9\"",
        apkSize: String = "4",
        sha256: String = "\"$digest\"",
    ): String =
        """{"version_code":$versionCode,"version_name":$versionName,"apk_size":$apkSize,"sha256":$sha256}"""
}
