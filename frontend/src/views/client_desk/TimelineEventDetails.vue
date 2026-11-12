<template>
  <article class="event-detail">
    <header>
      <h3>{{ timelineTitle(event) }}</h3>
      <p v-if="event.occurred_at" class="meta">
        {{ event.source === 'order' ? formatBeijingDate(event.occurred_at) : formatBeijingDateTime(event.occurred_at, { seconds: false }) }}
      </p>
    </header>

    <template v-if="event.source === 'order'">
      <dl class="facts">
        <div><dt>订单金额</dt><dd>{{ orderAmount(event.amount_usd) }}</dd></div>
        <div v-if="event.order_no"><dt>订单号</dt><dd>{{ event.order_no }}</dd></div>
        <div v-if="event.status_name"><dt>订单状态</dt><dd>{{ event.status_name }}</dd></div>
      </dl>
      <section>
        <h4>产品明细</h4>
        <ul v-if="event.products?.length" class="products">
          <li v-for="product in event.products" :key="product.id">
            <div>
              <strong>{{ product.name || product.model || '产品名称未同步' }}</strong>
              <p v-if="product.model && product.name" class="meta">型号 {{ product.model }}</p>
            </div>
            <span>{{ product.quantity == null ? '数量未同步' : `数量 ${product.quantity}` }}</span>
          </li>
        </ul>
        <p v-else class="meta">这笔订单暂无已同步的产品明细。</p>
      </section>
    </template>

    <dl v-else-if="event.card" class="facts">
      <div><dt>客户名称</dt><dd>{{ event.card.name || '未同步' }}</dd></div>
      <div><dt>国家或地区</dt><dd>{{ event.card.country || '未同步' }}</dd></div>
    </dl>

    <template v-else-if="event.source === 'rule'">
      <p>{{ event.summary || '这条提醒由方舟根据当前可见的客户资料和跟进记录生成。' }}</p>
      <dl v-if="event.next_followup_date || event.next_followup_remark" class="facts">
        <div v-if="event.next_followup_date"><dt>计划跟进</dt><dd>{{ formatBeijingDate(event.next_followup_date) }}</dd></div>
        <div v-if="event.next_followup_remark"><dt>跟进说明</dt><dd>{{ event.next_followup_remark }}</dd></div>
      </dl>
    </template>

    <template v-else-if="event.source === 'research'">
      <ResearchReport :report="event.report" />
    </template>

    <ul v-else-if="event.messages?.length" class="messages">
      <li v-for="message in event.messages" :key="message.id || message.key">
        <small class="meta">{{ message.sender_name || senderLabel(message) }} · {{ formatBeijingDateTime(message.occurred_at || message.sent_at || message.at, { seconds: false }) }}</small>
        <p>{{ message.content || message.text || '暂无可显示的正文' }}</p>
      </li>
    </ul>
    <p v-else>{{ event.content || event.text || event.summary || '这条记录暂无更多已同步内容。' }}</p>
  </article>
</template>

<script setup>
import ResearchReport from './ResearchReport.vue'
import { formatBeijingDate, formatBeijingDateTime } from '@/utils/datetime'
import { orderAmount, timelineTitle } from './deskController'

defineProps({ event: { type: Object, required: true } })

function senderLabel(message) {
  return ({ inbound: '客户', outbound: '我方' })[message.direction] || '发送方未知'
}
</script>

<style scoped>
.event-detail { line-height: 1.6; overflow-wrap: anywhere; }
.event-detail h3 { font-size: 20px; margin: 0; }
.event-detail h4 { font-size: 15px; margin: 18px 0 8px; }
.event-detail p { white-space: pre-wrap; }
.meta { color: var(--text-secondary); font-size: 12px; margin: 4px 0; }
.facts { display: grid; gap: 10px; margin: 16px 0; }
.facts > div { display: grid; grid-template-columns: minmax(76px, auto) 1fr; gap: 12px; }
.facts dt { color: var(--text-secondary); }
.facts dd { margin: 0; font-weight: 600; white-space: pre-wrap; }
.products, .messages { margin: 0; padding: 0; list-style: none; }
.products li, .messages li { padding: 12px 0; border-bottom: 1px solid var(--border-color); }
.products li { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.products li > div { min-width: 0; }
.products li > span { flex: none; }
.messages p { margin: 4px 0; }
</style>
