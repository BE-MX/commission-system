package com.leshine.pdareporting

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class ApiClientTest {
    @Test
    fun normalizesHttpsServerUrl() {
        assertEquals("https://leshine.work", ApiClient.normalizeBaseUrl(" https://leshine.work/// "))
    }

    @Test
    fun rejectsCleartextServerUrl() {
        assertThrows(IllegalArgumentException::class.java) {
            ApiClient.normalizeBaseUrl("http://192.168.1.8:8000")
        }
    }
}
