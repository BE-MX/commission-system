package com.leshine.pdareporting

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ScanBroadcastContractTest {
    @Test
    fun routesA4gThroughManifestAndPreservesDefaultCategoryCompatibility() {
        assertFalse(ScanBroadcastContract.dynamicActions.contains(ScanBroadcastContract.VENDOR_ACTION))
        assertTrue(ScanBroadcastContract.requiredCategories.contains("android.intent.category.DEFAULT"))
    }

    @Test
    fun readsVendorBarcodeStringFirst() {
        assertEquals(
            "ARK-D:1:abcdef12",
            ScanBroadcastContract.extract(
                mapOf(
                    "data" to "wrong",
                    "barcode_string" to "  ARK-D:1:abcdef12  ",
                ),
            ),
        )
    }

    @Test
    fun decodesVendorByteArrayAndRejectsEmptyPayload() {
        assertEquals(
            "ARK-DU:2:abcdef12",
            ScanBroadcastContract.extract(
                mapOf("barcode_string" to "ARK-DU:2:abcdef12\u0000".toByteArray()),
            ),
        )
        assertNull(ScanBroadcastContract.extract(mapOf("barcode_string" to "  ")))
    }

    @Test
    fun bridgeOnlyForwardsWhileForegroundListenerIsAttached() {
        val received = mutableListOf<Pair<String, String?>>()
        val listener: (String, String?) -> Unit = { action, code -> received += action to code }

        ScanBroadcastBridge.attach(listener)
        ScanBroadcastBridge.publish(ScanBroadcastContract.VENDOR_ACTION, "ARK-D:1:abcdef12")
        ScanBroadcastBridge.detach(listener)
        ScanBroadcastBridge.publish(ScanBroadcastContract.VENDOR_ACTION, "ARK-D:2:abcdef12")

        assertEquals(
            listOf(ScanBroadcastContract.VENDOR_ACTION to "ARK-D:1:abcdef12"),
            received,
        )
    }
}
