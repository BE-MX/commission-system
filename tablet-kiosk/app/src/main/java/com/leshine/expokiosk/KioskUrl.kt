package com.leshine.expokiosk

import android.content.Context
import java.net.URI

internal data class KioskEndpoint(
    val kioskUrl: String,
    val origin: String,
)

/** The compiled resource is the only kiosk source; invalid builds stop instead of widening access. */
internal object KioskUrlPolicy {
    private const val KIOSK_PATH = "/expo/kiosk"

    fun requireEndpoint(raw: String): KioskEndpoint {
        require(raw.isNotBlank() && raw == raw.trim()) { "The configured kiosk URL is invalid" }
        val uri = try {
            URI(raw)
        } catch (exception: Exception) {
            throw IllegalArgumentException("The configured kiosk URL is invalid", exception)
        }
        require(!uri.isOpaque) { "The configured kiosk URL is invalid" }
        require(uri.scheme.equals("https", ignoreCase = true)) { "The kiosk URL must use HTTPS" }
        require(!uri.host.isNullOrBlank()) { "The configured kiosk URL is invalid" }
        require(uri.rawUserInfo == null && uri.rawQuery == null && uri.rawFragment == null) {
            "The configured kiosk URL is invalid"
        }
        require(uri.rawPath == KIOSK_PATH) { "The kiosk URL path is fixed" }
        require(uri.port == -1 || uri.port in 1..65535) { "The configured kiosk URL port is invalid" }

        val origin = URI(
            uri.scheme.lowercase(),
            null,
            uri.host,
            uri.port,
            null,
            null,
            null,
        ).toASCIIString()
        return KioskEndpoint(kioskUrl = raw, origin = origin)
    }
}

object KioskUrl {
    fun origin(ctx: Context): String = endpoint(ctx).origin

    fun get(ctx: Context): String = endpoint(ctx).kioskUrl

    private fun endpoint(ctx: Context): KioskEndpoint =
        KioskUrlPolicy.requireEndpoint(ctx.getString(R.string.start_url))
}
