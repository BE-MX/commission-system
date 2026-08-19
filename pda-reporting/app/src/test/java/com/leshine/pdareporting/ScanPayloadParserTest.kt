package com.leshine.pdareporting

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ScanPayloadParserTest {
    @Test
    fun parsesQuantityCard() {
        val parsed = ScanPayloadParser.parse("ARK-D:123:abcdef1234567890")!!
        assertEquals(ScanPayload.Type.ITEM, parsed.type)
        assertEquals(123L, parsed.id)
        assertEquals("abcdef1234567890", parsed.sign)
    }

    @Test
    fun parsesUnitCardAndTrimsScannerSuffix() {
        val parsed = ScanPayloadParser.parse("  ARK-DU:987:ABCDEF12\u0000\n")!!
        assertEquals(ScanPayload.Type.UNIT, parsed.type)
        assertEquals(987L, parsed.id)
        assertEquals("abcdef12", parsed.sign)
    }

    @Test
    fun rejectsForeignAndMalformedCodes() {
        assertNull(ScanPayloadParser.parse("ARK-P:123:abcdef12"))
        assertNull(ScanPayloadParser.parse("ARK-D:nope:abcdef12"))
        assertNull(ScanPayloadParser.parse("ARK-D:999999999999999999999999999999:abcdef12"))
        assertNull(ScanPayloadParser.parse("https://example.com"))
    }
}
