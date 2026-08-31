package com.leshine.expokiosk

import java.net.URI
import java.net.URLDecoder
import java.nio.charset.StandardCharsets

sealed interface NavigationDecision {
    data object Allow : NavigationDecision
    data class Redirect(val url: String) : NavigationDecision
}

object KioskNavigationPolicy {
    fun shouldBlockSubframe(isForMainFrame: Boolean?): Boolean = isForMainFrame != true

    fun decide(kioskUrl: String, requestedUrl: String?): NavigationDecision {
        val kiosk = parseHttpsUrl(kioskUrl) ?: return NavigationDecision.Redirect(kioskUrl)
        val requested = parseHttpsUrl(requestedUrl) ?: return NavigationDecision.Redirect(kioskUrl)
        if (!sameOrigin(kiosk, requested)) return NavigationDecision.Redirect(kioskUrl)

        val kioskPath = normalizePath(kiosk.path)
        return when (normalizePath(requested.path)) {
            kioskPath -> NavigationDecision.Allow
            "/login" -> {
                val redirect = queryValue(requested.rawQuery, "redirect")
                if (normalizePath(redirect) == kioskPath) {
                    NavigationDecision.Allow
                } else {
                    NavigationDecision.Redirect(boundedLoginUrl(kiosk, kioskPath))
                }
            }
            else -> NavigationDecision.Redirect(kioskUrl)
        }
    }

    private fun parseHttpsUrl(raw: String?): URI? = try {
        URI(raw?.trim().orEmpty()).takeIf {
            it.scheme.equals("https", true) &&
                !it.host.isNullOrBlank() &&
                it.rawUserInfo == null
        }
    } catch (_: Exception) {
        null
    }

    private fun normalizePath(raw: String?): String {
        val path = raw.orEmpty().trimEnd('/').lowercase()
        return path.ifEmpty { "/" }
    }

    private fun sameOrigin(first: URI, second: URI): Boolean =
        first.scheme.equals(second.scheme, true) &&
            first.host.equals(second.host, true) &&
            effectivePort(first) == effectivePort(second)

    private fun effectivePort(uri: URI): Int = when {
        uri.port >= 0 -> uri.port
        uri.scheme.equals("https", true) -> 443
        else -> 80
    }

    private fun queryValue(rawQuery: String?, key: String): String? = rawQuery
        ?.split('&')
        ?.asSequence()
        ?.map { it.split('=', limit = 2) }
        ?.firstOrNull { decode(it[0]) == key }
        ?.getOrNull(1)
        ?.let(::decode)

    private fun decode(value: String): String =
        URLDecoder.decode(value, StandardCharsets.UTF_8.name())

    private fun boundedLoginUrl(kiosk: URI, kioskPath: String): String {
        val origin = URI(kiosk.scheme.lowercase(), null, kiosk.host, kiosk.port, null, null, null)
        val encodedPath = kioskPath.replace("/", "%2F")
        return "$origin/login?redirect=$encodedPath"
    }
}
