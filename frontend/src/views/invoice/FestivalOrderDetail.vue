<template>
  <div class="festival-order-page">
    <div class="festival-order-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <header class="festival-order-header">
      <div>
        <h2>采购节数据明细</h2>
        <p>直接核对采购节新签、首返和复购订单及其统计口径。</p>
      </div>
      <div v-if="summary.can_read_all" class="scope-selector">
        <span>查看范围</span>
        <el-select v-model="selectedUserId" placeholder="全公司" @change="changeScope">
          <el-option label="全公司" value="" />
          <el-option
            v-for="user in summary.users"
            :key="user.user_id"
            :label="user.user_name"
            :value="user.user_id"
          />
        </el-select>
      </div>
    </header>

    <el-alert
      v-if="error"
      class="festival-order-error"
      :title="error"
      type="error"
      show-icon
      :closable="false"
    >
      <template #default>
        <el-button link type="danger" @click="loadPage()">重新加载</el-button>
      </template>
    </el-alert>

    <section class="festival-metrics" aria-label="采购节统计">
      <article class="festival-metric-card festival-metric-card--primary lg-card is-static">
        <span>新签完成进度</span>
        <div class="metric-value">
          <strong>{{ summary.new_sign.count }}</strong>
          <small>/ {{ summary.new_sign.target }} 个客户</small>
        </div>
        <el-progress :percentage="summary.new_sign.progress_percent" :stroke-width="8" />
        <p>完成 {{ summary.new_sign.progress_percent }}% · 积分 {{ number(summary.new_sign.points) }}</p>
      </article>
      <article class="festival-metric-card lg-card is-static">
        <span>首返客户数</span>
        <div class="metric-value"><strong>{{ summary.first_return_count }}</strong><small>个客户</small></div>
        <p>按客户去重统计</p>
      </article>
      <article class="festival-metric-card lg-card is-static">
        <span>复购金额</span>
        <div class="metric-value"><strong>USD {{ money(summary.repurchase_amount) }}</strong></div>
        <p>有效复购订单金额合计</p>
      </article>
    </section>

    <section class="festival-order-panel table-card">
      <el-tabs v-model="activeType" class="festival-tabs" @tab-change="changeType">
        <el-tab-pane label="新签订单" name="new_sign" />
        <el-tab-pane label="首返订单" name="first_return" />
        <el-tab-pane label="复购订单" name="repurchase" />
      </el-tabs>

      <div class="festival-order-toolbar">
        <el-input
          v-model="filters.keyword"
          clearable
          placeholder="搜索订单号或客户名称"
          @keyup.enter="search"
          @clear="search"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-button type="primary" @click="search">
          <el-icon><Search /></el-icon>
          查询
        </el-button>
        <span class="activity-window">{{ windowText }}</span>
      </div>

      <el-table v-loading="loading" :data="orders" border class="list-table festival-order-table">
        <template #empty>
          <div class="festival-order-empty">
            <strong>当前范围暂无{{ activeLabel }}</strong>
            <span>可切换标签或调整搜索关键词继续查看。</span>
          </div>
        </template>
        <el-table-column prop="order_no" label="订单号" min-width="150" max-width="190" show-overflow-tooltip />
        <el-table-column prop="account_date" label="记账日期" min-width="108" max-width="128" />
        <el-table-column prop="amount_usd" label="金额（USD）" min-width="120" max-width="150" align="right">
          <template #default="{ row }">{{ money(row.amount_usd) }}</template>
        </el-table-column>
        <el-table-column prop="company_name" label="客户名称" min-width="180" max-width="300" show-overflow-tooltip />
        <el-table-column prop="user_name" label="业务员" min-width="96" max-width="120" />
        <el-table-column prop="team" label="所属团队" min-width="116" max-width="150" show-overflow-tooltip />
        <el-table-column prop="camp" label="所属阵营" min-width="100" max-width="130" show-overflow-tooltip />
        <el-table-column v-if="activeType === 'new_sign'" prop="points" label="积分" min-width="76" max-width="90" align="right">
          <template #default="{ row }">
            <span>{{ number(row.points) }}</span>
            <el-tooltip v-if="row.points_note" :content="row.points_note" placement="top">
              <el-tag class="points-note" type="info" effect="plain">已计分</el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <div class="festival-order-pagination">
      <el-pagination
        v-model:current-page="pagination.page"
        v-model:page-size="pagination.page_size"
        :total="pagination.total"
        :page-sizes="[20, 50, 100]"
        layout="total,sizes,prev,pager,next,jumper"
        @size-change="changePage"
        @current-change="changePage"
      />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { useFestivalOrderDetail } from './composables/useFestivalOrderDetail'

const {
  activeType, changePage, changeScope, changeType, error, filters, loadPage,
  loading, orders, pagination, search, selectedUserId, summary,
} = useFestivalOrderDetail()

const labels = { new_sign: '新签订单', first_return: '首返订单', repurchase: '复购订单' }
const activeLabel = computed(() => labels[activeType.value])
const windowText = computed(() => activeType.value === 'new_sign'
  ? '统计周期：8月1日—8月31日'
  : '统计周期：8月1日—9月30日')
const money = value => Number(value || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const number = value => Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 1 })
</script>

<style scoped src="./festival-order-detail.css"></style>
