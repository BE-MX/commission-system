package com.leshine.expokiosk

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
        return StrictManifestReader(raw).readObject()
    }

    private fun Map<String, Any?>.strictLong(key: String): Long = when (val value = getValue(key)) {
        is Byte, is Short, is Int, is Long -> (value as Number).toLong()
        else -> throw IllegalArgumentException("$key must be an integer")
    }

    private class StrictManifestReader(private val raw: String) {
        private var index = 0

        fun readObject(): Map<String, Any?> {
            skipWhitespace()
            expect('{', "Manifest must be a JSON object")
            skipWhitespace()

            val values = linkedMapOf<String, Any?>()
            if (peek() == '}') {
                index++
            } else {
                while (true) {
                    val key = readString("Manifest keys must be double-quoted JSON strings")
                    require(key in allowedKeys) { "Manifest contains unknown key: $key" }
                    require(!values.containsKey(key)) { "Manifest contains duplicate key: $key" }

                    skipWhitespace()
                    expect(':', "Manifest key must be followed by a value")
                    skipWhitespace()
                    values[key] = when (key) {
                        "version_code", "apk_size" -> readLong(key)
                        "version_name", "sha256" -> readString("$key must be a double-quoted JSON string")
                        else -> error("unreachable")
                    }

                    skipWhitespace()
                    when (peek()) {
                        ',' -> {
                            index++
                            skipWhitespace()
                            require(peek() != '}') { "Manifest must not contain a trailing comma" }
                        }
                        '}' -> {
                            index++
                            break
                        }
                        else -> throw IllegalArgumentException(
                            "Manifest object is not terminated correctly",
                        )
                    }
                }
            }

            skipWhitespace()
            require(index == raw.length) { "Manifest contains trailing content" }
            return values
        }

        private fun readString(message: String): String {
            expect('"', message)
            val value = StringBuilder()
            while (index < raw.length) {
                when (val character = raw[index++]) {
                    '"' -> return value.toString()
                    '\\' -> value.append(readEscape())
                    else -> {
                        require(character >= ' ') { "JSON strings must not contain control characters" }
                        value.append(character)
                    }
                }
            }
            throw IllegalArgumentException("JSON string is not terminated")
        }

        private fun readEscape(): Char {
            require(index < raw.length) { "JSON escape is not terminated" }
            return when (val escaped = raw[index++]) {
                '"', '\\', '/' -> escaped
                'b' -> '\b'
                'f' -> '\u000c'
                'n' -> '\n'
                'r' -> '\r'
                't' -> '\t'
                'u' -> readUnicodeEscape()
                else -> throw IllegalArgumentException("Invalid JSON escape: \\$escaped")
            }
        }

        private fun readUnicodeEscape(): Char {
            require(index + 4 <= raw.length) { "Unicode escape must contain four hexadecimal digits" }
            val hex = raw.substring(index, index + 4)
            require(hex.all { it.isDigit() || it.lowercaseChar() in 'a'..'f' }) {
                "Unicode escape must contain four hexadecimal digits"
            }
            index += 4
            return hex.toInt(16).toChar()
        }

        private fun readLong(key: String): Long {
            val start = index
            if (peek() == '-') index++
            require(index < raw.length) { "$key must be a JSON integer" }

            when (raw[index]) {
                '0' -> index++
                in '1'..'9' -> {
                    index++
                    while (peek() in '0'..'9') index++
                }
                else -> throw IllegalArgumentException("$key must be a JSON integer")
            }

            return raw.substring(start, index).toLongOrNull()
                ?: throw IllegalArgumentException("$key is outside the Long range")
        }

        private fun skipWhitespace() {
            while (peek() == ' ' || peek() == '\t' || peek() == '\r' || peek() == '\n') index++
        }

        private fun expect(expected: Char, message: String) {
            require(peek() == expected) { message }
            index++
        }

        private fun peek(): Char? = raw.getOrNull(index)
    }
}
