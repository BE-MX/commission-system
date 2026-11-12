<template>
  <article class="stats-card stats-insight lg-card is-static">
    <h4>{{ item.shop_name || item.title }}<StatusBadge v-if="item.customer_level">{{ item.customer_level }}</StatusBadge><StatusBadge v-for="signal in item.signals" :key="signal" type="info">{{ signal }}</StatusBadge>
      <StatusBadge v-if="['common', 'practice', 'frequency'].includes(item.category)" type="warning">样本 {{ item.sample_size }} 家</StatusBadge></h4>
    <p v-if="item.shop_name && item.title !== item.shop_name" class="stats-insight__why"><strong>{{ item.title }}</strong></p>
    <p class="stats-insight__why">{{ item.body }}</p>
    <p v-if="item.order_comparison" class="stats-insight__meta">当前订单权限内：近 90 天 {{ item.order_comparison.recent_count }} 单 / ¥{{ item.order_comparison.recent_amount }}，前 90 天 {{ item.order_comparison.previous_count }} 单 / ¥{{ item.order_comparison.previous_amount }}。</p>
    <div v-if="item.suggested_action" class="stats-insight__do"><b>建议：</b>{{ item.suggested_action }}<span v-if="item.suggested_date" class="stats-hint"> · {{ item.suggested_date }}</span></div>
    <p v-if="['practice', 'frequency'].includes(item.category)" class="stats-insight__meta">小样本观察，不代表因果结论。</p>
    <div class="stats-evidence" :class="{ 'is-open': expanded }"><div>
      <blockquote v-for="evidence in item.evidence" :key="evidence.id" class="stats-quote">
        <small>{{ evidence.followup_date }} {{ evidence.channel || '' }} · {{ evidence.shop_name }} · {{ evidence.author_name }}</small>
        {{ evidence.raw_text || evidence.summary }}<template v-if="evidence.items?.length"><br />{{ evidence.items.join('；') }}</template>
      </blockquote>
    </div></div>
    <div class="stats-insight__ops">
      <template v-if="!company">
        <GlassButton v-if="item.task_id" disabled>已生成待办</GlassButton>
        <GlassButton v-else-if="item.can_task" variant="primary" @click="$emit('task', item)">生成待办</GlassButton>
        <GlassButton v-if="item.can_record" v-permission="'domestic_followup:write'" @click="$emit('record', item)">记一条跟进</GlassButton>
      </template>
      <GlassButton v-else-if="item.can_adopt" :variant="item.adopted ? 'soft' : 'secondary'" :disabled="item.adopted" @click="$emit('adopt', item)">{{ item.adopted ? '已采纳' : '标记已采纳' }}</GlassButton>
      <GlassButton v-if="item.evidence.length" variant="link" :aria-expanded="expanded" @click="expanded = !expanded">{{ expanded ? '收起证据' : `看证据（${item.evidence.length}）` }}</GlassButton>
      <StatusBadge v-if="item.deidentified">已脱敏 · 不显示他人客户</StatusBadge>
      <span class="stats-spacer" />
      <GlassButton variant="ghost" :active="item.feedback === 'up'" :aria-pressed="item.feedback === 'up'" aria-label="有用" title="有用" @click="$emit('feedback', item, item.feedback === 'up' ? null : 'up')"><template #left-icon><el-icon><CircleCheck /></el-icon></template></GlassButton>
      <GlassButton variant="ghost" :active="item.feedback === 'down'" :aria-pressed="item.feedback === 'down'" aria-label="不准" title="不准，下次别这样" @click="$emit('feedback', item, item.feedback === 'down' ? null : 'down')"><template #left-icon><el-icon><CircleClose /></el-icon></template></GlassButton>
    </div>
    <p v-if="item.adoption_note" class="stats-insight__meta">采纳备注：{{ item.adoption_note }}</p>
    <p class="stats-insight__meta">AI 分析 · {{ formatBeijingShortDateTime(item.generated_at || generatedAt) }} · 依据 {{ item.evidence.length || item.sample_size }} {{ item.deidentified ? '家客户' : '条记录' }}</p>
  </article>
</template>
<script setup>
import StatusBadge from '@/components/StatusBadge.vue'
import { ref, watch } from 'vue'
import { CircleCheck, CircleClose } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import { formatBeijingShortDateTime } from '@/utils/datetime'
const props = defineProps({ item: { type: Object, required: true }, company: Boolean, generatedAt: String, recordCount: { type: Number, default: 0 } })
defineEmits(['task', 'record', 'adopt', 'feedback'])
const expanded = ref(false)
watch(() => props.item.id, () => { expanded.value = false })
</script>
