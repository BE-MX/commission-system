package com.leshine.expokiosk

import org.json.JSONTokener

object UpdateManifestParser {
    private val allowedKeys = setOf("version_code", "version_name", "apk_size", "sha256")
    private val sha256Pattern = Regex("^[0-9a-f]{64}$")

    fun parse(raw: String): Result<UpdateManifest> = try {
        Result.success(parseOrThrow(raw))
    } catch (exception: Exception) {
        Result.failure(exception)
    }

    private fun parseOrThrow(raw: String): UpdateManifest {
        val values = parseObject(raw)
        require(values.keys == allowedKeys) { "Manifest fields do not match the required schema" }

        val versionCode = values.strictLong("version_code")
        val versionName = values["version_name"] as? String
            ?: throw IllegalArgumentException("version_name must be a string")
        val apkSize = values.strictLong("apk_size")
        val sha256 = values["sha256"] as? String
            ?: throw IllegalArgumentException("sha256 must be a string")

        require(versionCode > 0) { "version_code must be positive" }
        require(versionName.isNotBlank() && versionName == versionName.trim()) {
            "version_name must be non-blank and trimmed"
        }
        require(apkSize in 1..UpdatePolicy.MAX_APK_BYTES) { "apk_size is outside the allowed range" }
        require(sha256Pattern.matches(sha256)) { "sha256 must be 64 lowercase hexadecimal characters" }

        return UpdateManifest(versionCode, versionName, apkSize, sha256)
    }

    private fun parseObject(raw: String): Map<String, Any?> {
        val tokener = JSONTokener(raw)
        require(tokener.nextClean() == '{') { "Manifest must be a JSON object" }

        val values = linkedMapOf<String, Any?>()
        var next = tokener.nextClean()
        if (next != '}') {
            while (true) {
                require(next == '"') { "Manifest keys must be JSON strings" }
                val key = tokener.nextString('"')
                require(!values.containsKey(key)) { "Manifest contains duplicate key: $key" }
                require(tokener.nextClean() == ':') { "Manifest key must be followed by a value" }
                values[key] = tokener.nextValue()

                when (tokener.nextClean()) {
                    ',' -> next = tokener.nextClean()
                    '}' -> break
                    else -> throw IllegalArgumentException("Manifest object is not terminated correctly")
                }
            }
        }
        require(tokener.nextClean() == '\u0000') { "Manifest contains trailing content" }
        return values
    }

    private fun Map<String, Any?>.strictLong(key: String): Long = when (val value = getValue(key)) {
        is Byte, is Short, is Int, is Long -> (value as Number).toLong()
        else -> throw IllegalArgumentException("$key must be an integer")
    }
}
