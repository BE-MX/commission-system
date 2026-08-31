package com.leshine.expokiosk

import java.io.File
import java.nio.file.Files
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class UpdateEngineTest {
    private val digest = "a".repeat(64)
    private val currentVersionCode = 9L
    private val updateManifest = UpdateManifest(10, "1.9", 4, digest)

    @Test
    fun `reports no update without invoking downstream work`() {
        val target = downloadTarget()
        val source = FakeSource(updateManifest.copy(versionCode = currentVersionCode))
        val verifier = FakeVerifier()
        val installer = FakeInstaller()
        val states = mutableListOf<UpdateState>()

        engine(target, source, verifier, installer).run(states::add)

        assertEquals(listOf(UpdateState.Checking, UpdateState.NoUpdate), states)
        assertCalls(source, verifier, installer, fetch = 1, download = 0, verify = 0, install = 0)
        assertFalse(target.exists())
    }

    @Test
    fun `downloads verifies and installs a newer version with clamped progress`() {
        val target = downloadTarget()
        val source = FakeSource(updateManifest, progress = listOf(-10, 35, 140))
        val verifier = FakeVerifier()
        val installer = FakeInstaller()
        val states = mutableListOf<UpdateState>()

        engine(target, source, verifier, installer).run(states::add)

        assertEquals(
            listOf(
                UpdateState.Checking,
                UpdateState.Downloading("1.9", 0),
                UpdateState.Downloading("1.9", 35),
                UpdateState.Downloading("1.9", 100),
                UpdateState.Installing,
            ),
            states,
        )
        assertCalls(source, verifier, installer, fetch = 1, download = 1, verify = 1, install = 1)
        assertSame(target, source.lastTarget)
        assertSame(target, verifier.lastArtifact?.file)
        assertSame(target, installer.lastArtifact?.file)
        assertTrue(target.exists())
        assertFalse(states.contains(UpdateState.AwaitingUserAction))
    }

    @Test
    fun `removes a stale target before download starts`() {
        val target = downloadTarget().apply { writeText("stale") }
        val source = FakeSource(updateManifest).apply {
            beforeWrite = { assertFalse(it.exists()) }
        }

        engine(target, source).run { }

        assertEquals("test", target.readText())
        assertEquals(1, source.downloadCalls)
    }

    @Test
    fun `turns fetch exceptions into a failed state without downstream work`() {
        val target = downloadTarget().apply { writeText("stale") }
        val source = FakeSource(updateManifest).apply {
            fetchFailure = IllegalStateException("manifest unavailable")
        }
        val verifier = FakeVerifier()
        val installer = FakeInstaller()
        val states = mutableListOf<UpdateState>()

        engine(target, source, verifier, installer).run(states::add)

        assertEquals(
            listOf(UpdateState.Checking, UpdateState.Failed("manifest unavailable")),
            states,
        )
        assertCalls(source, verifier, installer, fetch = 1, download = 0, verify = 0, install = 0)
        assertFalse(target.exists())
    }

    @Test
    fun `deletes a partially written target when download throws`() {
        val target = downloadTarget()
        val source = FakeSource(updateManifest).apply {
            downloadFailure = IllegalStateException("download failed")
        }
        val verifier = FakeVerifier()
        val installer = FakeInstaller()
        val states = mutableListOf<UpdateState>()

        engine(target, source, verifier, installer).run(states::add)

        assertEquals(
            listOf(UpdateState.Checking, UpdateState.Failed("download failed")),
            states,
        )
        assertCalls(source, verifier, installer, fetch = 1, download = 1, verify = 0, install = 0)
        assertFalse(target.exists())
    }

    @Test
    fun `deletes the artifact when verification throws`() {
        val target = downloadTarget()
        val source = FakeSource(updateManifest)
        val verifier = FakeVerifier().apply {
            failure = IllegalStateException("verification failed")
        }
        val installer = FakeInstaller()
        val states = mutableListOf<UpdateState>()

        engine(target, source, verifier, installer).run(states::add)

        assertEquals(UpdateState.Failed("verification failed"), states.last())
        assertCalls(source, verifier, installer, fetch = 1, download = 1, verify = 1, install = 0)
        assertFalse(target.exists())
    }

    @Test
    fun `deletes a rejected artifact and reports the rejection reason`() {
        val target = downloadTarget()
        val source = FakeSource(updateManifest)
        val verifier = FakeVerifier(DownloadedApkDecision.Reject("signature mismatch"))
        val installer = FakeInstaller()
        val states = mutableListOf<UpdateState>()

        engine(target, source, verifier, installer).run(states::add)

        assertEquals(UpdateState.Failed("signature mismatch"), states.last())
        assertCalls(source, verifier, installer, fetch = 1, download = 1, verify = 1, install = 0)
        assertFalse(target.exists())
    }

    @Test
    fun `deletes the artifact when installation throws`() {
        val target = downloadTarget()
        val source = FakeSource(updateManifest)
        val verifier = FakeVerifier()
        val installFailure = IllegalStateException("installer unavailable")
        val installer = FakeInstaller().apply { failure = installFailure }
        val diagnostics = RecordingDiagnostics()
        val states = mutableListOf<UpdateState>()

        engine(target, source, verifier, installer, diagnostics).run(states::add)

        assertEquals(UpdateState.Failed("installer unavailable"), states.last())
        assertCalls(source, verifier, installer, fetch = 1, download = 1, verify = 1, install = 1)
        assertEquals(listOf(Warning("update.run", installFailure)), diagnostics.warnings)
        assertFalse(target.exists())
    }

    @Test
    fun `uses a stable failure message when an exception message is empty`() {
        val target = downloadTarget()
        val source = FakeSource(updateManifest).apply {
            fetchFailure = IllegalStateException("")
        }
        val verifier = FakeVerifier()
        val installer = FakeInstaller()
        val states = mutableListOf<UpdateState>()

        engine(target, source, verifier, installer).run(states::add)

        assertEquals(UpdateState.Failed("升级失败"), states.last())
        assertCalls(source, verifier, installer, fetch = 1, download = 0, verify = 0, install = 0)
    }

    @Test
    fun `uses a stable failure message when an exception message is null`() {
        val target = downloadTarget()
        val source = FakeSource(updateManifest).apply {
            fetchFailure = IllegalStateException(null as String?)
        }
        val verifier = FakeVerifier()
        val installer = FakeInstaller()
        val states = mutableListOf<UpdateState>()

        engine(target, source, verifier, installer).run(states::add)

        assertEquals(UpdateState.Failed("升级失败"), states.last())
        assertCalls(source, verifier, installer, fetch = 1, download = 0, verify = 0, install = 0)
    }

    @Test
    fun `checking observer exceptions are diagnostic only`() {
        assertObserverExceptionIsDiagnosticOnly(
            expectedStage = "state.checking",
            shouldThrow = { it == UpdateState.Checking },
        )
    }

    @Test
    fun `downloading observer exceptions are diagnostic only`() {
        assertObserverExceptionIsDiagnosticOnly(
            expectedStage = "state.downloading",
            shouldThrow = { it is UpdateState.Downloading },
        )
    }

    @Test
    fun `installing observer exceptions are diagnostic only`() {
        assertObserverExceptionIsDiagnosticOnly(
            expectedStage = "state.installing",
            shouldThrow = { it == UpdateState.Installing },
        )
    }

    @Test
    fun `a state callback cannot reenter the same engine`() {
        val target = downloadTarget()
        val source = FakeSource(updateManifest)
        val verifier = FakeVerifier()
        val installer = FakeInstaller()
        val outerStates = mutableListOf<UpdateState>()
        val reentrantStates = mutableListOf<UpdateState>()
        val updateEngine = engine(target, source, verifier, installer)

        updateEngine.run { state ->
            outerStates += state
            updateEngine.run(reentrantStates::add)
        }

        assertEquals(
            listOf(UpdateState.Checking, UpdateState.Installing),
            outerStates,
        )
        assertTrue(reentrantStates.isEmpty())
        assertCalls(source, verifier, installer, fetch = 1, download = 1, verify = 1, install = 1)
        assertTrue(target.exists())
    }

    @Test
    fun `reports delete false without replacing a rejection failure`() {
        val target = controlledDeleteTarget(deleteResult = false)
        val source = FakeSource(updateManifest)
        val verifier = FakeVerifier(DownloadedApkDecision.Reject("signature mismatch"))
        val installer = FakeInstaller()
        val diagnostics = RecordingDiagnostics()
        val states = mutableListOf<UpdateState>()

        try {
            engine(target, source, verifier, installer, diagnostics).run(states::add)

            assertEquals(UpdateState.Failed("signature mismatch"), states.last())
            assertCalls(source, verifier, installer, fetch = 1, download = 1, verify = 1, install = 0)
            assertEquals(listOf(Warning("cleanup.download_target", null)), diagnostics.warnings)
            assertTrue(target.exists())
        } finally {
            File(target.path).delete()
        }
    }

    @Test
    fun `reports delete exceptions without replacing a rejection failure`() {
        val deleteFailure = SecurityException("delete blocked")
        val target = controlledDeleteTarget(deleteFailure = deleteFailure)
        val source = FakeSource(updateManifest)
        val verifier = FakeVerifier(DownloadedApkDecision.Reject("signature mismatch"))
        val installer = FakeInstaller()
        val diagnostics = RecordingDiagnostics()
        val states = mutableListOf<UpdateState>()

        try {
            engine(target, source, verifier, installer, diagnostics).run(states::add)

            assertEquals(UpdateState.Failed("signature mismatch"), states.last())
            assertCalls(source, verifier, installer, fetch = 1, download = 1, verify = 1, install = 0)
            assertEquals(
                listOf(Warning("cleanup.download_target", deleteFailure)),
                diagnostics.warnings,
            )
            assertTrue(target.exists())
        } finally {
            File(target.path).delete()
        }
    }

    @Test
    fun `allows only the first concurrent or later run to perform IO`() {
        val target = downloadTarget()
        val fetchEntered = CountDownLatch(1)
        val allowFetchToFinish = CountDownLatch(1)
        val source = FakeSource(updateManifest.copy(versionCode = currentVersionCode)).apply {
            beforeFetch = {
                fetchEntered.countDown()
                assertTrue(allowFetchToFinish.await(5, TimeUnit.SECONDS))
            }
        }
        val verifier = FakeVerifier()
        val installer = FakeInstaller()
        val states = Collections.synchronizedList(mutableListOf<UpdateState>())
        val executor = Executors.newFixedThreadPool(2)
        val updateEngine = engine(target, source, verifier, installer)

        try {
            val first = executor.submit { updateEngine.run(states::add) }
            assertTrue(fetchEntered.await(5, TimeUnit.SECONDS))
            val second = executor.submit { updateEngine.run(states::add) }
            second.get(5, TimeUnit.SECONDS)
            allowFetchToFinish.countDown()
            first.get(5, TimeUnit.SECONDS)

            updateEngine.run(states::add)
        } finally {
            allowFetchToFinish.countDown()
            executor.shutdownNow()
        }

        assertCalls(source, verifier, installer, fetch = 1, download = 0, verify = 0, install = 0)
        assertEquals(listOf(UpdateState.Checking, UpdateState.NoUpdate), states)
    }

    @Test
    fun `does not swallow fatal JVM errors`() {
        val target = downloadTarget()
        val fatal = AssertionError("fatal")
        val source = FakeSource(updateManifest).apply { fetchError = fatal }
        val verifier = FakeVerifier()
        val installer = FakeInstaller()
        val states = mutableListOf<UpdateState>()

        try {
            engine(target, source, verifier, installer).run(states::add)
            fail("Expected the source error to propagate")
        } catch (error: AssertionError) {
            assertSame(fatal, error)
        }

        assertEquals(listOf(UpdateState.Checking), states)
        assertCalls(source, verifier, installer, fetch = 1, download = 0, verify = 0, install = 0)
    }

    @Test
    fun `awaiting user action is a public state but is not emitted by this engine`() {
        val target = downloadTarget()
        val publicState: UpdateState = UpdateState.AwaitingUserAction
        val states = mutableListOf<UpdateState>()

        engine(
            target,
            FakeSource(updateManifest.copy(versionCode = currentVersionCode)),
        ).run(states::add)

        assertEquals(UpdateState.AwaitingUserAction, publicState)
        assertFalse(states.contains(publicState))
    }

    private fun assertObserverExceptionIsDiagnosticOnly(
        expectedStage: String,
        shouldThrow: (UpdateState) -> Boolean,
    ) {
        val target = downloadTarget()
        val source = FakeSource(updateManifest, progress = listOf(50))
        val verifier = FakeVerifier()
        val installer = FakeInstaller()
        val diagnostics = RecordingDiagnostics()
        val observerFailure = IllegalStateException("observer failed")
        val states = mutableListOf<UpdateState>()

        engine(target, source, verifier, installer, diagnostics).run { state ->
            states += state
            if (shouldThrow(state)) throw observerFailure
        }

        assertEquals(
            listOf(
                UpdateState.Checking,
                UpdateState.Downloading("1.9", 50),
                UpdateState.Installing,
            ),
            states,
        )
        assertCalls(source, verifier, installer, fetch = 1, download = 1, verify = 1, install = 1)
        assertEquals(listOf(Warning(expectedStage, observerFailure)), diagnostics.warnings)
        assertTrue(target.exists())
    }

    private fun engine(
        downloadTarget: File,
        source: UpdateSource,
        verifier: UpdateVerifier = FakeVerifier(),
        installer: UpdateInstaller = FakeInstaller(),
        diagnostics: UpdateDiagnostics = UpdateDiagnostics.NONE,
    ) = UpdateEngine(
        currentVersionCode = currentVersionCode,
        source = source,
        verifier = verifier,
        installer = installer,
        downloadTarget = downloadTarget,
        diagnostics = diagnostics,
    )

    private fun downloadTarget(): File {
        val file = Files.createTempFile("update-engine-", ".apk").toFile()
        check(file.delete())
        file.deleteOnExit()
        return file
    }

    private fun controlledDeleteTarget(
        deleteResult: Boolean = true,
        deleteFailure: Exception? = null,
    ): File {
        val path = downloadTarget().path
        File(path).deleteOnExit()
        return ControlledDeleteFile(path, deleteResult, deleteFailure)
    }

    private fun assertCalls(
        source: FakeSource,
        verifier: FakeVerifier,
        installer: FakeInstaller,
        fetch: Int,
        download: Int,
        verify: Int,
        install: Int,
    ) {
        assertEquals("fetch calls", fetch, source.fetchCalls)
        assertEquals("download calls", download, source.downloadCalls)
        assertEquals("verify calls", verify, verifier.calls)
        assertEquals("install calls", install, installer.calls)
    }

    private class FakeSource(
        private val manifest: UpdateManifest,
        private val progress: List<Int> = emptyList(),
        private val downloadedSha256: String = "a".repeat(64),
    ) : UpdateSource {
        var fetchCalls = 0
        var downloadCalls = 0
        var lastTarget: File? = null
        var fetchFailure: Exception? = null
        var downloadFailure: Exception? = null
        var fetchError: Error? = null
        var beforeFetch: (() -> Unit)? = null
        var beforeWrite: ((File) -> Unit)? = null

        override fun fetchManifest(): UpdateManifest {
            fetchCalls += 1
            beforeFetch?.invoke()
            fetchError?.let { throw it }
            fetchFailure?.let { throw it }
            return manifest
        }

        override fun download(
            manifest: UpdateManifest,
            target: File,
            onProgress: (Int) -> Unit,
        ): DownloadedArtifact {
            downloadCalls += 1
            lastTarget = target
            beforeWrite?.invoke(target)
            target.writeText("test")
            progress.forEach(onProgress)
            downloadFailure?.let { throw it }
            return DownloadedArtifact(target, target.length(), downloadedSha256)
        }
    }

    private class FakeVerifier(
        private val decision: DownloadedApkDecision = DownloadedApkDecision.Accept,
    ) : UpdateVerifier {
        var calls = 0
        var lastArtifact: DownloadedArtifact? = null
        var failure: Exception? = null

        override fun verify(
            manifest: UpdateManifest,
            artifact: DownloadedArtifact,
        ): DownloadedApkDecision {
            calls += 1
            lastArtifact = artifact
            failure?.let { throw it }
            return decision
        }
    }

    private class FakeInstaller : UpdateInstaller {
        var calls = 0
        var lastArtifact: DownloadedArtifact? = null
        var failure: Exception? = null

        override fun install(artifact: DownloadedArtifact) {
            calls += 1
            lastArtifact = artifact
            failure?.let { throw it }
        }
    }

    private class RecordingDiagnostics : UpdateDiagnostics {
        val warnings = mutableListOf<Warning>()

        override fun warning(stage: String, error: Exception?) {
            warnings += Warning(stage, error)
        }
    }

    private data class Warning(
        val stage: String,
        val error: Exception?,
    )

    private class ControlledDeleteFile(
        path: String,
        private val deleteResult: Boolean,
        private val deleteFailure: Exception?,
    ) : File(path) {
        override fun delete(): Boolean {
            deleteFailure?.let { throw it }
            return deleteResult
        }
    }
}
