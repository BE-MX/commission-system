package com.leshine.pdareporting

import java.io.File
import java.net.URL
import java.security.KeyStore
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLHandshakeException
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509TrustManager
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test

class LegacyTlsTest {
    private val rootFile = File("src/main/res/raw/isrg_root_x1.pem")
    private val root get() = rootFile.inputStream().use {
        CertificateFactory.getInstance("X.509").generateCertificate(it) as X509Certificate
    }
    // Model an old trust store without either ISRG anchor; retain unrelated system CAs.
    private val oldRoots get() = LegacyTls.systemTrustManager().acceptedIssuers.filter {
        !it.subjectX500Principal.name.contains("ISRG")
    }.toTypedArray()

    @Test fun bundlesTheOfficialSelfSignedRoot() {
        val certificate = root
        certificate.verify(certificate.publicKey)
        val fingerprint = MessageDigest.getInstance("SHA-256").digest(certificate.encoded)
            .joinToString("") { "%02x".format(it) }
        assertEquals("96bcec06264976f37460779acf28c5a7cfe8a3c0aae11a8ffcee05c0bddf08c6", fingerprint)
    }

    @Test fun addsMissingIsrgRootAndPreservesSystemAnchors() {
        val old = oldRoots
        val manager = LegacyTls.augmentedTrustManager(rootFile.inputStream(), old)
        assertTrue(manager.acceptedIssuers.toList().containsAll(old.toList()))
        assertTrue(manager.acceptedIssuers.contains(root))
        manager.checkServerTrusted(arrayOf(root), "RSA")
    }

    @Test fun doesNotTrustUnrelatedCertificates() {
        val manager = LegacyTls.augmentedTrustManager(rootFile.inputStream(), emptyArray())
        assertThrows(CertificateException::class.java) {
            manager.checkServerTrusted(arrayOf(oldRoots.first()), "RSA")
        }
    }

    @Test fun onlyUsesExtraAnchorOnLegacyAndroidAndExactLeshineHosts() {
        for (sdk in listOf(23, 24, 25)) {
            for (host in listOf("leshine.cloud", "www.leshine.cloud", "leshine.work", "www.leshine.work")) {
                assertTrue(LegacyTls.needsBundledRoot(sdk, host))
            }
        }
        assertTrue(LegacyTls.needsBundledRoot(23, "WWW.LESHINE.CLOUD"))
        assertFalse(LegacyTls.needsBundledRoot(26, "leshine.cloud"))
        assertFalse(LegacyTls.needsBundledRoot(35, "leshine.cloud"))
        for (host in listOf("other.example", "leshine.cloud.example", "evil-leshine.cloud", "154.8.205.162")) {
            assertFalse(LegacyTls.needsBundledRoot(23, host))
        }
    }

    @Test fun liveServerFailsWithoutIsrgAndConnectsWithBundledRoot() {
        // Explicit opt-in: normal unit tests do not depend on a production server or DNS.
        assumeTrue(System.getenv("PDA_TLS_SMOKE") == "1")
        val oldStore = KeyStore.getInstance(KeyStore.getDefaultType()).apply {
            load(null, null)
            oldRoots.forEachIndexed { index, cert -> setCertificateEntry("old-$index", cert) }
        }
        val oldManager = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm()).apply {
            init(oldStore)
        }.trustManagers.filterIsInstance<X509TrustManager>().single()
        assertThrows(SSLHandshakeException::class.java) { probe("www.leshine.cloud", oldManager) }
        val fixed = LegacyTls.augmentedTrustManager(rootFile.inputStream(), oldRoots)
        for (host in listOf("www.leshine.cloud", "leshine.cloud", "leshine.work")) {
            assertEquals(403, probe(host, fixed))
        }
    }

    private fun probe(host: String, manager: X509TrustManager): Int {
        val connection = URL("https://$host/api/auth/me").openConnection() as HttpsURLConnection
        return try {
            connection.sslSocketFactory = LegacyTls.socketFactory(manager)
            connection.connectTimeout = 15_000
            connection.readTimeout = 15_000
            // Leave the default hostname verifier enabled. No credentials or business writes.
            connection.responseCode
        } finally {
            connection.disconnect()
        }
    }
}
