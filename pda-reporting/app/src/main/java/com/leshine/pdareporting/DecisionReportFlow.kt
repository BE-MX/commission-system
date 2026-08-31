package com.leshine.pdareporting

data class DecisionOption(val code: String, val label: String)

data class DecisionSubmission(
    val qty: Int,
    val outcomes: LinkedHashMap<String, Int>,
)

object DecisionReportFlow {
    fun normalizeOptions(values: List<DecisionOption>): List<DecisionOption> {
        val normalized = values.map { DecisionOption(it.code.trim(), it.label.trim()) }
        require(normalized.isNotEmpty()) { "当前工序没有可选结果" }
        require(normalized.all { it.code.isNotEmpty() && it.label.isNotEmpty() }) { "处理结果配置不完整" }
        require(normalized.map { it.code }.distinct().size == normalized.size) { "处理结果编码不能重复" }
        return normalized
    }

    fun validate(maxQty: Int, values: Map<String, Int>): DecisionSubmission {
        require(maxQty > 0) { "当前没有可报数量" }
        val normalized = linkedMapOf<String, Int>()
        var total = 0
        values.forEach { (code, qty) ->
            require(code.isNotBlank()) { "结果编码不能为空" }
            require(qty >= 0) { "分配数量不能为负数" }
            if (qty > 0) normalized[code] = qty
            total += qty
        }
        require(total > 0) { "至少一个结果需要分配数量" }
        require(total <= maxQty) { "分配总数不能超过可报数量" }
        return DecisionSubmission(total, normalized)
    }

    fun validateUnit(optionCodes: List<String>, selectedCode: String?): DecisionSubmission {
        require(selectedCode != null && optionCodes.count { it == selectedCode } == 1) {
            "请选择一个有效处理结果"
        }
        return DecisionSubmission(1, linkedMapOf(selectedCode to 1))
    }
}
