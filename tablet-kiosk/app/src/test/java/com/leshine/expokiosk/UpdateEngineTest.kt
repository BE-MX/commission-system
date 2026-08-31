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
        val source = FakeSource(updateManifest.copy(versionCode = currentVersionCode))
        val verifier = FakeVerifier()
        val installer = FakeInstaller()
        val states = mutableListOf<UpdateState>()

        engine(source, verifier, installer).run(states::add)

        assertEquals(listOf(UpdateState.Checking, UpdateState.NoUpdate), states)
        assertEquals(1, source.fetchCalls)
        assertEquals(0, source.downloadCalls)
        assertEquals(0, verifier.calls)
        assertEquals(0, installer.calls)
    }

    @Test
    fun `downloads verifies and installs a newer version with clamped progress`() {
        val artifact = artifact()
        val source = FakeSource(
            manifest = updateManifest,
            artifact = artifact,
            progress = listOf(-10, 35, 140),
        )
        val verifier = FakeVerifier()
        val installer = FakeInstaller()
        val states = mutableListOf<UpdateState>()

        engine(source, verifier, installer).run(states::add)

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
        assertEquals(1, verifier.calls)
        assertSame(artifact, verifier.lastArtifact)
        assertEquals(1, installer.calls)
        assertSame(artifact, installer.lastArtifact)
        assertTrue(artifact.file.exists())
        assertFalse(states.contains(UpdateState.AwaitingUserAction))
    }

    @Test
    fun `turns fetch exceptions into a failed state without throwing`() {
        val source = FakeSource(updateManifest).apply {
            fetchFailure = IllegalStateException("manifest unavailable")
        }
        val states = mutableListOf<UpdateState>()

        engine(source).run(states::add)

        assertEquals(
            listOf(UpdateState.Checking, UpdateState.Failed("manifest unavailable")),
            states,
        )
        assertEquals(0, source.downloadCalls)
    }

    @Test
    fun `turns download exceptions into a failed state without throwing`() {
        val source = FakeSource(updateManifest).apply {
            downloadFailure = IllegalStateException("download failed")
        }
        val states = mutableListOf<UpdateState>()

        engine(source).run(states::add)

        assertEquals(UpdateState.Failed("download failed"), states.last())
    }

    @Test
    fun `deletes the artifact when verification throws`() {
        val artifact = artifact()
        val verifier = FakeVerifier().apply {
            failure = IllegalStateException("verification failed")
        }
        val states = mutableListOf<UpdateState>()

        engine(FakeSource(updateManifest, artifact), verifier).run(states::add)

        assertEquals(UpdateState.Failed("verification failed"), states.last())
        assertFalse(artifact.file.exists())
    }

    @Test
    fun `deletes a rejected artifact and reports the rejection reason`() {
        val artifact = artifact()
        val verifier = FakeVerifier(DownloadedApkDecision.Reject("signature mismatch"))
        val states = mutableListOf<UpdateState>()

        engine(FakeSource(updateManifest, artifact), verifier).run(states::add)

        assertEquals(UpdateState.Failed("signature mismatch"), states.last())
        assertFalse(artifact.file.exists())
    }

    @Test
    fun `deletes the artifact when installation throws`() {
        val artifact = artifact()
        val installer = FakeInstaller().apply {
            failure = IllegalStateException("installer unavailable")
        }
        val states = mutableListOf<UpdateState>()

        engine(
            source = FakeSource(updateManifest, artifact),
            installer = installer,
        ).run(states::add)

        assertEquals(UpdateState.Failed("installer unavailable"), states.last())
        assertFalse(artifact.file.exists())
    }

    @Test
    fun `uses a stable failure message when an exception message is empty`() {
        val source = FakeSource(updateManifest).apply {
            fetchFailure = IllegalStateException("")
        }
        val states = mutableListOf<UpdateState>()

        engine(source).run(states::add)

        assertEquals(UpdateState.Failed("升级失败"), states.last())
    }

    @Test
    fun `allows only the first concurrent or later run to perform IO`() {
        val fetchEntered = CountDownLatch(1)
        val allowFetchToFinish = CountDownLatch(1)
        val source = FakeSource(updateManifest.copy(versionCode = currentVersionCode)).apply {
            beforeFetch = {
                fetchEntered.countDown()
                assertTrue(allowFetchToFinish.await(5, TimeUnit.SECONDS))
            }
        }
        val states = Collections.synchronizedList(mutableListOf<UpdateState>())
        val executor = Executors.newFixedThreadPool(2)
        val updateEngine = engine(source)

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

        assertEquals(1, source.fetchCalls)
        assertEquals(listOf(UpdateState.Checking, UpdateState.NoUpdate), states)
    }

    @Test
    fun `does not swallow fatal JVM errors`() {
        val fatal = AssertionError("fatal")
        val source = FakeSource(updateManifest).apply { fetchError = fatal }
        val states = mutableListOf<UpdateState>()

        try {
            engine(source).run(states::add)
            fail("Expected the source error to propagate")
        } catch (error: AssertionError) {
            assertSame(fatal, error)
        }

        assertEquals(listOf(UpdateState.Checking), states)
    }

    @Test
    fun `awaiting user action is a public state but is not emitted by this engine`() {
        val publicState: UpdateState = UpdateState.AwaitingUserAction
        val states = mutableListOf<UpdateState>()

        engine(FakeSource(updateManifest.copy(versionCode = currentVersionCode))).run(states::add)

        assertEquals(UpdateState.AwaitingUserAction, publicState)
        assertFalse(states.contains(publicState))
    }

    private fun engine(
        source: UpdateSource,
        verifier: UpdateVerifier = FakeVerifier(),
        installer: UpdateInstaller = FakeInstaller(),
    ) = UpdateEngine(currentVersionCode, source, verifier, installer)

    private fun artifact(): DownloadedArtifact {
        val file = Files.createTempFile("update-engine-", ".apk").toFile()
        file.writeText("test")
        file.deleteOnExit()
        return DownloadedArtifact(file, file.length(), digest)
    }

    private class FakeSource(
        private val manifest: UpdateManifest,
        private val artifact: DownloadedArtifact? = null,
        private val progress: List<Int> = emptyList(),
    ) : UpdateSource {
        var fetchCalls = 0
        var downloadCalls = 0
        var fetchFailure: Exception? = null
        var downloadFailure: Exception? = null
        var fetchError: Error? = null
        var beforeFetch: (() -> Unit)? = null

        override fun fetchManifest(): UpdateManifest {
            fetchCalls += 1
            beforeFetch?.invoke()
            fetchError?.let { throw it }
            fetchFailure?.let { throw it }
            return manifest
        }

        override fun download(
            manifest: UpdateManifest,
            onProgress: (Int) -> Unit,
        ): DownloadedArtifact {
            downloadCalls += 1
            progress.forEach(onProgress)
            downloadFailure?.let { throw it }
            return checkNotNull(artifact) { "Fake artifact is required for a download" }
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
}
