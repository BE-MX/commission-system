package com.leshine.expokiosk

import java.io.File

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

data class DownloadedArtifact(
    val file: File,
    val size: Long,
    val sha256: String,
)

sealed interface UpdateState {
    data object Checking : UpdateState
    data class Downloading(val versionName: String, val progress: Int) : UpdateState
    data object AwaitingUserAction : UpdateState
    data object Installing : UpdateState
    data object NoUpdate : UpdateState
    data class Failed(val message: String) : UpdateState
}
