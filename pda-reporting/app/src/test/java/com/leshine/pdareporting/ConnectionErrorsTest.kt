package com.leshine.pdareporting

import java.net.SocketTimeoutException
import java.net.UnknownHostException
import javax.net.ssl.SSLHandshakeException
import javax.net.ssl.SSLPeerUnverifiedException
import org.junit.Assert.*
import org.junit.Test

class ConnectionErrorsTest {
    @Test fun tlsFailurePointsToClockAndCertificateInsteadOfAddress() {
        val message = connectionErrorMessage(SSLHandshakeException("Trust anchor not found"))
        assertTrue(message.contains("日期时间"))
        assertTrue(message.contains("证书"))
        assertFalse(message.contains("Wi-Fi"))
    }

    @Test fun distinguishesHostnameDnsAndTimeoutFailures() {
        assertTrue(connectionErrorMessage(SSLPeerUnverifiedException("wrong host")).contains("不匹配"))
        assertTrue(connectionErrorMessage(UnknownHostException()).contains("无法解析"))
        assertTrue(connectionErrorMessage(SocketTimeoutException()).contains("超时"))
    }

    @Test fun preservesBusinessErrorMessages() {
        assertEquals("账号或密码错误", connectionErrorMessage(ApiException(401, "账号或密码错误")))
    }
}
