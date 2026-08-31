package com.leshine.expokiosk

import java.net.URI

object UpdatePolicy {
    const val MAX_APK_BYTES = 100L * 1024 * 1024

    private const val PACKAGE_NAME = "com.leshine.expokiosk"
    private const val MANIFEST_PATH = "/expo-app/latest.json"
    private const val APK_PATH = "/expo-app/leshine-expo-kiosk.apk"
    private val sha256Pattern = Regex("^[0-9a-f]{64}$")

    fun manifestUrl(kioskUrl: String): String = endpointUrl(kioskUrl, MANIFEST_PATH)

    fun apkUrl(kioskUrl: String): String = endpointUrl(kioskUrl, APK_PATH)

    fun validateDownloaded(
        manifest: UpdateManifest,
        current: ApkIdentity,
        candidate: ApkIdentity,
        size: Long,
        sha256: String,
    ): DownloadedApkDecision {
        val manifestProblem = when {
            manifest.versionCode <= 0 -> "version code must be positive"
            manifest.versionName.isBlank() || manifest.versionName != manifest.versionName.trim() ->
                "version name must be non-blank and trimmed"
            manifest.apkSize !in 1..MAX_APK_BYTES -> "APK size is outside the allowed range"
            !sha256Pattern.matches(manifest.sha256) ->
                "sha256 must be 64 lowercase hexadecimal characters"
            else -> null
        }
        if (manifestProblem != null) {
            return DownloadedApkDecision.Reject("Invalid manifest: $manifestProblem")
        }
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
        require(kioskUrl == kioskUrl.trim()) { "Kiosk URL must already be normalized" }
        val kiosk = try {
            URI(kioskUrl)
        } catch (exception: Exception) {
            throw IllegalArgumentException("Kiosk URL is invalid", exception)
        }
        val scheme = kiosk.scheme?.lowercase()
        require(scheme == "https") { "Kiosk URL must use HTTPS" }
        require(!kiosk.host.isNullOrBlank()) { "Kiosk URL must include a valid host" }
        require(kiosk.userInfo == null) { "Kiosk URL must not include user information" }
        require(kiosk.port == -1 || kiosk.port in 1..65535) { "Kiosk URL port is invalid" }

        return URI(scheme, null, kiosk.host, kiosk.port, path, null, null).toString()
    }
}
