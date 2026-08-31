package com.leshine.expokiosk

import java.net.URI

object UpdatePolicy {
    const val MAX_APK_BYTES = 100L * 1024 * 1024

    private const val PACKAGE_NAME = "com.leshine.expokiosk"
    private const val MANIFEST_PATH = "/expo-app/latest.json"
    private const val APK_PATH = "/expo-app/leshine-expo-kiosk.apk"

    fun manifestUrl(kioskUrl: String): String = endpointUrl(kioskUrl, MANIFEST_PATH)

    fun apkUrl(kioskUrl: String): String = endpointUrl(kioskUrl, APK_PATH)

    fun validateDownloaded(
        manifest: UpdateManifest,
        current: ApkIdentity,
        candidate: ApkIdentity,
        size: Long,
        sha256: String,
    ): DownloadedApkDecision {
        if (manifest.versionCode <= current.versionCode) {
            return DownloadedApkDecision.Reject("Manifest version must be newer than the installed app")
        }
        if (current.packageName != PACKAGE_NAME || candidate.packageName != PACKAGE_NAME ||
            candidate.packageName != current.packageName
        ) {
            return DownloadedApkDecision.Reject("APK package does not match the installed kiosk app")
        }
        if (candidate.versionCode != manifest.versionCode) {
            return DownloadedApkDecision.Reject("APK version code does not match the manifest")
        }
        if (candidate.versionName != manifest.versionName) {
            return DownloadedApkDecision.Reject("APK version name does not match the manifest")
        }
        if (candidate.signers.isEmpty() || candidate.signers != current.signers) {
            return DownloadedApkDecision.Reject("APK signer set does not match the installed app")
        }
        if (size !in 1..MAX_APK_BYTES || size != manifest.apkSize) {
            return DownloadedApkDecision.Reject("APK size is invalid or does not match the manifest")
        }
        if (sha256 != manifest.sha256) {
            return DownloadedApkDecision.Reject("APK sha256 does not match the manifest")
        }
        return DownloadedApkDecision.Accept
    }

    private fun endpointUrl(kioskUrl: String, path: String): String {
        val kiosk = try {
            URI(kioskUrl.trim())
        } catch (exception: Exception) {
            throw IllegalArgumentException("Kiosk URL is invalid", exception)
        }
        val scheme = kiosk.scheme?.lowercase()
        require(scheme == "http" || scheme == "https") { "Kiosk URL must use HTTP or HTTPS" }
        require(!kiosk.host.isNullOrBlank()) { "Kiosk URL must include a valid host" }

        return URI(scheme, null, kiosk.host, kiosk.port, path, null, null).toString()
    }
}
