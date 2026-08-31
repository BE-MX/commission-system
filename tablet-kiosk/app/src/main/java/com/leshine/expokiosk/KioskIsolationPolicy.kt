package com.leshine.expokiosk

import java.net.URI

internal object KioskWebPermissionPolicy {
    const val VIDEO_CAPTURE = "android.webkit.resource.VIDEO_CAPTURE"
    const val AUDIO_CAPTURE = "android.webkit.resource.AUDIO_CAPTURE"
    private const val KIOSK_PATH = "/expo/kiosk"

    fun allow(
        fixedOrigin: String,
        requestOrigin: String?,
        currentMainFrameUrl: String?,
        resources: Array<String>?,
    ): Boolean {
        if (resources?.size != 1 || resources[0] != VIDEO_CAPTURE) return false
        val expected = parseHttps(fixedOrigin) ?: return false
        val requester = parseHttps(requestOrigin) ?: return false
        if (!isOriginOnly(requester) || !sameOrigin(expected, requester)) return false
        val mainFrame = parseHttps(currentMainFrameUrl) ?: return false
        return sameOrigin(expected, mainFrame) &&
            mainFrame.rawUserInfo == null &&
            mainFrame.rawPath == KIOSK_PATH
    }

    private fun isOriginOnly(uri: URI): Boolean =
        uri.rawUserInfo == null &&
            (uri.rawPath.isNullOrEmpty() || uri.rawPath == "/") &&
            uri.rawQuery == null &&
            uri.rawFragment == null

    private fun parseHttps(raw: String?): URI? = try {
        URI(raw.orEmpty()).takeIf {
            !it.isOpaque &&
                it.scheme.equals("https", ignoreCase = true) &&
                !it.host.isNullOrBlank() &&
                (it.port == -1 || it.port in 1..65535)
        }
    } catch (_: Exception) {
        null
    }

    private fun sameOrigin(first: URI, second: URI): Boolean =
        first.scheme.equals(second.scheme, ignoreCase = true) &&
            first.host.equals(second.host, ignoreCase = true) &&
            effectivePort(first) == effectivePort(second)

    private fun effectivePort(uri: URI): Int = if (uri.port == -1) 443 else uri.port
}

internal object KioskExternalPackagePolicy {
    private val PACKAGE_NAME = Regex("[A-Za-z][A-Za-z0-9_]*(?:\\.[A-Za-z][A-Za-z0-9_]*)+")

    fun lockTaskPackages(selfPackage: String, printerPackage: String): List<String> = buildList {
        require(PACKAGE_NAME.matches(selfPackage)) { "The kiosk package name is invalid" }
        add(selfPackage)
        if (PACKAGE_NAME.matches(printerPackage)) add(printerPackage)
    }

    fun configuredPrinter(printerPackage: String): String? =
        printerPackage.takeIf(PACKAGE_NAME::matches)
}
