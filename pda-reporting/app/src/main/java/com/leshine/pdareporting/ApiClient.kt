package com.leshine.pdareporting

import android.net.Uri
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.nio.charset.StandardCharsets

class ApiException(
    val statusCode: Int,
    override val message: String,
    val code: String? = null,
) : Exception(message)

class ApiClient(baseUrl: String) {
    var baseUrl: String = normalizeBaseUrl(baseUrl)
        private set
    var token: String = ""

    fun updateBaseUrl(value: String) {
        baseUrl = normalizeBaseUrl(value)
    }

    fun login(username: String, password: String): AuthSession {
        val json = requestJson(
            method = "POST",
            path = "/api/auth/login",
            body = JSONObject().put("username", username).put("password", password),
            authenticated = false,
        )
        val user = json.optJSONObject("user") ?: JSONObject()
        return AuthSession(
            token = json.getString("access_token"),
            userName = user.optString("real_name").ifBlank { user.optString("username", username) },
        )
    }

    fun verify(): String {
        val json = requestJson("GET", "/api/mini/auth/verify")
        val user = json.optJSONObject("user") ?: JSONObject()
        return user.optString("name", "")
    }

    fun scan(payload: ScanPayload): JSONObject {
        val route = if (payload.type == ScanPayload.Type.UNIT) "unit-scan" else "scan"
        val sign = Uri.encode(payload.sign)
        return requestJson("GET", "/api/mini/domestic/$route/${payload.id}?sign=$sign")
    }

    fun submit(
        scan: JSONObject,
        payload: ScanPayload,
        qty: Int,
        requestId: String,
        outcomes: JSONObject? = null,
    ): JSONObject {
        val body = JSONObject()
            .put("item_id", scan.getLong("item_id"))
            .put("progress_id", scan.getJSONObject("next_step").getLong("progress_id"))
            .put("qty", qty)
            .put("request_id", requestId)
        if (outcomes != null) body.put("outcomes", outcomes)
        if (scan.optString("report_mode") == "unit") {
            body.put("unit_id", scan.getLong("unit_id"))
            body.put("unit_sign", payload.sign)
        }
        return requestJson("POST", "/api/mini/domestic/scan/submit", body)
    }

    fun history(): Pair<List<HistoryRecord>, Pair<Int, Int>> {
        val json = requestJson("GET", "/api/mini/domestic/history")
        val rows = json.optJSONArray("records") ?: JSONArray()
        val result = ArrayList<HistoryRecord>(rows.length())
        for (i in 0 until rows.length()) {
            val row = rows.getJSONObject(i)
            val codesJson = row.optJSONArray("unit_codes") ?: JSONArray()
            val codes = (0 until codesJson.length()).map { codesJson.optString(it) }
            result += HistoryRecord(
                logId = row.getLong("log_id"),
                productName = row.optString("product_name", "-"),
                processName = row.optString("process_name", "-"),
                reportQty = row.optInt("report_qty"),
                orderLabel = listOf(row.optString("domestic_no"), row.optString("order_no"))
                    .filter { it.isNotBlank() && it != "null" }.joinToString(" · "),
                reportedAt = row.optString("reported_at").replace("T", " ").take(19),
                revoked = row.optInt("revoked") == 1 || row.optBoolean("revoked"),
                unitCodes = codes,
            )
        }
        return result to (json.optInt("today_count") to json.optInt("today_qty"))
    }

    fun revoke(logId: Long): JSONObject = requestJson(
        "POST",
        "/api/mini/domestic/scan/revoke",
        JSONObject().put("log_id", logId),
    )

    fun image(relativePath: String): ByteArray {
        val encoded = relativePath.split('/').joinToString("/") { Uri.encode(it) }
        return requestBytes("GET", "/api/mini/domestic/images/$encoded")
    }

    private fun requestJson(
        method: String,
        path: String,
        body: JSONObject? = null,
        authenticated: Boolean = true,
    ): JSONObject {
        val bytes = requestBytes(method, path, body?.toString()?.toByteArray(StandardCharsets.UTF_8), authenticated)
        return JSONObject(String(bytes, StandardCharsets.UTF_8))
    }

    private fun requestBytes(method: String, path: String): ByteArray =
        requestBytes(method, path, null, true)

    private fun requestBytes(
        method: String,
        path: String,
        body: ByteArray?,
        authenticated: Boolean,
    ): ByteArray {
        val connection = URL(baseUrl + path).openConnection() as HttpURLConnection
        try {
            connection.requestMethod = method
            connection.connectTimeout = 15_000
            connection.readTimeout = 30_000
            connection.setRequestProperty("Accept", "application/json")
            connection.setRequestProperty("User-Agent", "LeShine-PDA-Reporting/1.0")
            if (authenticated && token.isNotBlank()) {
                connection.setRequestProperty("Authorization", "Bearer $token")
            }
            if (body != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                connection.outputStream.use { it.write(body) }
            }

            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val response = stream?.use { input ->
                val output = ByteArrayOutputStream()
                input.copyTo(output)
                output.toByteArray()
            } ?: ByteArray(0)
            if (status !in 200..299) {
                throw ApiException(status, errorMessage(response, status), errorCode(response))
            }
            return response
        } finally {
            connection.disconnect()
        }
    }

    private fun errorMessage(bytes: ByteArray, status: Int): String {
        if (bytes.isEmpty()) return "请求失败（$status）"
        return try {
            val root = JSONObject(String(bytes, StandardCharsets.UTF_8))
            when (val detail = root.opt("detail")) {
                is JSONObject -> detail.optString("message", "请求失败（$status）")
                is String -> detail
                else -> root.optString("message", "请求失败（$status）")
            }
        } catch (_: Exception) {
            "请求失败（$status）"
        }
    }

    private fun errorCode(bytes: ByteArray): String? {
        if (bytes.isEmpty()) return null
        return runCatching {
            JSONObject(String(bytes, StandardCharsets.UTF_8))
                .optJSONObject("detail")
                ?.optString("code")
                ?.takeIf { it.isNotBlank() }
        }.getOrNull()
    }

    companion object {
        fun normalizeBaseUrl(input: String): String {
            val trimmed = input.trim().trimEnd('/')
            require(trimmed.startsWith("https://")) {
                "服务器地址必须以 https:// 开头"
            }
            return trimmed
        }
    }
}
