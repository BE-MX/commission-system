<template>
  <div>
    <div class="page-header"><h2>交易历史承接</h2><p>按已核验清单接管原业务责任。完整合同、已消费资金和历史媒体保留，核对全部期末责任后放行。</p></div>
    <MigrationImportPanel @applied="records?.refresh()" />
    <MigrationRecords ref="records" />
  </div>
</template>
<script setup>
import { ref } from 'vue'
import MigrationImportPanel from './MigrationImportPanel.vue'
import MigrationRecords from './MigrationRecords.vue'
const records = ref()
</script>
