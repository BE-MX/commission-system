<template>
  <div>
    <div class="page-header">
      <h2>本地成品库存账</h2>
      <p>仅反映方舟本地交易的成品库存，所有数量以件计。隔离、破损库存不计入可售；单据过账后通过受约束冲销纠正。</p>
    </div>
    <el-tabs v-model="tab">
      <el-tab-pane label="库存余额" name="balances" lazy>
        <StockRows mode="balances" />
      </el-tab-pane>
      <el-tab-pane label="库存流水" name="ledger" lazy>
        <StockRows mode="ledger" />
      </el-tab-pane>
      <el-tab-pane label="库存单据" name="documents" lazy>
        <StockDocuments />
      </el-tab-pane>
      <el-tab-pane label="仓库" name="warehouses" lazy>
        <Warehouses />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>
<script setup>
import { ref } from 'vue'
import StockRows from './StockRows.vue'
import StockDocuments from './StockDocuments.vue'
import Warehouses from './Warehouses.vue'
const tab = ref('balances')
</script>
