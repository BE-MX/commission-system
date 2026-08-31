package com.leshine.expokiosk

import java.io.File
import java.util.concurrent.atomic.AtomicBoolean

interface UpdateSource {
    fun fetchManifest(): UpdateManifest

    fun download(
        manifest: UpdateManifest,
        target: File,
        onProgress: (Int) -> Unit,
    ): DownloadedArtifact
}

interface UpdateVerifier {
    fun verify(
        manifest: UpdateManifest,
        artifact: DownloadedArtifact,
    ): DownloadedApkDecision
}

interface UpdateInstaller {
    fun install(artifact: DownloadedArtifact)
}

class UpdateEngine(
    private val currentVersionCode: Long,
    private val source: UpdateSource,
    private val verifier: UpdateVerifier,
    private val installer: UpdateInstaller,
    private val downloadTarget: File,
    private val diagnostics: UpdateDiagnostics = UpdateDiagnostics.NONE,
) {
    private val hasRun = AtomicBoolean(false)

    fun run(onState: (UpdateState) -> Unit) {
        if (!hasRun.compareAndSet(false, true)) return

        var artifact: DownloadedArtifact? = null
        try {
            emitState(UpdateState.Checking, onState)
            val manifest = source.fetchManifest()
            if (manifest.versionCode <= currentVersionCode) {
                emitState(UpdateState.NoUpdate, onState)
                return
            }

            deleteDownloadFiles()
            artifact = source.download(manifest, downloadTarget) { progress ->
                emitState(
                    UpdateState.Downloading(
                        versionName = manifest.versionName,
                        progress = progress.coerceIn(0, 100),
                    ),
                    onState,
                )
            }
            when (val decision = verifier.verify(manifest, artifact)) {
                DownloadedApkDecision.Accept -> {
                    installer.install(artifact)
                    emitState(UpdateState.Installing, onState)
                }

                is DownloadedApkDecision.Reject -> {
                    deleteDownloadFiles(artifact)
                    emitState(UpdateState.Failed(decision.reason), onState)
                }
            }
        } catch (exception: Exception) {
            reportWarning("update.run", exception)
            deleteDownloadFiles(artifact)
            emitState(
                UpdateState.Failed(exception.message?.takeIf(String::isNotBlank) ?: "升级失败"),
                onState,
            )
        }
    }

    private fun emitState(
        state: UpdateState,
        onState: (UpdateState) -> Unit,
    ) {
        try {
            onState(state)
        } catch (exception: Exception) {
            reportWarning(state.diagnosticStage(), exception)
        }
    }

    private fun deleteDownloadFiles(artifact: DownloadedArtifact? = null) {
        if (artifact != null && artifact.file != downloadTarget) {
            deleteFile(artifact.file, "cleanup.artifact")
        }
        deleteFile(downloadTarget, "cleanup.download_target")
    }

    private fun deleteFile(file: File, stage: String) {
        try {
            if (file.exists() && !file.delete()) {
                reportWarning(stage, null)
            }
        } catch (exception: Exception) {
            reportWarning(stage, exception)
        }
    }

    private fun reportWarning(stage: String, error: Exception?) {
        try {
            diagnostics.warning(stage, error)
        } catch (_: Exception) {
            // Diagnostics must never change the update lifecycle.
        }
    }

    private fun UpdateState.diagnosticStage(): String = when (this) {
        UpdateState.Checking -> "state.checking"
        is UpdateState.Downloading -> "state.downloading"
        UpdateState.AwaitingUserAction -> "state.awaiting_user_action"
        UpdateState.Installing -> "state.installing"
        UpdateState.NoUpdate -> "state.no_update"
        is UpdateState.Failed -> "state.failed"
    }
}
