package com.leshine.expokiosk

import android.content.Context
import java.net.HttpURLConnection
import java.security.KeyStore
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import javax.net.ssl.HostnameVerifier
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509TrustManager

/**
 * 自签证书的指纹 pinning，WebView 与原生下载两条链路共用同一把尺子。
 *
 * 背景：展会实例是 IP 直连，申请不到 CA 证书，但 http 下浏览器不给 secure context、网页相机用不了。
 * 于是服务器挂自签证书，客户端只认 strings.xml 里 pin 的那张指纹——**不是关掉校验**：
 * 指纹不匹配时回落到系统信任链，两边都不过才拒绝。备案后换正规证书，这里自动走系统信任链，无需改动。
 *
 * 必须两条链路都装：`MainActivity.downloadAndSaveToGallery` 用的是裸 HttpURLConnection，
 * 只给 WebView 放行的话「一键打印」会在 TLS 握手上直接断掉。
 */
object PinnedTls {

    fun sha256Hex(der: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(der).joinToString("") { "%02x".format(it) }

    fun pinnedFingerprint(ctx: Context): String =
        ctx.getString(R.string.pinned_cert_sha256).replace(":", "").trim().lowercase()

    fun matches(ctx: Context, der: ByteArray?): Boolean {
        val expected = pinnedFingerprint(ctx)
        if (expected.isEmpty() || der == null) return false
        return runCatching { sha256Hex(der) == expected }.getOrDefault(false)
    }

    /** 给 https 连接装上「pin 优先、系统信任链兜底」的校验；http 连接原样返回 */
    fun apply(ctx: Context, conn: HttpURLConnection) {
        if (conn !is HttpsURLConnection) return
        val expected = pinnedFingerprint(ctx)
        if (expected.isEmpty()) return
        runCatching {
            val tm = object : X509TrustManager {
                override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) = Unit

                override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
                    val leaf = chain.firstOrNull() ?: throw CertificateException("empty chain")
                    if (sha256Hex(leaf.encoded) == expected) return // 就是我们那张自签证书
                    systemTrustManager()?.checkServerTrusted(chain, authType)
                        ?: throw CertificateException("cert not pinned and no system trust manager")
                }

                override fun getAcceptedIssuers(): Array<X509Certificate> = arrayOf()
            }
            conn.sslSocketFactory = SSLContext.getInstance("TLS")
                .apply { init(null, arrayOf<javax.net.ssl.TrustManager>(tm), null) }
                .socketFactory
            // 指纹已经唯一锁定了证书，主机名不必再校验（IP 证书本来也过不了常规 hostname 规则）；
            // 非 pin 证书仍走系统默认 verifier
            val default = HttpsURLConnection.getDefaultHostnameVerifier()
            conn.hostnameVerifier = HostnameVerifier { hostname, session ->
                val leafDer = runCatching { session.peerCertificates.firstOrNull()?.encoded }.getOrNull()
                if (leafDer != null && sha256Hex(leafDer) == expected) true
                else default.verify(hostname, session)
            }
        }
    }

    private fun systemTrustManager(): X509TrustManager? = runCatching {
        TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm())
            .apply { init(null as KeyStore?) }
            .trustManagers
            .filterIsInstance<X509TrustManager>()
            .firstOrNull()
    }.getOrNull()
}
