<script setup>
/** 验货单详情里的物流单区块：展示当前关联，上传/更换走与列表操作列同一个弹框。 */
defineProps({ detail: { type: Object, required: true } })
defineEmits(['upload'])
</script>
<template>
  <section aria-label="物流单" class="shipment-section">
    <h3>物流单</h3>
    <p v-if="detail.shipment">
      {{ detail.shipment.carrier }} ·
      <router-link :to="`/tracking/${encodeURIComponent(detail.shipment.waybill_no)}`">{{ detail.shipment.waybill_no }}</router-link>
    </p>
    <p v-else class="shipment-empty">尚未关联物流单</p>
    <span v-if="detail.status === 'submitted'" v-permission="'tracking:write'">
      <GlassButton v-any-permission="['shipping_inspection:write', 'shipping_inspection:admin']"
        left-icon="Upload" @click="$emit('upload')">{{ detail.shipment ? '更换物流单' : '上传物流单' }}</GlassButton>
    </span>
  </section>
</template>
<style scoped>
.shipment-section { margin-block: 20px; }
.shipment-section a { color: var(--color-primary-text); }
.shipment-empty { color: var(--text-secondary); }
</style>
