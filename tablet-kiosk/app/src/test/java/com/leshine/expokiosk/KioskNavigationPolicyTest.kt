package com.leshine.expokiosk

import org.junit.Assert.assertEquals
import org.junit.Test

class KioskNavigationPolicyTest {
    private val kioskUrl = "https://154.8.205.162/expo/kiosk"
    private val loginUrl = "https://154.8.205.162/login?redirect=%2Fexpo%2Fkiosk"

    @Test
    fun `allows only the configured kiosk page`() {
        for (url in listOf(
            kioskUrl,
            "$kioskUrl/",
            "$kioskUrl?station=hall-a",
            "$kioskUrl#result",
        )) {
            assertEquals(NavigationDecision.Allow, KioskNavigationPolicy.decide(kioskUrl, url))
        }
    }

    @Test
    fun `allows login only when it is bounded back to kiosk`() {
        assertEquals(NavigationDecision.Allow, KioskNavigationPolicy.decide(kioskUrl, loginUrl))
        assertEquals(
            NavigationDecision.Redirect(loginUrl),
            KioskNavigationPolicy.decide(kioskUrl, "https://154.8.205.162/login"),
        )
        assertEquals(
            NavigationDecision.Redirect(loginUrl),
            KioskNavigationPolicy.decide(
                kioskUrl,
                "https://154.8.205.162/login?redirect=%2Fdashboard",
            ),
        )
    }

    @Test
    fun `redirects every Ark page back to kiosk`() {
        for (url in listOf(
            "https://154.8.205.162/",
            "https://154.8.205.162/dashboard",
            "https://154.8.205.162/expo/leads",
            "https://154.8.205.162/create/invite-token",
        )) {
            assertEquals(
                NavigationDecision.Redirect(kioskUrl),
                KioskNavigationPolicy.decide(kioskUrl, url),
            )
        }
    }

    @Test
    fun `redirects cross-origin and non-http navigation back to kiosk`() {
        for (url in listOf(
            "https://leshine.work/dashboard",
            "http://154.8.205.162/expo/kiosk",
            "https://user@154.8.205.162/expo/kiosk",
            "intent://dashboard",
            "javascript:location='/dashboard'",
            "not a url",
        )) {
            assertEquals(
                NavigationDecision.Redirect(kioskUrl),
                KioskNavigationPolicy.decide(kioskUrl, url),
            )
        }
    }

    @Test
    fun `blocks every subframe while allowing main-frame policy checks`() {
        assertEquals(true, KioskNavigationPolicy.shouldBlockSubframe(null))
        assertEquals(true, KioskNavigationPolicy.shouldBlockSubframe(false))
        assertEquals(false, KioskNavigationPolicy.shouldBlockSubframe(true))
    }

    @Test
    fun `supports equivalent explicit default HTTPS ports`() {
        assertEquals(
            NavigationDecision.Allow,
            KioskNavigationPolicy.decide(kioskUrl, "https://154.8.205.162:443/expo/kiosk"),
        )
    }

    @Test
    fun `keeps custom ports isolated and rejects double-encoded login redirects`() {
        val customKiosk = "https://154.8.205.162:8443/expo/kiosk"
        val customLogin = "https://154.8.205.162:8443/login?redirect=%2Fexpo%2Fkiosk"
        assertEquals(
            NavigationDecision.Allow,
            KioskNavigationPolicy.decide(customKiosk, customLogin),
        )
        assertEquals(
            NavigationDecision.Redirect(customKiosk),
            KioskNavigationPolicy.decide(customKiosk, kioskUrl),
        )
        assertEquals(
            NavigationDecision.Redirect(loginUrl),
            KioskNavigationPolicy.decide(
                kioskUrl,
                "https://154.8.205.162/login?redirect=%252Fexpo%252Fkiosk&redirect=%2Fexpo%2Fkiosk",
            ),
        )
    }
}
