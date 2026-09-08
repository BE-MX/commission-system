package com.leshine.pdareporting

import java.io.InputStream
import java.security.KeyStore
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSocketFactory
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509TrustManager

/** Add the public ISRG anchor missing from Android 6/7, only for our API hosts. */
internal object LegacyTls {
    fun needsBundledRoot(sdkInt: Int, host: String): Boolean = sdkInt <= 25 &&
        host.lowercase() in setOf("leshine.cloud", "www.leshine.cloud", "leshine.work", "www.leshine.work")

    fun systemTrustManager(): X509TrustManager = trustManager(null)

    fun augmentedTrustManager(
        root: InputStream,
        systemRoots: Array<X509Certificate> = systemTrustManager().acceptedIssuers,
    ): X509TrustManager {
        val store = KeyStore.getInstance(KeyStore.getDefaultType()).apply { load(null, null) }
        systemRoots.forEachIndexed { index, certificate -> store.setCertificateEntry("system-$index", certificate) }
        val certificate = root.use { CertificateFactory.getInstance("X.509").generateCertificate(it) }
        store.setCertificateEntry("isrg-root-x1", certificate)
        return trustManager(store)
    }

    fun socketFactory(manager: X509TrustManager): SSLSocketFactory =
        SSLContext.getInstance("TLS").apply { init(null, arrayOf(manager), null) }.socketFactory

    private fun trustManager(store: KeyStore?): X509TrustManager =
        TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm()).apply { init(store) }
            .trustManagers.filterIsInstance<X509TrustManager>().single()
}
