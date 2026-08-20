package com.leshine.pdareporting

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class UnitReportFlowTest {
    @Test
    fun unit_mode_always_auto_submits() {
        assertTrue(UnitReportFlow.shouldAutoSubmit("unit"))
        assertFalse(UnitReportFlow.shouldAutoSubmit("quantity"))
        assertFalse(UnitReportFlow.shouldAutoSubmit(""))
    }

    @Test
    fun submitting_blocks_close_and_next_scan() {
        val state = UnitReportFlow.submitting()

        assertEquals(UnitReportTone.PROGRESS, state.tone)
        assertFalse(state.closeEnabled)
        assertFalse(state.nextScanEnabled)
        assertNull(state.autoHideAfterMs)
    }

    @Test
    fun scanning_next_item_clears_previous_result_and_blocks_actions() {
        val state = UnitReportFlow.scanning()

        assertEquals(UnitReportTone.PROGRESS, state.tone)
        assertEquals("正在识别下一件…", state.message)
        assertFalse(state.closeEnabled)
        assertFalse(state.nextScanEnabled)
    }

    @Test
    fun success_allows_close_and_next_scan_for_three_seconds() {
        val state = UnitReportFlow.success("植发 · 1 件")

        assertEquals(UnitReportTone.SUCCESS, state.tone)
        assertEquals("✓ 报工成功\n植发 · 1 件", state.message)
        assertTrue(state.closeEnabled)
        assertTrue(state.nextScanEnabled)
        assertEquals(3_000L, state.autoHideAfterMs)
    }

    @Test
    fun explicit_error_allows_rescan_without_auto_hiding() {
        val state = UnitReportFlow.error("操作失败：当前不能报工")

        assertEquals(UnitReportTone.ERROR, state.tone)
        assertTrue(state.closeEnabled)
        assertTrue(state.nextScanEnabled)
        assertNull(state.autoHideAfterMs)
    }
}
