<template>
  <el-dropdown trigger="click" @command="handleExport">
    <GlassButton variant="link" left-icon="Download" right-icon="ArrowDown">
      导出
    </GlassButton>
    <template #dropdown>
      <el-dropdown-menu>
        <el-dropdown-item command="all"><el-icon><Document /></el-icon> 全部明细</el-dropdown-item>
        <el-dropdown-item command="salesperson"><el-icon><User /></el-icon> 按业务员</el-dropdown-item>
        <el-dropdown-item command="supervisor"><el-icon><UserFilled /></el-icon> 按一级主管</el-dropdown-item>
        <el-dropdown-item command="customer"><el-icon><OfficeBuilding /></el-icon> 按客户</el-dropdown-item>
        <el-dropdown-item command="sp_summary" divided><el-icon><TrendCharts /></el-icon> 业务员汇总</el-dropdown-item>
        <el-dropdown-item command="sv_summary"><el-icon><TrendCharts /></el-icon> 一级主管汇总</el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>

<script setup>
// 批次导出菜单：全部/按角色/按客户明细 + 业务员/主管汇总，批次列表各状态行共用。
import { exportCommissionDetails, exportSalespersonSummary, exportSupervisorSummary } from '@/api/report'
import { downloadBlob } from '@/utils/download'

const props = defineProps({
  batchId: { type: [Number, String], required: true },
})

async function handleExport(cmd) {
  let res
  if (cmd === 'sp_summary') {
    res = await exportSalespersonSummary(props.batchId)
  } else if (cmd === 'sv_summary') {
    res = await exportSupervisorSummary(props.batchId)
  } else {
    const groupBy = cmd === 'all' ? '' : cmd
    res = await exportCommissionDetails(props.batchId, groupBy)
  }
  downloadBlob(res)
}
</script>
