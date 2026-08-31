package com.leshine.pdareporting

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class DecisionReportFlowTest {
    @Test
    fun options_are_trimmed_and_keep_backend_order() {
        val result = DecisionReportFlow.normalizeOptions(
            listOf(DecisionOption(" dandong ", " 丹东 "), DecisionOption("lixiaohong", "李晓宏")),
        )

        assertEquals(
            listOf(DecisionOption("dandong", "丹东"), DecisionOption("lixiaohong", "李晓宏")),
            result,
        )
        assertThrows(IllegalArgumentException::class.java) {
            DecisionReportFlow.normalizeOptions(
                listOf(DecisionOption("same", "结果一"), DecisionOption("same", "结果二")),
            )
        }
    }

    @Test
    fun quantity_outcomes_preserve_option_order_and_sum_to_qty() {
        val result = DecisionReportFlow.validate(
            maxQty = 20,
            values = linkedMapOf("dandong" to 12, "unused" to 0, "lixiaohong" to 8),
        )

        assertEquals(20, result.qty)
        assertEquals(linkedMapOf("dandong" to 12, "unused" to 0, "lixiaohong" to 8), result.outcomes)
    }

    @Test
    fun quantity_outcomes_must_be_positive_and_within_maximum() {
        assertThrows(IllegalArgumentException::class.java) {
            DecisionReportFlow.validate(20, linkedMapOf("dandong" to 0, "lixiaohong" to 0))
        }
        assertThrows(IllegalArgumentException::class.java) {
            DecisionReportFlow.validate(20, linkedMapOf("dandong" to -1, "lixiaohong" to 1))
        }
        assertThrows(IllegalArgumentException::class.java) {
            DecisionReportFlow.validate(20, linkedMapOf("dandong" to 12, "lixiaohong" to 9))
        }
    }

    @Test
    fun unit_decision_requires_exactly_one_known_option() {
        val result = DecisionReportFlow.validateUnit(
            optionCodes = listOf("dandong", "lixiaohong"),
            selectedCode = "lixiaohong",
        )

        assertEquals(1, result.qty)
        assertEquals(linkedMapOf("lixiaohong" to 1), result.outcomes)
        assertThrows(IllegalArgumentException::class.java) {
            DecisionReportFlow.validateUnit(listOf("dandong", "lixiaohong"), null)
        }
        assertThrows(IllegalArgumentException::class.java) {
            DecisionReportFlow.validateUnit(listOf("dandong", "lixiaohong"), "other")
        }
    }
}
