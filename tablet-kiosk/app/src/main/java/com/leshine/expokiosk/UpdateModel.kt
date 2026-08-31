package com.leshine.expokiosk

data class UpdateManifest(
    val versionCode: Long,
    val versionName: String,
    val apkSize: Long,
    val sha256: String,
)

data class ApkIdentity(
    val packageName: String,
    val versionCode: Long,
    val versionName: String,
    val signers: Set<String>,
)

sealed interface DownloadedApkDecision {
    data object Accept : DownloadedApkDecision
    data class Reject(val reason: String) : DownloadedApkDecision
}
