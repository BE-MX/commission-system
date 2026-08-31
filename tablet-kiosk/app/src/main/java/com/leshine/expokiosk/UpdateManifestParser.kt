package com.leshine.expokiosk

import org.json.JSONObject

object UpdateManifestParser {
    private val allowedKeys = setOf("version_code", "version_name", "apk_size", "sha256")
    private val sha256Pattern = Regex("^[0-9a-f]{64}$")

    fun parse(raw: String): Result<UpdateManifest> = runCatching {
        val json = JSONObject(raw)
        require(json.keys().asSequence().toSet() == allowedKeys) {
            "Manifest fields do not match the required schema"
        }

        val versionCode = json.strictLong("version_code")
        val versionName = json.get("version_name") as? String
            ?: throw IllegalArgumentException("version_name must be a string")
        val apkSize = json.strictLong("apk_size")
        val sha256 = json.get("sha256") as? String
            ?: throw IllegalArgumentException("sha256 must be a string")

        require(versionCode > 0) { "version_code must be positive" }
        require(versionName.isNotBlank()) { "version_name must not be blank" }
        require(apkSize in 1..UpdatePolicy.MAX_APK_BYTES) { "apk_size is outside the allowed range" }
        require(sha256Pattern.matches(sha256)) { "sha256 must be 64 lowercase hexadecimal characters" }

        UpdateManifest(versionCode, versionName, apkSize, sha256)
    }

    private fun JSONObject.strictLong(key: String): Long = when (val value = get(key)) {
        is Byte, is Short, is Int, is Long -> (value as Number).toLong()
        else -> throw IllegalArgumentException("$key must be an integer")
    }
}
