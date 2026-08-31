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

/**
 * Receives internal update warnings. Implementations must avoid recording credentials, signers,
 * digests, or other sensitive adapter inputs.
 */
fun interface UpdateDiagnostics {
    fun warning(stage: String, error: Exception?)

    companion object {
        val NONE = UpdateDiagnostics { _, _ -> }
    }
}

sealed interface UpdateState {
    data object Checking : UpdateState
    data class Downloading(val versionName: String, val progress: Int) : UpdateState
    data object AwaitingUserAction : UpdateState
    data object Installing : UpdateState
    data object NoUpdate : UpdateState

    /**
     * Internal diagnostic detail only. Task 4 UI must not display [message] verbatim to users;
     * the original exception is sent to [UpdateDiagnostics].
     */
    data class Failed(val message: String) : UpdateState
}
