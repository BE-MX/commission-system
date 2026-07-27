<template>
  <div class="quality-pick">
    <div class="qp-title">出图档位<small>赶时间可选速览，画质略简</small></div>
    <div class="qp-opts">
      <button
        v-for="o in OPTIONS" :key="o.value"
        class="qp-opt" :class="{ on: modelValue === o.value }"
        @click="$emit('update:modelValue', o.value)"
      >
        <b>{{ o.label }}</b>
        <small>{{ o.hint }}</small>
      </button>
    </div>
  </div>
</template>

<script setup>
defineProps({ modelValue: { type: String, default: 'high' } })
defineEmits(['update:modelValue'])

// 值必须与后端 GenerateRequest.quality 的 pattern ^(high|medium)$ 一致。
// 时长是实测均值（high 107s / medium 55s），写「约」是因为上游排队波动很大
// （生产 225 次样本 26.9s~291.8s），不敢承诺准点。
const OPTIONS = [
  { value: 'high', label: '精致大片', hint: '细节最丰富 · 约 2 分钟' },
  { value: 'medium', label: '形象速览', hint: '快一倍 · 约 1 分钟' },
]
</script>

<style scoped>
.quality-pick { width: 100%; }
.qp-title {
  font-size: 11px; letter-spacing: 0.24em; color: var(--xk-gold-dim);
  display: flex; align-items: baseline; gap: 10px;
}
.qp-title small { font-size: 10px; letter-spacing: 0.1em; color: var(--xk-mut); }
.qp-opts { display: flex; gap: 10px; margin-top: 10px; }
.qp-opt {
  flex: 1; min-width: 0;
  display: flex; flex-direction: column; align-items: center; gap: 3px;
  padding: 10px 12px; border-radius: 16px; cursor: pointer;
  border: 1px solid var(--xk-gold-line); background: transparent;
  transition: transform 160ms cubic-bezier(0.23, 1, 0.32, 1), border-color 160ms ease,
    background 160ms ease, box-shadow 160ms ease;
}
.qp-opt:active { transform: scale(0.97); }
.qp-opt b {
  font-family: 'Noto Serif SC', serif; font-size: 15px; font-weight: 500;
  letter-spacing: 0.08em; color: var(--xk-mut); transition: color 160ms ease;
}
.qp-opt small { font-size: 10px; letter-spacing: 0.06em; color: var(--xk-gold-dim); }
.qp-opt.on {
  border-color: var(--xk-gold);
  background: rgba(232, 196, 121, 0.08);
  box-shadow: 0 0 16px rgba(232, 196, 121, 0.14);
}
.qp-opt.on b { color: var(--xk-gold-hi); }

@media (max-width: 560px) {
  .qp-opt { padding: 9px 8px; }
  .qp-opt b { font-size: 14px; }
}
</style>
