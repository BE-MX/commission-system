package com.leshine.expokiosk

import java.util.concurrent.atomic.AtomicBoolean

interface UpdateSource {
    fun fetchManifest(): UpdateManifest

    fun download(
        manifest: UpdateManifest,
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
) {
    private val hasRun = AtomicBoolean(false)

    fun run(onState: (UpdateState) -> Unit) {
        if (!hasRun.compareAndSet(false, true)) return

        var artifact: DownloadedArtifact? = null
        try {
            onState(UpdateState.Checking)
            val manifest = source.fetchManifest()
            if (manifest.versionCode <= currentVersionCode) {
                onState(UpdateState.NoUpdate)
                return
            }

            artifact = source.download(manifest) { progress ->
                onState(
                    UpdateState.Downloading(
                        versionName = manifest.versionName,
                        progress = progress.coerceIn(0, 100),
                    ),
                )
            }
            when (val decision = verifier.verify(manifest, artifact)) {
                DownloadedApkDecision.Accept -> {
                    installer.install(artifact)
                    onState(UpdateState.Installing)
                }

                is DownloadedApkDecision.Reject -> {
                    deleteArtifact(artifact)
                    onState(UpdateState.Failed(decision.reason))
                }
            }
        } catch (exception: Exception) {
            deleteArtifact(artifact)
            try {
                onState(UpdateState.Failed(exception.message?.takeIf(String::isNotBlank) ?: "升级失败"))
            } catch (_: Exception) {
                // State observers must not make the synchronous update run throw.
            }
        }
    }

    private fun deleteArtifact(artifact: DownloadedArtifact?) {
        try {
            artifact?.file?.delete()
        } catch (_: Exception) {
            // Cleanup is best effort; update failure must still be reported.
        }
    }
}
