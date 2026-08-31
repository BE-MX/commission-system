package com.leshine.expokiosk

import android.annotation.SuppressLint
import android.app.PendingIntent
import android.app.admin.DevicePolicyManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageInstaller
import android.content.pm.PackageManager
import android.os.Build
import android.util.Log
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

private const val MANIFEST_MAX_BYTES = 16 * 1024
private const val COPY_BUFFER_BYTES = 32 * 1024

enum class InstallUserActionPolicy {
    SYSTEM_CONFIRMATION,
    SILENT_ALLOWED,
}

enum class InstallStatusDecision {
    AWAIT_USER,
    SUCCESS,
    FAILURE,
}

object UpdateRuntimePolicy {
    fun requireSuccessfulHttpStatus(status: Int) {
        require(status == HttpURLConnection.HTTP_OK) { "Update server returned an unexpected status" }
    }

    fun downloadProgress(bytesRead: Long, expectedSize: Long): Int {
        if (bytesRead <= 0 || expectedSize <= 0) return 0
        return ((bytesRead * 100) / expectedSize).coerceIn(0, 100).toInt()
    }

    fun signerFingerprint(der: ByteArray): String = PinnedTls.sha256Hex(der)

    fun installUserActionPolicy(deviceOwner: Boolean, sdkInt: Int): InstallUserActionPolicy =
        if (deviceOwner && sdkInt >= Build.VERSION_CODES.S) {
            InstallUserActionPolicy.SILENT_ALLOWED
        } else {
            InstallUserActionPolicy.SYSTEM_CONFIRMATION
        }

    fun installStatusDecision(status: Int): InstallStatusDecision = when (status) {
        PackageInstaller.STATUS_PENDING_USER_ACTION -> InstallStatusDecision.AWAIT_USER
        PackageInstaller.STATUS_SUCCESS -> InstallStatusDecision.SUCCESS
        else -> InstallStatusDecision.FAILURE
    }
}

fun streamApkToTarget(
    input: InputStream,
    target: File,
    expectedSize: Long,
    hardLimit: Long,
    onProgress: (Int) -> Unit,
): DownloadedArtifact {
    require(expectedSize in 1..hardLimit) { "Manifest APK size is outside the allowed range" }
    val digest = MessageDigest.getInstance("SHA-256")
    var total = 0L

    input.use { source ->
        FileOutputStream(target, false).use { output ->
            val buffer = ByteArray(COPY_BUFFER_BYTES)
            while (true) {
                val count = source.read(buffer)
                if (count < 0) break
                if (count == 0) continue
                val nextTotal = total + count
                require(nextTotal <= expectedSize && nextTotal <= hardLimit) {
                    "Downloaded APK exceeds the manifest size"
                }
                output.write(buffer, 0, count)
                digest.update(buffer, 0, count)
                total = nextTotal
                onProgress(UpdateRuntimePolicy.downloadProgress(total, expectedSize))
            }
            require(total == expectedSize) { "Downloaded APK does not match the manifest size" }
            output.fd.sync()
        }
    }

    return DownloadedArtifact(
        file = target,
        size = total,
        sha256 = digest.digest().joinToString("") { "%02x".format(it) },
    )
}

class HttpUpdateSource(
    private val context: Context,
    private val kioskUrl: String,
) : UpdateSource {
    override fun fetchManifest(): UpdateManifest {
        val connection = open(UpdatePolicy.manifestUrl(kioskUrl), 3_000, 5_000)
        try {
            UpdateRuntimePolicy.requireSuccessfulHttpStatus(connection.responseCode)
            val declaredSize = connection.contentLengthLong
            require(declaredSize <= MANIFEST_MAX_BYTES) { "Update manifest is too large" }
            val raw = connection.inputStream.use { input ->
                readManifest(input)
            }
            return UpdateManifestParser.parse(raw).getOrThrow()
        } finally {
            connection.disconnect()
        }
    }

    override fun download(
        manifest: UpdateManifest,
        target: File,
        onProgress: (Int) -> Unit,
    ): DownloadedArtifact {
        require(manifest.apkSize in 1..UpdatePolicy.MAX_APK_BYTES) {
            "Manifest APK size is outside the allowed range"
        }
        val connection = open(UpdatePolicy.apkUrl(kioskUrl), 5_000, 60_000)
        try {
            UpdateRuntimePolicy.requireSuccessfulHttpStatus(connection.responseCode)
            val declaredSize = connection.contentLengthLong
            require(declaredSize <= UpdatePolicy.MAX_APK_BYTES) { "APK response is too large" }
            require(declaredSize < 0 || declaredSize == manifest.apkSize) {
                "APK response size does not match the manifest"
            }
            return streamApkToTarget(
                input = connection.inputStream,
                target = target,
                expectedSize = manifest.apkSize,
                hardLimit = UpdatePolicy.MAX_APK_BYTES,
                onProgress = onProgress,
            )
        } finally {
            connection.disconnect()
        }
    }

    private fun open(url: String, connectTimeout: Int, readTimeout: Int): HttpURLConnection {
        val connection = URL(url).openConnection() as HttpURLConnection
        connection.instanceFollowRedirects = false
        connection.connectTimeout = connectTimeout
        connection.readTimeout = readTimeout
        connection.useCaches = false
        connection.requestMethod = "GET"
        PinnedTls.apply(context, connection)
        return connection
    }

    private fun readManifest(input: InputStream): String {
        val output = java.io.ByteArrayOutputStream()
        val buffer = ByteArray(4 * 1024)
        while (true) {
            val count = input.read(buffer)
            if (count < 0) break
            if (count == 0) continue
            require(output.size() + count <= MANIFEST_MAX_BYTES) { "Update manifest is too large" }
            output.write(buffer, 0, count)
        }
        return output.toString(Charsets.UTF_8.name())
    }
}

class AndroidApkVerifier(private val context: Context) : UpdateVerifier {
    override fun verify(
        manifest: UpdateManifest,
        artifact: DownloadedArtifact,
    ): DownloadedApkDecision {
        val packageManager = context.packageManager
        val current = packageInfo(packageManager, context.packageName)
            ?: return DownloadedApkDecision.Reject("Installed app identity is unavailable")
        val candidate = archivePackageInfo(packageManager, artifact.file)
            ?: return DownloadedApkDecision.Reject("Downloaded APK cannot be parsed")

        return UpdatePolicy.validateDownloaded(
            manifest = manifest,
            current = current.toIdentity(),
            candidate = candidate.toIdentity(),
            size = artifact.size,
            sha256 = artifact.sha256,
        )
    }

    @Suppress("DEPRECATION")
    private fun packageInfo(packageManager: PackageManager, packageName: String): PackageInfo? =
        try {
            packageManager.getPackageInfo(packageName, signatureFlags())
        } catch (_: PackageManager.NameNotFoundException) {
            null
        }

    @Suppress("DEPRECATION")
    private fun archivePackageInfo(packageManager: PackageManager, apk: File): PackageInfo? =
        packageManager.getPackageArchiveInfo(apk.absolutePath, signatureFlags())

    @Suppress("DEPRECATION")
    private fun signatureFlags(): Int = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
        PackageManager.GET_SIGNING_CERTIFICATES
    } else {
        PackageManager.GET_SIGNATURES
    }

    @Suppress("DEPRECATION")
    private fun PackageInfo.toIdentity(): ApkIdentity {
        val packageSigners = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            signingInfo?.apkContentsSigners.orEmpty()
        } else {
            signatures.orEmpty()
        }
        return ApkIdentity(
            packageName = packageName,
            versionCode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                longVersionCode
            } else {
                versionCode.toLong()
            },
            versionName = versionName.orEmpty(),
            signers = packageSigners.mapTo(linkedSetOf()) {
                UpdateRuntimePolicy.signerFingerprint(it.toByteArray())
            },
        )
    }
}

class AndroidUpdateInstaller(private val context: Context) : UpdateInstaller {
    @SuppressLint("UnspecifiedImmutableFlag")
    override fun install(artifact: DownloadedArtifact) {
        val packageInstaller = context.packageManager.packageInstaller
        val devicePolicy = context.getSystemService(DevicePolicyManager::class.java)
        val deviceOwner = devicePolicy?.isDeviceOwnerApp(context.packageName) == true
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
            .apply {
                setAppPackageName(context.packageName)
                setSize(artifact.size)
                setInstallReason(
                    if (deviceOwner) PackageManager.INSTALL_REASON_POLICY
                    else PackageManager.INSTALL_REASON_USER,
                )
                if (UpdateRuntimePolicy.installUserActionPolicy(
                        deviceOwner = deviceOwner,
                        sdkInt = Build.VERSION.SDK_INT,
                    ) == InstallUserActionPolicy.SILENT_ALLOWED
                ) {
                    setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_NOT_REQUIRED)
                }
            }

        val sessionId = packageInstaller.createSession(params)
        var committed = false
        try {
            packageInstaller.openSession(sessionId).use { session ->
                FileInputStream(artifact.file).use { input ->
                    session.openWrite("base.apk", 0, artifact.size).use { output ->
                        input.copyTo(output, COPY_BUFFER_BYTES)
                        session.fsync(output)
                    }
                }
                session.commit(installStatusIntent(sessionId).intentSender)
                committed = true
            }
        } finally {
            if (!committed) {
                runCatching { packageInstaller.abandonSession(sessionId) }
            } else if (!artifact.file.delete()) {
                Log.w(TAG, "Committed update cache cleanup failed")
            }
        }
    }

    private fun installStatusIntent(sessionId: Int): PendingIntent {
        val intent = Intent(context, UpdateInstallReceiver::class.java)
            .setAction(UpdateInstallReceiver.ACTION_INSTALL_STATUS)
        var flags = PendingIntent.FLAG_UPDATE_CURRENT
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            flags = flags or PendingIntent.FLAG_MUTABLE
        }
        return PendingIntent.getBroadcast(context, sessionId, intent, flags)
    }

    companion object {
        private const val TAG = "ExpoKioskUpdate"
    }
}

class AndroidUpdateDiagnostics : UpdateDiagnostics {
    override fun warning(stage: String, error: Exception?) {
        Log.w("ExpoKioskUpdate", "stage=$stage type=${error?.javaClass?.simpleName.orEmpty()}")
    }
}
