package com.leshine.expokiosk

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class UpdatePresentationTest {
    @Test
    fun `checking blocks kiosk with fixed message`() {
        val presentation = UpdatePresentation.from(UpdateState.Checking)

        assertTrue(presentation.blocksKiosk)
        assertEquals(UpdateMessage.CHECKING, presentation.message)
        assertNull(presentation.versionName)
        assertNull(presentation.progress)
    }

    @Test
    fun `downloading blocks kiosk and clamps progress`() {
        assertEquals(
            UpdatePresentation(
                blocksKiosk = true,
                message = UpdateMessage.DOWNLOADING,
                versionName = "1.9",
                progress = 0,
            ),
            UpdatePresentation.from(UpdateState.Downloading("1.9", -20)),
        )
        assertEquals(
            UpdatePresentation(
                blocksKiosk = true,
                message = UpdateMessage.DOWNLOADING,
                versionName = "1.9",
                progress = 100,
            ),
            UpdatePresentation.from(UpdateState.Downloading("1.9", 120)),
        )
    }

    @Test
    fun `awaiting confirmation blocks kiosk with fixed message`() {
        val presentation = UpdatePresentation.from(UpdateState.AwaitingUserAction)

        assertTrue(presentation.blocksKiosk)
        assertEquals(UpdateMessage.AWAITING_USER_ACTION, presentation.message)
    }

    @Test
    fun `installing blocks kiosk with fixed message`() {
        val presentation = UpdatePresentation.from(UpdateState.Installing)

        assertTrue(presentation.blocksKiosk)
        assertEquals(UpdateMessage.INSTALLING, presentation.message)
    }

    @Test
    fun `no update releases kiosk without a message`() {
        val presentation = UpdatePresentation.from(UpdateState.NoUpdate)

        assertFalse(presentation.blocksKiosk)
        assertNull(presentation.message)
        assertNull(presentation.versionName)
        assertNull(presentation.progress)
    }

    @Test
    fun `failure releases kiosk without exposing internal diagnostics`() {
        val secret = "https://secret.example/path token=abc"

        val presentation = UpdatePresentation.from(UpdateState.Failed(secret))

        assertFalse(presentation.blocksKiosk)
        assertEquals(UpdateMessage.FAILURE, presentation.message)
        assertNull(presentation.versionName)
        assertNull(presentation.progress)
        assertFalse(presentation.toString().contains(secret))
        assertFalse(presentation.toString().contains("token=abc"))
    }
}
