package com.leshine.expokiosk

import org.json.JSONObject
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
    fun `parses any field order and standard JSON string escapes`() {
        val raw = """
            {
              "sha256": "$digest",
              "apk_size": 4,
              "version_name": "1.9-\"stable\"-\u0021",
              "version_code": 10
            }
        """.trimIndent()

        assertEquals(
            UpdateManifest(10, "1.9-\"stable\"-!", 4, digest),
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
    fun `rejects duplicate manifest keys`() {
        val invalid = listOf(
            """{"version_code":10,"version_code":11,"version_name":"1.9","apk_size":4,"sha256":"$digest"}""",
            """{"version_code":10,"version_name":"1.9","apk_size":4,"apk_size":5,"sha256":"$digest"}""",
            """{"version_code":10,"version_name":"1.9","apk_size":4,"sha256":"$digest","sha256":"${"b".repeat(64)}"}""",
        )

        invalid.forEach { raw ->
            assertTrue(raw, UpdateManifestParser.parse(raw).isFailure)
        }
    }

    @Test
    fun `rejects content after the manifest object`() {
        val raw = manifest() + " true"

        assertTrue(raw, UpdateManifestParser.parse(raw).isFailure)
    }

    @Test
    fun `rejects single-quoted and bare JSON strings`() {
        val invalid = listOf(
            """{'version_code':10,"version_name":"1.9","apk_size":4,"sha256":"$digest"}""",
            """{"version_code":10,"version_name":'1.9',"apk_size":4,"sha256":"$digest"}""",
            """{"version_code":10,"version_name":"1.9","apk_size":4,"sha256":'$digest'}""",
            """{"version_code":10,"version_name":release-1.9,"apk_size":4,"sha256":"$digest"}""",
            """{"version_code":10,"version_name":"1.9","apk_size":4,"sha256":$digest}""",
        )

        invalid.forEach { raw ->
            assertTrue(raw, UpdateManifestParser.parse(raw).isFailure)
        }
    }

    @Test
    fun `rejects JavaScript comments and trailing commas`() {
        val invalid = listOf(
            """{/* comment */"version_code":10,"version_name":"1.9","apk_size":4,"sha256":"$digest"}""",
            """{"version_code":10,"version_name":"1.9","apk_size":4,"sha256":"$digest",}""",
        )

        invalid.forEach { raw ->
            assertTrue(raw, UpdateManifestParser.parse(raw).isFailure)
        }
    }

    @Test
    fun `rejects nonstandard and non-integer JSON numbers`() {
        val invalidTokens = listOf("+10", "0xA", "NaN", "Infinity", "10.0", "1e1", "01")
        val invalid = invalidTokens.flatMap { token ->
            listOf(
                manifestWithNumbers(versionCode = token),
                manifestWithNumbers(apkSize = token),
            )
        }

        invalid.forEach { raw ->
            assertTrue(raw, UpdateManifestParser.parse(raw).isFailure)
        }
    }

    @Test
    fun `rejects non-positive version codes`() {
        val invalid = listOf(
            manifest(versionCode = 0),
            manifest(versionCode = -1),
        )

        invalid.forEach { raw ->
            assertTrue(raw, UpdateManifestParser.parse(raw).isFailure)
        }
    }

    @Test
    fun `rejects blank and untrimmed version names`() {
        val invalid = listOf(
            manifest(versionName = ""),
            manifest(versionName = "   "),
            manifest(versionName = " 1.9 "),
        )

        invalid.forEach { raw ->
            assertTrue(raw, UpdateManifestParser.parse(raw).isFailure)
        }
    }

    @Test
    fun `rejects apk sizes outside the allowed range`() {
        val invalid = listOf(
            manifest(apkSize = 0),
            manifest(apkSize = -1),
            manifest(apkSize = 100L * 1024 * 1024 + 1),
        )

        invalid.forEach { raw ->
            assertTrue(raw, UpdateManifestParser.parse(raw).isFailure)
        }
    }

    @Test
    fun `rejects sha256 digests with incorrect lengths`() {
        val invalid = listOf(
            manifest(sha256 = "abc"),
            manifest(sha256 = "a".repeat(63)),
            manifest(sha256 = "a".repeat(65)),
        )

        invalid.forEach { raw ->
            assertTrue(raw, UpdateManifestParser.parse(raw).isFailure)
        }
    }

    @Test
    fun `rejects sha256 digests outside lowercase hexadecimal`() {
        val invalid = listOf(
            manifest(sha256 = "ABCDEF".repeat(11).take(64)),
            manifest(sha256 = "g".repeat(64)),
        )

        invalid.forEach { raw ->
            assertTrue(raw, UpdateManifestParser.parse(raw).isFailure)
        }
    }

    @Test
    fun `rejects fields with the wrong JSON types`() {
        val invalid = listOf(
            manifest(versionCode = "10"),
            manifest(versionName = 10),
            manifest(apkSize = "4"),
            manifest(sha256 = JSONObject.NULL),
        )

        invalid.forEach { raw ->
            assertTrue(raw, UpdateManifestParser.parse(raw).isFailure)
        }
    }

    private fun manifest(
        versionCode: Any = 10,
        versionName: Any = "1.9",
        apkSize: Any = 4,
        sha256: Any = digest,
    ): String = JSONObject()
        .put("version_code", versionCode)
        .put("version_name", versionName)
        .put("apk_size", apkSize)
        .put("sha256", sha256)
        .toString()

    private fun manifestWithNumbers(
        versionCode: String = "10",
        apkSize: String = "4",
    ): String =
        """{"version_code":$versionCode,"version_name":"1.9","apk_size":$apkSize,"sha256":"$digest"}"""
}
