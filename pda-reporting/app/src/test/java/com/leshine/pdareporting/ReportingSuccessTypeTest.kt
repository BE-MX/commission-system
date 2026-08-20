package com.leshine.pdareporting

import org.junit.Assert.assertEquals
import org.junit.Test

class ReportingSuccessTypeTest {
    @Test
    fun report_and_revoke_use_distinct_success_titles() {
        assertEquals("✓ 报工成功", ReportingSuccessType.REPORT.title)
        assertEquals("✓ 撤销成功", ReportingSuccessType.REVOKE.title)
    }
}
